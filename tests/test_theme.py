import json
import threading
import unittest
import urllib.request
import uuid
from unittest.mock import patch
from http.server import ThreadingHTTPServer
import app


class ThemeTests(unittest.TestCase):
    def setUp(self):
        css=app.DATA/('theme-test-'+uuid.uuid4().hex+'.css')
        state=css.with_suffix('.json')
        for path in (css,state,css.with_suffix('.tmp')):
            self.addCleanup(lambda p=path:p.unlink(missing_ok=True))
        for name,path in (('CUSTOM_CSS',css),('THEME',state)):
            patcher=patch.object(app,name,path);patcher.start();self.addCleanup(patcher.stop)

    def test_save_disable_and_reenable_preserve_exact_css(self):
        css='/* fonts */\nbody { font-family: "Palatino", serif; }\n'
        self.assertEqual(app.load_theme(),{'css':'','enabled':True})
        app.save_theme({'css':css,'enabled':True})
        self.assertEqual(app.CUSTOM_CSS.read_text(encoding='utf-8'),css)
        app.save_theme({'css':css,'enabled':False})
        self.assertEqual(app.load_theme(),{'css':css,'enabled':False})
        app.save_theme({'css':css,'enabled':True})
        self.assertTrue(app.load_theme()['enabled'])

    def test_invalid_payload_does_not_change_saved_theme(self):
        app.save_theme({'css':'body {}','enabled':True})
        for payload in ({'css':None},{'css':'x'*60001},{'css':'x','enabled':'false'}):
            with self.assertRaises(ValueError):app.save_theme(payload)
        self.assertEqual(app.load_theme(),{'css':'body {}','enabled':True})

    def test_stylesheet_is_served_as_css_and_disabled_is_empty(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        url=f'http://127.0.0.1:{server.server_port}/custom.css'
        css='/* </style><script>never HTML</script> */\nbody {}'
        app.save_theme({'css':css,'enabled':True})
        with urllib.request.urlopen(url) as response:
            self.assertEqual(response.headers.get_content_type(),'text/css')
            self.assertEqual(response.read().decode(),css)
        app.save_theme({'css':css,'enabled':False})
        with urllib.request.urlopen(url) as response:self.assertEqual(response.read(),b'')
        self.assertEqual(app.load_theme()['css'],css)


if __name__=='__main__':unittest.main()
