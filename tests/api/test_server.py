"""網頁伺服器的本機限制、前端提供與建置缺失提示。"""
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from api.app import create_app

LOCAL = ('127.0.0.1', 50000)


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.static = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def client(self, address=LOCAL):
        return TestClient(create_app(self.static, lock_path=self.static / '.lock', scan_on_start=False), client=address)

    def build_frontend(self):
        (self.static / 'index.html').write_text('<app-root></app-root>', encoding='utf-8')
        (self.static / 'main.js').write_text('console.log(1)', encoding='utf-8')

    def test_health_from_loopback(self):
        for address in (LOCAL, ('::1', 50000)):
            response = self.client(address).get('/api/health')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {'status': 'ok'})

    def test_rejects_non_loopback_clients(self):
        self.build_frontend()
        client = self.client(('192.168.1.20', 50000))
        for path in ('/api/health', '/', '/records'):
            self.assertEqual(client.get(path).status_code, 403)

    def test_missing_build_shows_instructions(self):
        response = self.client().get('/')
        self.assertEqual(response.status_code, 503)
        self.assertIn('npm run build', response.text)

    def test_serves_built_files_and_routes_to_index(self):
        self.build_frontend()
        client = self.client()
        self.assertEqual(client.get('/main.js').text, 'console.log(1)')
        for path in ('/', '/records', '/learning/research/abc'):
            response = client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn('<app-root>', response.text)

    def test_unknown_api_is_not_routed_to_frontend(self):
        self.build_frontend()
        self.assertEqual(self.client().get('/api/missing').status_code, 404)

    def test_paths_outside_build_are_not_served(self):
        self.build_frontend()
        secret = self.static.parent / 'secret.txt'
        secret.write_text('secret', encoding='utf-8')
        try:
            response = self.client().get('/..%2Fsecret.txt')
            self.assertNotIn('secret', response.text)
        finally:
            secret.unlink()


if __name__ == '__main__':
    unittest.main()
