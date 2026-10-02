import http.client
import json
import threading
import unittest
import uuid
from unittest.mock import patch
import app


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.path=app.DATA/('access-test-'+uuid.uuid4().hex+'.json')
        self.addCleanup(lambda:self.path.unlink(missing_ok=True))
        self.addCleanup(lambda:self.path.with_suffix('.tmp').unlink(missing_ok=True))
        patcher=patch.object(app,'ACCESS',self.path);patcher.start();self.addCleanup(patcher.stop)

    def test_generated_code_and_session_survive_restarts(self):
        first=app.load_access()
        self.assertEqual(app.load_access(),first)
        self.assertEqual(app.login_access(first['generatedCode']),first['sessionToken'])
        self.assertEqual(len(first['generatedCode']),14)
        self.assertNotEqual(first['generatedCode'],first['sessionToken'])

    def test_custom_password_is_hashed_and_rotates_sessions(self):
        original=app.load_access()
        token=app.change_access_password('A custom password ☕','A custom password ☕')
        state=app.load_access()
        self.assertTrue(state['passwordSet']);self.assertNotIn('generatedCode',state)
        self.assertNotIn('A custom password',self.path.read_text(encoding='utf-8'))
        self.assertNotEqual(token,original['sessionToken'])
        self.assertEqual(app.login_access('A custom password ☕'),token)
        with self.assertRaises(ValueError):app.login_access(original['generatedCode'])
        handler=object.__new__(app.Handler);handler.client_address=('192.0.2.1',1000)
        handler.headers={'Cookie':'minnie='+token}
        self.assertTrue(handler.authorized())
        handler.headers={'Cookie':'minnie='+original['sessionToken']}
        self.assertFalse(handler.authorized())

    def test_invalid_changes_do_not_modify_existing_access(self):
        original=app.load_access()
        for password,confirmation in [('short','short'),('long enough','mismatch'),(None,None),('x'*129,'x'*129)]:
            with self.subTest(password=password),self.assertRaises(ValueError):app.change_access_password(password,confirmation)
        self.assertEqual(app.load_access(),original)

    def test_phone_login_cookie_and_password_change_http_contract(self):
        class PhoneHandler(app.Handler):
            def setup(self):
                super().setup();self.client_address=('192.0.2.10',self.client_address[1])
        server=app.ThreadingHTTPServer(('127.0.0.1',0),PhoneHandler);server.daemon_threads=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        client=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
        host=f'127.0.0.1:{server.server_port}'
        def post(path,payload,cookie=None):
            headers={'Content-Type':'application/json','Origin':'https://'+host}
            if cookie:headers['Cookie']=cookie
            client.request('POST',path,json.dumps(payload),headers)
            response=client.getresponse();return response.status,json.loads(response.read()),response.getheader('Set-Cookie')
        try:
            code=app.load_access()['generatedCode']
            status,_,_=post('/api/access/password',{'password':'new phone password','confirmation':'new phone password'})
            self.assertEqual(status,401)
            status,_,_=post('/api/login',{'password':'wrong'})
            self.assertEqual(status,401)
            status,body,cookie=post('/api/login',{'password':code})
            self.assertEqual(status,200);self.assertTrue(body['connected'])
            for flag in ('Max-Age=15552000','HttpOnly','SameSite=Strict','Path=/','Secure'):self.assertIn(flag,cookie)
            old_cookie=cookie.split(';')[0]
            status,body,new_cookie=post('/api/access/password',{'password':'new phone password','confirmation':'new phone password'},old_cookie)
            self.assertEqual(status,200);self.assertTrue(body['saved'])
            self.assertNotEqual(old_cookie,new_cookie.split(';')[0])
            status,_,_=post('/api/access/password',{'password':'another password','confirmation':'another password'},old_cookie)
            self.assertEqual(status,401)
            client.request('GET','/api/settings',headers={'Cookie':new_cookie.split(';')[0]})
            response=client.getresponse();settings=json.loads(response.read())
            self.assertEqual(response.status,200);self.assertEqual(settings['access'],{'passwordSet':True})
            self.assertNotIn('passwordHash',json.dumps(settings));self.assertNotIn('sessionToken',json.dumps(settings))
            status,_,_=post('/api/login',{'password':'new phone password'})
            self.assertEqual(status,200)
        finally:
            client.close();server.shutdown();server.server_close();thread.join(3)


if __name__=='__main__':unittest.main()
