from concurrent.futures import ThreadPoolExecutor
import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from server import create_server
from service import DatabaseService


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.service = DatabaseService(":memory:")
        self.server = create_server(self.service, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def query(self, sql):
        request = Request(self.base + "/api/query", data=json.dumps({"sql": sql}).encode(),
                          headers={"Content-Type": "application/json"})
        with urlopen(request) as response:
            return json.load(response)

    def test_api_and_concurrent_writes(self):
        self.query("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(lambda i: self.query(f"INSERT INTO items VALUES ({i}, 'item')"), range(20)))
        self.assertEqual(len(self.query("SELECT * FROM items")["result"]), 20)
        with urlopen(self.base + "/api/schema") as response:
            self.assertEqual(json.load(response)["schema"]["items"]["row_count"], 20)
        with urlopen(self.base) as response:
            self.assertIn(b"Mini SQLite Studio", response.read())

    def test_invalid_sql_and_requests(self):
        with self.assertRaises(HTTPError) as error:
            self.query("SELECT * FROM missing")
        self.assertEqual(error.exception.code, 400)
        error.exception.close()
        request = Request(self.base + "/api/query", data=b'{}', headers={
            "Content-Type": "application/json", "Origin": "https://example.com"})
        with self.assertRaises(HTTPError) as error:
            urlopen(request)
        self.assertEqual(error.exception.code, 403)
        error.exception.close()


if __name__ == "__main__":
    unittest.main()
