import re
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
import app


class RestyleAssetsTests(unittest.TestCase):
    def test_bundled_fonts_load_through_the_app_server(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            origin=f'http://127.0.0.1:{server.server_port}'
            with urllib.request.urlopen(origin+'/style.css') as response:
                stylesheet=response.read().decode('utf-8')
            fonts=re.findall(r"url\('(/fonts/[^']+)'\)",stylesheet)
            self.assertEqual(len(fonts),2)
            for url in fonts:
                with self.subTest(url=url),urllib.request.urlopen(origin+url) as response:
                    self.assertEqual(response.headers.get_content_type(),'font/woff2')
                    self.assertEqual(response.read(),(app.ROOT/'web'/url.lstrip('/')).read_bytes())
        finally:
            server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
