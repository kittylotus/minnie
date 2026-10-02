import array
import uuid
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch
import app

class IndexProgressTests(unittest.TestCase):
    def setUp(self):
        self.path=app.DATA/('index-test-'+uuid.uuid4().hex+'.sqlite')
        self.addCleanup(lambda:self.path.unlink(missing_ok=True))
        self.config={'baseUrl':'http://fixture.invalid/v1','model':'embedding-test'}
        self.previous=dict(app.STATUS)
        self.patcher=patch.object(app,'INDEX',self.path);self.patcher.start();self.addCleanup(self.patcher.stop)
        with app.db() as c:
            c.executescript('CREATE TABLE manifest(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE vectors(id TEXT PRIMARY KEY,model TEXT,vector BLOB); CREATE TABLE nodes(id TEXT PRIMARY KEY,conversation,line,speaker,skill,text,title,conditions,alternates);')
            c.execute('INSERT INTO manifest VALUES(?,?)',('sourceHash','fixture'))
        app.STATUS.update(running=False,done=0,total=0,error=None)
    def tearDown(self):
        app.STATUS.clear();app.STATUS.update(self.previous)
        self.patcher.stop()
    def corpus(self,count):
        with app.db() as c:
            c.executemany('INSERT INTO nodes VALUES(?,?,?,?,?,?,?,?,?)',[(f'1:{i}',1,i,'You','',f'Spoken line {i}','Fixture','','[]') for i in range(count)])
            c.executemany('INSERT INTO nodes VALUES(?,?,?,?,?,?,?,?,?)',[('1:999',1,999,'HUB','','0','Fixture','','[]'),('1:998',1,998,'Mainframe','','123456','Fixture','','[]')])
    def test_legacy_total_is_not_the_completion_target(self):
        self.corpus(2)
        with app.db() as c:
            c.executemany('INSERT INTO vectors VALUES(?,?,?)',[(i,app.embedding_key(self.config),array.array('f',[1,0]).tobytes()) for i in ['1:0','1:1','1:998','1:999']])
        state=app.index_inventory(self.config)
        self.assertEqual((state['stored'],state['ready'],state['eligible'],state['remaining'],state['excludedStored']),(4,2,2,0,2))
        self.assertTrue(state['complete'])
        with patch.object(app,'embed') as embed, self.assertLogs(app.LOG,level='INFO') as logs:
            response=app.start_index(self.config)
        self.assertTrue(response['alreadyComplete']);embed.assert_not_called()
        self.assertIn('already complete',logs.output[0])
    def test_partial_failure_is_persisted_and_resumes_only_missing_lines(self):
        self.corpus(35)
        with patch.object(app,'context',return_value={'nodes':[]}),patch.object(app,'embed',side_effect=[[[1,0]]*32,ValueError('Provider returned HTTP 429.')]),self.assertLogs(app.LOG,level='INFO'):
            app.index_vectors(self.config)
        state=app.index_inventory(self.config)
        self.assertEqual((state['ready'],state['remaining']),(32,3))
        self.assertFalse(state['complete']);self.assertIn('429',state['lastError'])
        app.STATUS.update(error=None,running=False)
        self.assertIn('429',app.index_inventory(self.config)['lastError'])
        with patch.object(app,'context',return_value={'nodes':[]}),patch.object(app,'embed',return_value=[[1,0]]*3) as embed,self.assertLogs(app.LOG,level='INFO') as logs:
            app.index_vectors(self.config)
        self.assertEqual(len(embed.call_args.args[0]),3)
        state=app.index_inventory(self.config)
        self.assertTrue(state['complete']);self.assertIsNone(state['lastError'])
        self.assertEqual(state['stored'],35)
        self.assertTrue(any('Semantic index complete' in line for line in logs.output))
    def test_inventory_is_specific_to_provider_and_model(self):
        self.corpus(1)
        with app.db() as c:c.execute('INSERT INTO vectors VALUES(?,?,?)',('1:0',app.embedding_key(self.config),array.array('f',[1,0]).tobytes()))
        other={**self.config,'model':'other-model'}
        state=app.index_inventory(other)
        self.assertEqual((state['ready'],state['remaining']),(0,1))
        self.assertFalse(state['complete'])
    def test_provider_errors_report_http_code_without_secrets(self):
        error=urllib.error.HTTPError('https://secret-url.invalid?key=secret-key',429,'secret-provider-body',None,None)
        text=app.provider_error(error)
        self.assertIn('429',text);self.assertIn('rate-limited',text);self.assertNotIn('secret',text)
        self.assertIn('timed out',app.provider_error(TimeoutError()))

if __name__=='__main__':unittest.main()
