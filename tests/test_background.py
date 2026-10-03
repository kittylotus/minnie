import http.client
import json
import threading
import time
import unittest
import uuid
from unittest.mock import patch
import app


class BackgroundResearchTests(unittest.TestCase):
    def setUp(self):
        ident=uuid.uuid4().hex
        for key,suffix in [('CHATS','.sqlite'),('PRESETS','.json')]:
            path=app.DATA/('background-test-'+ident+suffix)
            self.addCleanup(lambda p=path:p.unlink(missing_ok=True))
            self.addCleanup(lambda p=path:p.with_suffix('.tmp').unlink(missing_ok=True))
            patcher=patch.object(app,key,path);patcher.start();self.addCleanup(patcher.stop)
        patcher=patch.object(app,'settings',return_value={'llm':{'model':'fixture'},'customInstructions':''});patcher.start();self.addCleanup(patcher.stop)

    def test_disconnected_viewer_reconnects_to_same_job_and_saved_answer(self):
        server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);server.daemon_threads=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        client=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=4)
        viewer=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=4)
        ready=threading.Event();release=threading.Event();calls=[]
        def completion(config,payload,emit,control=None):
            calls.append(payload);emit('delta',{'answer':'Partial answer','reasoning':'Partial reasoning'});ready.set()
            release.wait(5);control.check();emit('delta',{'answer':'Finished answer','reasoning':'Finished reasoning'})
            return {'content':'Finished answer','reasoning_content':'Finished reasoning'}
        def post(path,payload):
            client.request('POST',path,json.dumps(payload),{'Content-Type':'application/json'})
            response=client.getresponse();body=json.loads(response.read());self.assertEqual(response.status,200,body);return body
        try:
            with patch.object(app,'stream_completion',side_effect=completion):
                identity=post('/api/research/start',{'query':'A question','depth':'chat'})
                self.assertTrue(ready.wait(3))
                viewer.request('POST','/api/research/events',json.dumps(identity),{'Content-Type':'application/json'})
                response=viewer.getresponse();self.assertEqual(response.status,200)
                self.assertEqual(response.readline().strip(),b'event: chat');response.readline();response.readline()
                self.assertEqual(response.readline().strip(),b'event: snapshot')
                snapshot=json.loads(response.readline().decode().removeprefix('data: '))
                self.assertEqual(snapshot['answer'],'Partial answer')
                response.close();viewer.close()  # The PWA/browser disappears mid-response.
                snapshot=post('/api/research/state',identity)
                self.assertEqual(snapshot['status'],'pending');self.assertFalse(app.JOBS[identity['runId']].cancelled.is_set())
                release.set()
                deadline=time.monotonic()+4
                while time.monotonic()<deadline:
                    snapshot=post('/api/research/state',identity)
                    if snapshot['status']=='complete':break
                    time.sleep(.02)
                self.assertEqual(snapshot['status'],'complete');self.assertEqual(snapshot['result']['answer'],'Finished answer')
                self.assertEqual(len(calls),1)
                self.assertEqual(len(app.get_chat(identity['chatId'])['turns']),1)
                viewer=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=4)
                viewer.request('POST','/api/research/events',json.dumps(identity),{'Content-Type':'application/json'})
                response=viewer.getresponse();body=response.read()
                self.assertIn(b'Finished answer',body);self.assertIn(b'event: done',body)
                with app.RUN_LOCK:app.JOBS.pop(identity['runId'])
                persisted=post('/api/research/state',identity)
                self.assertEqual(persisted['result']['answer'],'Finished answer')
                self.assertEqual(persisted['status'],'complete')
        finally:
            release.set();client.close();viewer.close();server.shutdown();server.server_close();thread.join(3)

    def test_stop_uses_server_text_after_browser_loses_updates(self):
        ready=threading.Event();release=threading.Event();finished=threading.Event()
        def completion(config,payload,emit,control=None):
            try:
                emit('delta',{'answer':'Newer server text','reasoning':'Server reasoning'});ready.set();release.wait(5);control.check()
                return {'content':'Must not finish'}
            finally:finished.set()
        try:
            with patch.object(app,'stream_completion',side_effect=completion):
                identity=app.start_research({'query':'Question','depth':'chat'})
                self.assertTrue(ready.wait(3))
                app.stop_turn(identity['chatId'],identity['turnId'],{'answer':'Stale phone text'})
                state=app.research_state(**identity)
                self.assertEqual(state['status'],'stopped')
                self.assertEqual(state['result']['answer'],'Newer server text')
                self.assertEqual(state['result']['reasoning'],'Server reasoning')
                release.set();self.assertTrue(finished.wait(3))
        finally:release.set()


if __name__=='__main__':unittest.main()
