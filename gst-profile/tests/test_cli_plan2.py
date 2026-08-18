import io, json, os, socket, threading, time, unittest, shutil, tempfile
from contextlib import redirect_stdout, redirect_stderr
from gst_profile import cli, rules

FX = os.path.join(os.path.dirname(__file__), "fixtures")
HAS_GST = shutil.which("gst-launch-1.0") is not None


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class AnalyzeVerdictTest(unittest.TestCase):
    def setUp(self):
        rules.VERIFIED_RULES.clear()

    def test_analyze_prints_verdict_and_exits_clean_when_all_info(self):
        code, out, _ = run_cli(["analyze", os.path.join(FX, "jetson-zc-break.json")])
        self.assertEqual(code, 0)                       # nothing verified -> all info -> exit 0
        self.assertIn("gst-profile verdict", out)
        self.assertIn("ZC", out)
        self.assertIn("Zero-copy broken", out)

    def test_exit_1_when_a_verified_rule_fires(self):
        rules.VERIFIED_RULES.update({"ZC": ["orin-nx-r36.4"]})
        try:
            code, out, _ = run_cli(["analyze", os.path.join(FX, "jetson-zc-break.json")])
        finally:
            rules.VERIFIED_RULES.clear()
        self.assertEqual(code, 1)                       # a high/medium finding -> EXIT_FINDINGS

    def test_report_is_self_contained_html(self):
        out_html = os.path.join(tempfile.mkdtemp(), "r.html")
        code, _, _ = run_cli(["report", os.path.join(FX, "jetson-zc-break.json"), "-o", out_html])
        self.assertEqual(code, 0)
        with open(out_html, encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn("__VERDICT__", html)
        self.assertIn("Zero-copy broken", html)
        self.assertNotIn("http://", html.split("scoping")[0] if "scoping" in html else html)  # no external hosts in the doc head/body


@unittest.skipUnless(HAS_GST, "GStreamer not installed")
class LiveRunTest(unittest.TestCase):
    PIPE = ("videotestsrc is-live=true ! video/x-raw,width=320,height=240,framerate=30/1 "
            "! videoconvert ! queue ! fakesink sync=false")

    def test_headless_run_prints_verdict_exit_0(self):
        out_json = os.path.join(tempfile.mkdtemp(), "s.json")
        code, out, _ = run_cli(["run", self.PIPE, "--duration", "2s", "--no-ui", "--out", out_json])
        self.assertEqual(code, 0)
        self.assertIn("gst-profile verdict", out)
        self.assertTrue(os.path.exists(out_json))

    def test_live_run_streams_ticks_then_exits(self):
        # capture runs on THIS (main) thread; a background reader connects and collects the live stream.
        port = 8793
        out_json = os.path.join(tempfile.mkdtemp(), "s.json")
        frames = []
        def reader():
            time.sleep(0.6)                              # let the server come up mid-capture
            try:
                s = socket.create_connection(("127.0.0.1", port), timeout=5)
                s.sendall(b"GET /events HTTP/1.1\r\nHost: x\r\n\r\n")
                s.settimeout(0.3); buf = b""; deadline = time.time() + 2.2
                while time.time() < deadline:
                    try:
                        c = s.recv(4096)
                    except socket.timeout:
                        continue
                    if not c:
                        break
                    buf += c
                s.close()
                frames.extend(b.split(b"event: ")[1].split(b"\n")[0].decode() for b in buf.split(b"\n\n") if b"event: " in b)
            except OSError:
                pass
        t = threading.Thread(target=reader); t.start()
        run_cli(["run", self.PIPE, "--duration", "3s", "--hold", "0", "--port", str(port),
                 "--host", "127.0.0.1", "--out", out_json])
        t.join()
        self.assertIn("tick", frames)                    # live ticks streamed to the browser
        self.assertIn("findings", frames)


if __name__ == "__main__":
    unittest.main()
