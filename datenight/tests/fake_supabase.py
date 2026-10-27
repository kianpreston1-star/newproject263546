"""A stand-in for a Supabase project with sync/supabase.sql installed, for tests. Same four functions,
same rules, kept in memory. Run it directly to try the apps against it: python3 tests/fake_supabase.py"""
import itertools
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

KEY = "sb_publishable_test"
CODE = re.compile(r"^[A-Za-z0-9_-]{24,64}$")


class FakeSupabase:
    def __init__(self, port=0):
        self.docs, self.photos, self.lock, self.clock = {}, {}, threading.Lock(), itertools.count(1)
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status, body=None):
                data = b"" if body is None else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_OPTIONS(self):
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "apikey, authorization, content-type")
                self.send_header("Access-Control-Allow-Methods", "POST")
                self.end_headers()

            def do_POST(self):
                if self.headers.get("apikey") != KEY:
                    return self._send(401, {"message": "Invalid API key"})
                m = re.fullmatch(r"/rest/v1/rpc/(\w+)", self.path)
                handler = getattr(fake, m.group(1), None) if m and m.group(1).startswith("dn_") else None
                if not handler:
                    return self._send(404, {"message": "not found"})
                args = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                if not CODE.match(args.get("p_code") or ""):
                    return self._send(400, {"message": "bad sync code"})
                with fake.lock:
                    self._send(200, handler(**args))

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def start(self):
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def dn_pull(self, p_code):
        doc, version = self.docs.get(p_code, ({}, None))
        return {"doc": doc, "version": version, "photos": sorted(self.photos.get(p_code, {}))}

    def dn_push(self, p_code, p_doc, p_expected):
        current = self.docs.get(p_code)
        if (p_expected is None and current) or (p_expected is not None and (not current or current[1] != p_expected)):
            return False
        self.docs[p_code] = (p_doc, f"v{next(self.clock)}")
        return True

    def dn_photo_put(self, p_code, p_name, p_data):
        self.photos.setdefault(p_code, {}).setdefault(p_name, p_data)

    def dn_photo_get(self, p_code, p_names):
        mine = self.photos.get(p_code, {})
        return {n: mine[n] for n in p_names[:10] if n in mine}


if __name__ == "__main__":
    fake = FakeSupabase(54321)
    print(f"Fake Supabase on {fake.url}, key {KEY}")
    fake.server.serve_forever()
