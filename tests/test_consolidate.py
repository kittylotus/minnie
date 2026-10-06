import json
import re
import sqlite3
import unittest
import uuid
from unittest.mock import patch
import app


class ConsolidationTests(unittest.TestCase):
    def setUp(self):
        self.path=app.DATA/('consolidation-test-'+uuid.uuid4().hex+'.sqlite')
        self.chats=self.path.with_name(self.path.stem+'-chats.sqlite')
        for path in (self.path,self.chats):self.addCleanup(lambda p=path:p.unlink(missing_ok=True))
        with sqlite3.connect(self.path,factory=app.ManagedConnection) as c:
            c.executescript('''CREATE TABLE dialogues(id INTEGER,title TEXT);
                CREATE TABLE actors(id INTEGER,name TEXT);
                CREATE TABLE dentries(id INTEGER,conversationid INTEGER,actor INTEGER,dialoguetext TEXT,conditionstring TEXT,userscript TEXT,isgroup INTEGER,difficultypass INTEGER);
                CREATE TABLE dlinks(originconversationid INTEGER,origindialogueid INTEGER,destinationconversationid INTEGER,destinationdialogueid INTEGER,isConnector INTEGER,priority INTEGER);
                CREATE TABLE checks(conversationid INTEGER,dialogueid INTEGER,skilltype TEXT);
                CREATE TABLE modifiers(conversationid INTEGER,dialogueid INTEGER,tooltip TEXT);
                CREATE TABLE alternates(conversationid INTEGER,dialogueid INTEGER,condition TEXT,alternateline TEXT);
                INSERT INTO dialogues VALUES(1,'Church'),(2,'Money');
                INSERT INTO actors VALUES(1,'You'),(2,'Garte');
                INSERT INTO dentries VALUES(0,1,1,'','','',1,0),(1,1,2,'A fact.','','',0,0),(2,1,1,'Branch A','A','set A',0,4),(3,1,1,'Branch B','B','',0,0),(4,1,2,'','','',0,0),(1,2,2,'Other topic','','',0,0);
                INSERT INTO dlinks VALUES(1,0,1,1,0,0),(1,1,1,2,0,0),(1,1,1,3,0,0),(1,2,1,1,0,0),(1,3,2,1,1,0);
                INSERT INTO checks VALUES(1,2,'Logic');
                INSERT INTO modifiers VALUES(1,2,'A modifier');
                INSERT INTO alternates VALUES(1,4,'C','Alternate-only fact.');''')
        def source():
            c=sqlite3.connect(self.path,factory=app.ManagedConnection);c.row_factory=sqlite3.Row;return c
        self.preset={'id':'fixture','mainPrompt':'Ground facts.','chatPrompt':'Chat.','blocks':[]}
        for name,value in [('source',source),('CHATS',self.chats)]:
            p=patch.object(app,name,value);p.start();self.addCleanup(p.stop)
        for name,value in [('settings',{'llm':{'model':'fake'}}),('chat_history',[]),('preset_snapshot',self.preset)]:
            p=patch.object(app,name,return_value=value);p.start();self.addCleanup(p.stop)

    def test_tree_includes_blank_routing_all_forks_cycles_and_metadata(self):
        tree=app.conversation_tree(1);self.assertEqual(len(tree['nodes']),5)
        nodes={n['id']:n for n in tree['nodes']}
        self.assertTrue(nodes['1:0']['structural']);self.assertEqual(nodes['1:0']['text'],'')
        self.assertEqual([l['to'] for l in nodes['1:1']['next']],['1:2','1:3'])
        self.assertEqual(nodes['1:2']['next'][0]['to'],'1:1')
        self.assertTrue(nodes['1:3']['next'][0]['external'])
        self.assertEqual(nodes['1:2']['checks'][0]['skilltype'],'Logic')
        self.assertEqual(nodes['1:2']['conditions'],'A');self.assertEqual(nodes['1:2']['script'],'set A')
        self.assertIn('Alternate-only fact.',nodes['1:4']['alternates'])
        self.assertEqual(app.conversation_list(ids=[1])['conversations'][0]['records'],5)
        self.assertEqual(app.conversation_list('Money')['conversations'][0]['id'],2)

    def test_full_sources_are_read_without_search_and_citations_verified(self):
        requests=[]
        def provider(conf,endpoint,payload):
            requests.append(payload)
            return {'choices':[{'message':{'content':'Fact [1:1, 1:4]. Bad [999:9].'}}]}
        with patch.object(app,'provider',side_effect=provider),patch.object(app,'search') as search:
            result=app.research({'query':'Summarize','depth':'consolidate','conversationIds':[1,2],'promptSnapshot':self.preset})
        search.assert_not_called();self.assertEqual(result['coverage']['records'],6)
        text=requests[0]['messages'][-1]['content']
        for ident in ['1:0','1:1','1:2','1:3','1:4','2:1']:self.assertIn(ident,text)
        self.assertIn('Alternate-only fact.',text);self.assertIn('set A',text)
        self.assertEqual([n['id'] for n in result['evidence']],['1:1','1:4'])
        self.assertTrue(result['citationWarning']);self.assertIn('[unverified source]',result['answer'])
        self.assertNotIn('tools',requests[-1])

    def test_chunks_do_not_lose_long_source_text(self):
        texts=['a'*45,'b'*12,'c'*41]
        chunks=app.text_batches(texts,20)
        self.assertEqual(''.join(chunks).replace('\n',''),''.join(texts))
        self.assertTrue(all(len(c)<=20 for c in chunks))

    def test_large_record_is_split_with_identity_and_notes_are_reduced(self):
        with sqlite3.connect(self.path,factory=app.ManagedConnection) as c:
            c.execute('UPDATE dentries SET dialoguetext=? WHERE conversationid=1 AND id=1',('Long source '*4000,))
        requests=[]
        def provider(conf,endpoint,payload):
            text=payload['messages'][-1]['content'];requests.append(text)
            answer=('Fact [1:1]. '*2500 if 'Records (a long record' in text else 'Fact [1:1].')
            return {'choices':[{'message':{'content':answer}}]}
        with patch.object(app,'provider',side_effect=provider):
            result=app.consolidate({'query':'Summarize','conversationIds':[1]}, {'model':'fake'},self.preset)
        source_requests=[r for r in requests if 'Records (a long record' in r]
        self.assertGreater(len(source_requests),1)
        supplied=''.join(r.split('Records (a long record may continue in the next portion):\n',1)[1] for r in source_requests)
        supplied=re.sub(r'Record \d+:\d+ · portion \d+:\n','',supplied).replace('\n','')
        self.assertEqual(supplied.count('Long source '),4000)
        for portion in range(1,4):self.assertTrue(any(f'Record 1:1 · portion {portion}:' in r for r in source_requests))
        self.assertTrue(any('Combine these sourced notes' in r for r in requests))
        self.assertEqual(result['coverage']['records'],5)
        self.assertEqual(result['evidence'][0]['id'],'1:1')

    def test_retry_keeps_selection_and_new_response_is_non_destructive(self):
        with patch.object(app,'provider',return_value={'choices':[{'message':{'content':'Fact [1:1].'}}]}):
            handler=object.__new__(app.Handler)
            first=handler.persistent_research({'query':'Summarize','depth':'consolidate','conversationIds':[1]})
            second=handler.persistent_research({'query':'Summarize','depth':'consolidate','conversationIds':[2],'chatId':first['chatId'],'retryTurnId':first['turnId']})
        self.assertEqual(second['coverage']['conversations'][0]['id'],1)
        turn=app.get_chat(first['chatId'])['turns'][0]
        self.assertEqual(len(turn['variants']),2);self.assertEqual(turn['request']['conversationIds'],[1])

    def test_missing_selection_fails_before_creating_a_chat(self):
        for ids in ([],[True],list(range(11)),[999]):
            with self.assertRaises(ValueError):app.create_run({'query':'Summarize','depth':'consolidate','conversationIds':ids})
        self.assertEqual(app.chat_list()['chats'],[])

    def test_stop_checks_between_model_requests(self):
        class Control:
            stopped=False
            def check(self):
                if self.stopped:raise app.GenerationStopped()
        control=Control();requests=[]
        def provider(*args):
            requests.append(args);control.stopped=True
            return {'choices':[{'message':{'content':'Fact [1:1].'}}]}
        with patch.object(app,'provider',side_effect=provider):
            with self.assertRaises(app.GenerationStopped):app.consolidate({'query':'Summary','conversationIds':[1]}, {'model':'fake'},self.preset,control=control)
        self.assertEqual(len(requests),1)


if __name__=='__main__':unittest.main()
