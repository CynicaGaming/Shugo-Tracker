"""
Preview the Electron UI in an ordinary browser: serves desktop/renderer and runs the same Core as the app,
with POST /rpc for requests and GET /events (server-sent events) for pushed updates.

    python -m shugotracker.devserver --demo            # then open http://127.0.0.1:8765
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import queue
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .core import Core

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RENDERER = os.path.join(HERE, "desktop", "renderer")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--root", default=None, help="app folder (data, cache, logs); a temporary one by default")
    a = ap.parse_args(argv)
    clients: list[queue.Queue] = []
    lock = threading.Lock()

    def emit(obj: dict) -> None:
        with lock:
            for q in clients:
                q.put(obj)
    core = Core(a.root or tempfile.mkdtemp(prefix="shugo-dev-"), emit, demo=a.demo,
                log=lambda m: print("core:", m, flush=True))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            if self.path != "/rpc":
                self.send_error(404)
                return
            msg = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            done, box = threading.Event(), {}

            def reply(obj):
                box["r"] = obj
                done.set()
            core.handle(msg, reply)
            done.wait(60)
            body = json.dumps(box.get("r") or {"id": msg.get("id"), "error": "timeout"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/events":
                q: queue.Queue = queue.Queue()
                with lock:
                    clients.append(q)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                try:
                    while True:
                        try:
                            obj = q.get(timeout=15)
                            self.wfile.write(f"data: {json.dumps(obj)}\n\n".encode())
                        except queue.Empty:
                            self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    with lock:
                        clients.remove(q)
                return
            path = self.path.split("?", 1)[0]
            rel = "index.html" if path in ("/", "") else path.lstrip("/")
            full = os.path.normpath(os.path.join(RENDERER, rel))
            if not full.startswith(RENDERER) or not os.path.isfile(full):
                self.send_error(404)
                return
            with open(full, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(full)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print(f"Shugo Tracker preview: http://127.0.0.1:{a.port}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    core.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
