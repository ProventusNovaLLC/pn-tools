import json, socket, threading, time, unittest
import http.client
from gst_profile import server as srv


def read_stream(port, seconds=2.0):
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.sendall(b"GET /events HTTP/1.1\r\nHost: x\r\n\r\n")
    s.settimeout(0.3)
    buf, deadline = b"", time.time() + seconds
    while time.time() < deadline:
        try:
            c = s.recv(4096)
        except socket.timeout:
            continue
        if not c:
            break
        buf += c
    s.close()
    frames = []
    for block in buf.split(b"\n\n"):
        if b"event:" in block:
            ev = block.split(b"event: ")[1].split(b"\n")[0].decode()
            data = block.split(b"data: ")[1].decode() if b"data: " in block else ""
            frames.append((ev, data))
    return frames


class ServerTest(unittest.TestCase):
    def make(self, snap=None, control=None):
        b = srv.Broker()
        server = srv.LiveServer(b, lambda: (snap or {"schema": "gst-profile/1"}),
                                (control or (lambda req: {"ok": True, "echo": req.get("action")})),
                                "<html>panel</html>", host="127.0.0.1", port=0)
        server.start()
        self.addCleanup(server.stop)
        return b, server

    def test_late_joiner_gets_sticky_graph_and_live_ticks(self):
        b, server = self.make()
        b.publish("graph", {"elements": ["a", "b"]}, sticky=True)   # before any client connects
        frames = []
        def reader():
            frames.extend(read_stream(server.port, seconds=2.0))
        t = threading.Thread(target=reader); t.start()
        time.sleep(0.4)
        b.publish("tick", {"t": 0.0})
        b.publish("findings", [{"rule": "ZC"}], sticky=True)
        b.publish("tick", {"t": 0.25})
        t.join()
        evs = [e for e, _ in frames]
        self.assertIn("graph", evs)                 # sticky replayed to the late joiner
        self.assertEqual(evs.count("tick"), 2)
        self.assertIn("findings", evs)

    def test_static_routes_and_control(self):
        posted = {}
        def control(req):
            posted.update(req); return {"ok": True}
        b, server = self.make(snap={"schema": "gst-profile/1", "n": 1}, control=control)
        c = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
        c.request("GET", "/"); r = c.getresponse(); self.assertEqual(r.status, 200); self.assertIn(b"panel", r.read())
        c.request("GET", "/session.json"); r = c.getresponse(); self.assertEqual(json.loads(r.read())["n"], 1)
        c.request("GET", "/nope"); r = c.getresponse(); self.assertEqual(r.status, 404); r.read()
        body = json.dumps({"action": "stop"}).encode()
        c.request("POST", "/control", body=body, headers={"Content-Length": str(len(body))})
        r = c.getresponse(); self.assertTrue(json.loads(r.read())["ok"])
        self.assertEqual(posted.get("action"), "stop")
        # a malformed Content-Length must yield a clean 400, not a stderr traceback
        c.request("POST", "/control", body=b"{}", headers={"Content-Length": "abc"})
        r = c.getresponse(); self.assertEqual(r.status, 400); r.read()
        c.close()

    def test_sticky_replacement_keeps_only_the_latest(self):
        b, server = self.make()
        b.publish("findings", [{"n": 1}], sticky=True)
        b.publish("findings", [{"n": 2}], sticky=True)   # same event type twice -> only the latest replays
        frames = read_stream(server.port, seconds=1.0)
        findings = [d for e, d in frames if e == "findings"]
        self.assertEqual(findings, ['[{"n": 2}]'])


if __name__ == "__main__":
    unittest.main()
