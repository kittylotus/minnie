import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import app

class ModelDiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.requests=[]
        class Provider(BaseHTTPRequestHandler):
            def do_GET(self):
                cls.requests.append((self.path,self.headers.get('Authorization')))
                model='text-model' if self.path.startswith('/text/') else 'embedding-model'
                body=json.dumps({'data':[{'id':model},{'id':model},{'id':'another-model'},{'missing':'id'}]}).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def log_message(self,*args):pass
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Provider)
        cls.url=f'http://127.0.0.1:{cls.server.server_port}'
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()

    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.thread.join()

    def config(self):
        return {'llm':{'baseUrl':self.url+'/text/v1','apiKey':'saved-text-key'},'embedding':{'baseUrl':self.url+'/embed/v1','apiKey':'saved-embedding-key'}}

    def test_separate_get_endpoints_and_saved_keys_without_selected_model(self):
        with patch.object(app,'settings',side_effect=self.config):
            text=app.list_models('llm',self.url+'/text/v1/','')
            embeddings=app.list_models('embedding')
        self.assertEqual(text['models'],['another-model','text-model'])
        self.assertEqual(embeddings['models'],['another-model','embedding-model'])
        self.assertEqual(self.requests[-2:], [('/text/v1/models','Bearer saved-text-key'),('/embed/v1/models','Bearer saved-embedding-key')])

    def test_unsaved_key_and_url_do_not_save_settings(self):
        with patch.object(app,'settings',side_effect=self.config):
            app.list_models('llm',self.url+'/new/v1','new-key')
        self.assertEqual(self.requests[-1],('/new/v1/models','Bearer new-key'))

    def test_changed_endpoint_does_not_receive_saved_key(self):
        with patch.object(app,'settings',side_effect=self.config):app.list_models('llm',self.url+'/new/v1','')
        self.assertEqual(self.requests[-1],('/new/v1/models',None))

    def test_invalid_and_empty_response(self):
        with patch.object(app,'provider',return_value={'data':[]}):self.assertEqual(app.list_models('llm')['models'],[])
        with patch.object(app,'provider',return_value={'models':[]}):
            with self.assertRaisesRegex(ValueError,'invalid model list'):app.list_models('embedding')

    def test_invalid_provider_kind(self):
        with self.assertRaises(ValueError):app.list_models('unknown')
