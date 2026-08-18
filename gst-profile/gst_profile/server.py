"""Live view server: stdlib http.server, Server-Sent Events. Streams the session as it builds.
Frames (SSE `event:` types): graph (full, on topology change), tick (one series row), findings
(full ranked list), status, event. GET / = the panel page; GET /session.json = the snapshot;
POST /control = {"action":"stop"|"mark", ...}. No third-party deps."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable


class Broker:
    """Fan-out of frames to connected SSE clients. The capture thread calls publish(); each client
    holds a bounded queue and a condition. Thread-safe."""
    def __init__(self, maxlen: int = 2000):
        self._clients = []            # list of (list buffer, threading.Condition)
        self._lock = threading.Lock()
        self._history = []            # graph+latest-findings replayed to late joiners
        self._maxlen = maxlen
        self.closed = False

    def subscribe(self):
        buf, cond = [], threading.Condition()
        with self._lock:
            client = (buf, cond)
            self._clients.append(client)
            # replay the sticky frames (graph, latest findings, status) so a late client is current
            with cond:
                buf.extend(self._history)
        return client

    def unsubscribe(self, client):
        with self._lock:
            if client in self._clients:
                self._clients.remove(client)

    def publish(self, event: str, data: dict, sticky: bool = False):
        frame = (event, json.dumps(data))
        with self._lock:
            if sticky:
                self._history = [f for f in self._history if f[0] != event] + [frame]
            clients = list(self._clients)
        for buf, cond in clients:
            with cond:
                buf.append(frame)
                if len(buf) > self._maxlen:
                    del buf[:len(buf) - self._maxlen]
                cond.notify()

    def close(self):
        self.closed = True
        with self._lock:
            clients = list(self._clients)
        for buf, cond in clients:
            with cond:
                cond.notify()


def make_handler(broker: Broker, snapshot: Callable[[], dict], control: Callable[[dict], dict], page: str):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *a):
            pass
        def _send(self, code, ctype, body: bytes, extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)
        def do_GET(self):
            if self.path == "/" or self.path.startswith("/index"):
                self._send(200, "text/html; charset=utf-8", page.encode())
            elif self.path.startswith("/session.json"):
                self._send(200, "application/json", json.dumps(snapshot()).encode())
            elif self.path.startswith("/events"):
                self._stream()
            else:
                self._send(404, "text/plain", b"not found")
        def do_POST(self):
            if not self.path.startswith("/control"):
                self._send(404, "text/plain", b"not found"); return
            n = int(self.headers.get("Content-Length", 0))
            try:
                req = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                self._send(400, "text/plain", b"bad json"); return
            self._send(200, "application/json", json.dumps(control(req)).encode())
        def _stream(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            buf, cond = broker.subscribe()
            try:
                while not broker.closed:
                    with cond:
                        if not buf:
                            cond.wait(timeout=15)
                        pending, buf[:] = list(buf), []
                    if not pending:
                        self.wfile.write(b": keep-alive\n\n")  # comment frame
                        self.wfile.flush()
                        continue
                    for event, data in pending:
                        self.wfile.write(f"event: {event}\ndata: {data}\n\n".encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                broker.unsubscribe((buf, cond))
    return H


class LiveServer:
    def __init__(self, broker, snapshot, control, page, host="0.0.0.0", port=8790):
        self.broker = broker
        self.httpd = ThreadingHTTPServer((host, port), make_handler(broker, snapshot, control, page))
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self._t = None
    def start(self):
        self._t = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._t.start()
    def stop(self):
        self.broker.close()
        self.httpd.shutdown()
        self.httpd.server_close()
