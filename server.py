"""Local HTTP database API and browser interface."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlsplit

from mini_sqlite import DatabaseError
from service import DatabaseService

MAX_BODY = 64 * 1024


def create_server(service, host="127.0.0.1", port=8000):
    class Handler(BaseHTTPRequestHandler):
        def send(self, status, body, kind="application/json"):
            payload = json.dumps(body).encode() if kind == "application/json" else body
            self.send_response(status)
            self.send_header("Content-Type", kind + "; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/":
                self.send(200, Path(__file__).with_name("web.html").read_bytes(), "text/html")
            elif path == "/api/schema":
                self.send(200, {"schema": service.schema()})
            else:
                self.send(404, {"error": "Route not found"})

        def do_POST(self):
            if urlsplit(self.path).path != "/api/query":
                self.send(404, {"error": "Route not found"})
                return
            # Reject cross-origin browser requests to this local database.
            origin = self.headers.get("Origin")
            if origin and origin != "http://" + self.headers.get("Host", ""):
                self.send(403, {"error": "Cross-origin requests are not allowed"})
                return
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                self.send(415, {"error": "Use Content-Type: application/json"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_BODY:
                    self.send(413, {"error": "Request must contain 1–65536 bytes"})
                    return
                self.connection.settimeout(10)
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise DatabaseError("JSON body must be an object")
                result = service.execute(data.get("sql"))
            except (DatabaseError, ValueError, UnicodeDecodeError) as exc:
                self.send(400, {"error": str(exc)})
                return
            except OSError:
                self.send(500, {"error": "Database I/O failed"})
                return
            self.send(200, result)

    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", nargs="?", default="mini.db")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    try:
        server = create_server(DatabaseService(args.database), args.host, args.port)
    except (OSError, DatabaseError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    print(f"Database: {args.database}\nOpen http://{args.host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
