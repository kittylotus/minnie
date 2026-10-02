import json
import http.client
import threading
import unittest
import uuid
from unittest.mock import patch
import app


class ChatControlTests(unittest.TestCase):
    def setUp(self):
        self.path=app.DATA/('chat-controls-'+uuid.uuid4().hex+'.sqlite')
        self.addCleanup(lambda:self.path.unlink(missing_ok=True))
        patcher=patch.object(app,'CHATS',self.path);patcher.start();self.addCleanup(patcher.stop)

    def result(self,text):
        return {'answer':text,'reasoning':'','evidence':[],'retrieved':[],'trace':[],'citationWarning':False,'semantic':False,'mode':'chat'}

    def test_no_search_uses_history_without_any_retrieval_or_tools(self):
        chat,turn=app.begin_turn({'query':'My draft','depth':'chat'})
        app.finish_turn(turn,self.result('Earlier answer'))
        conf={'llm':{'model':'fixture'},'embedding':{},'customInstructions':'Use short paragraphs.'}
        with patch.object(app,'settings',return_value=conf),patch.object(app,'search') as search,patch.object(app,'context') as context,patch.object(app,'embed') as embed,patch.object(app,'readonly_sql') as sql,patch.object(app,'provider',return_value={'choices':[{'message':{'content':'<think>Plan</think>**Edited draft**'}}]}) as provider:
            result=app.research({'query':'Format that','chatId':chat,'depth':'chat'})
        for tool in (search,context,embed,sql):tool.assert_not_called()
        request=provider.call_args.args[2]
        self.assertNotIn('tools',request);self.assertNotIn('tool_choice',request)
        self.assertTrue(any(m['content']=='Earlier answer' for m in request['messages']))
        self.assertEqual(result['answer'],'**Edited draft**');self.assertEqual(result['reasoning'],'Plan')
        self.assertFalse(result['citationWarning']);self.assertEqual(result['mode'],'chat')

    def test_retry_preserves_alternatives_and_selected_followup_context(self):
        chat,turn=app.begin_turn({'query':'Question','depth':'chat','verbosity':'detailed'})
        app.finish_turn(turn,self.result('Original'))
        _,retry=app.begin_turn({'query':'Question','chatId':chat,'retryTurnId':turn,'depth':'chat','verbosity':'detailed'})
        self.assertEqual(retry,turn);self.assertEqual(app.chat_history(chat),[])
        app.finish_turn(retry,self.result('Alternative'))
        turns=app.get_chat(chat)['turns']
        self.assertEqual(len(turns),1);self.assertEqual(len(turns[0]['variants']),2)
        self.assertEqual(turns[0]['variants'][0]['result']['answer'],'Original')
        self.assertEqual(turns[0]['variant_index'],1)
        app.select_variant(chat,turn,0)
        self.assertEqual(app.chat_history(chat)[0]['result']['answer'],'Original')
        app.select_variant(chat,turn,1)
        self.assertEqual(app.chat_history(chat)[0]['result']['answer'],'Alternative')
        with self.assertRaisesRegex(ValueError,'not found'):app.select_variant(chat,turn,2)

    def test_retry_migrates_old_response_and_only_retries_latest_question(self):
        chat,turn=app.begin_turn({'query':'Old question'})
        with app.chat_db() as c:c.execute("UPDATE turns SET result=?,status='complete',variants=NULL WHERE id=?",(json.dumps(self.result('Legacy answer')),turn))
        app.begin_turn({'query':'Old question','chatId':chat,'retryTurnId':turn})
        app.finish_turn(turn,self.result('New answer'))
        self.assertEqual(app.get_chat(chat)['turns'][0]['variants'][0]['result']['answer'],'Legacy answer')
        _,next_turn=app.begin_turn({'query':'Next question','chatId':chat})
        app.finish_turn(next_turn,self.result('Next answer'))
        with self.assertRaisesRegex(ValueError,'latest'):app.begin_turn({'query':'Old question','chatId':chat,'retryTurnId':turn})

    def test_stop_saves_partial_and_old_worker_cannot_overwrite_retry(self):
        started=threading.Event();release=threading.Event();errors=[];ids={}
        handler=object.__new__(app.Handler)
        def emit(event,data):
            if event=='chat':ids.update(data)
        def generate(payload,emit,control):
            if payload.get('retryTurnId'):return self.result('Retried answer')
            emit('delta',{'answer':'**Partial**','reasoning':'Working'})
            started.set();release.wait(5);control.check()
            return self.result('Old worker answer')
        def run():
            try:handler.persistent_research({'query':'Question','depth':'chat'},emit)
            except Exception as error:errors.append(error)
        with patch.object(app,'research',side_effect=generate):
            worker=threading.Thread(target=run);worker.start()
            try:
                self.assertTrue(started.wait(3))
                app.stop_turn(ids['chatId'],ids['turnId'],{'answer':'**Partial**','reasoning':'Working'})
                stopped=app.get_chat(ids['chatId'])['turns'][0]
                self.assertEqual(stopped['status'],'stopped');self.assertEqual(stopped['result']['answer'],'**Partial**')
                self.assertEqual(app.chat_history(ids['chatId']),[])
                handler.persistent_research({'query':'Question','depth':'chat','chatId':ids['chatId'],'retryTurnId':ids['turnId']})
            finally:release.set();worker.join(3)
        self.assertFalse(worker.is_alive());self.assertIsInstance(errors[0],app.GenerationStopped)
        latest=app.get_chat(ids['chatId'])['turns'][0]
        self.assertEqual(latest['result']['answer'],'Retried answer')
        self.assertEqual(len(latest['variants']),2)
        self.assertEqual(latest['variants'][0]['status'],'stopped')
        self.assertFalse(app.stop_turn(ids['chatId'],ids['turnId'])['stopped'])

    def test_comparison_blocked_while_generating(self):
        chat,turn=app.begin_turn({'query':'Q'})
        app.finish_turn(turn,self.result('A'))
        app.begin_turn({'query':'Q','chatId':chat,'retryTurnId':turn})
        with self.assertRaisesRegex(ValueError,'Stop'):app.select_variant(chat,turn,0)

    def test_stream_stop_retry_and_comparison_http_contract(self):
        server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);server.daemon_threads=True
        server_thread=threading.Thread(target=server.serve_forever,daemon=True);server_thread.start()
        connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
        client=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
        ready=threading.Event();release=threading.Event()
        def completion(config,payload,emit,control=None):
            self.assertNotIn('tools',payload)
            emit('delta',{'answer':'**Partial text**','reasoning':''});ready.set();release.wait(5);control.check()
            return {'content':'Should not finish'}
        def post(path,payload):
            client.request('POST',path,json.dumps(payload),{'Content-Type':'application/json'})
            response=client.getresponse();body=json.loads(response.read());self.assertEqual(response.status,200,body);return body
        try:
            with patch.object(app,'settings',return_value={'llm':{'model':'fixture'},'customInstructions':''}),patch.object(app,'stream_completion',side_effect=completion):
                connection.request('POST','/api/research/stream',json.dumps({'query':'Format this','depth':'chat'}),{'Content-Type':'application/json'})
                response=connection.getresponse()
                self.assertEqual(response.status,200)
                self.assertEqual(response.readline().strip(),b'event: chat')
                identity=json.loads(response.readline().decode().removeprefix('data: '));response.readline()
                self.assertTrue(ready.wait(3))
                stopped=post('/api/research/stop',{**identity,'partial':{'answer':'**Partial text**'}})
                self.assertTrue(stopped['stopped']);release.set()
                self.assertIn(b'event: stopped',response.read())
            with patch.object(app,'settings',return_value={'llm':{'model':'fixture'},'customInstructions':''}),patch.object(app,'provider',return_value={'choices':[{'message':{'content':'Fresh answer'}}]}):
                result=post('/api/research',{'query':'Format this','depth':'chat','chatId':identity['chatId'],'retryTurnId':identity['turnId']})
                self.assertEqual(result['answer'],'Fresh answer')
            chat=post('/api/chat/variant',{**identity,'index':0})
            self.assertEqual(chat['turns'][0]['status'],'stopped')
            self.assertEqual(chat['turns'][0]['result']['answer'],'**Partial text**')
            chat=post('/api/chat/variant',{**identity,'index':1})
            self.assertEqual(chat['turns'][0]['result']['answer'],'Fresh answer')
        finally:
            release.set();connection.close();client.close();server.shutdown();server.server_close();server_thread.join(3)


if __name__=='__main__':unittest.main()
