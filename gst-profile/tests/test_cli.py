import glob
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr
from gst_profile.cli import main, _parse_duration

HERE = os.path.dirname(__file__)
LOG = os.path.join(HERE, "..", "fixtures", "local-videotestsrc", "trace-run.log.gz")
DOT = os.path.join(HERE, "..", "fixtures", "local-videotestsrc", "pipeline.PAUSED_PLAYING.dot")


class CliTest(unittest.TestCase):
    def test_duration(self):
        self.assertEqual(_parse_duration("30s"), 30.0)
        self.assertEqual(_parse_duration("2m"), 120.0)
        self.assertEqual(_parse_duration("500ms"), 0.5)
        self.assertIsNone(_parse_duration(None))

    def test_analyze_log_to_session(self):
        out = os.path.join(tempfile.mkdtemp(), "s.json")
        code = main(["analyze", LOG, "--dot", DOT, "--out", out])
        self.assertEqual(code, 0)
        with open(out) as fh:
            d = json.load(fh)
        self.assertEqual(d["schema"], "gst-profile/1")
        self.assertEqual(len(d["graph"]["links"]), 4)
        self.assertEqual(d["graph"]["elements"][0]["id"], "videotestsrc0")
        # analyze of a session JSON re-prints without error
        self.assertEqual(main(["analyze", out]), 0)

    def test_check_runs(self):
        self.assertEqual(main(["check"]), 0)

    def test_analyze_tolerates_a_malformed_record(self):
        # a new-element record missing name= must not crash analyze; it's dropped as a parse error.
        path = os.path.join(tempfile.mkdtemp(), "bad.log")
        with open(path, "w") as fh:
            fh.write('0:00:00.1 1 0x1 TRACE GST_TRACER :0:: new-element, thread-id=(guint64)1, ts=(guint64)1, '
                     'ix=(uint)0, parent-ix=(uint)4294967295, type=(string)GstX, is-bin=(boolean)0;\n')
        self.assertEqual(main(["analyze", path]), 0)

    def test_usage_errors_return_3_not_systemexit(self):
        for argv in ([], ["bogus"], ["run"], ["analyze"], ["run", "--nope", "x"]):
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main(argv), 3, argv)

    def test_wrap_requires_a_command(self):
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(["wrap"]), 3)
            self.assertEqual(main(["wrap", "--"]), 3)

    def test_wrap_bad_binary_returns_3_and_cleans_up(self):
        before = set(glob.glob("/tmp/gst-profile-*"))
        with redirect_stderr(io.StringIO()) as err:
            code = main(["wrap", "--", "./definitely-no-such-binary-xyz"])
        self.assertEqual(code, 3)
        self.assertIn("cannot start", err.getvalue())
        after = set(glob.glob("/tmp/gst-profile-*"))
        self.assertEqual(after, before)                  # no leaked workdir

    @unittest.skipUnless(shutil.which("gst-launch-1.0"), "GStreamer not installed")
    def test_wrap_real_app_gets_topology_and_caps_from_the_log(self):
        out = os.path.join(tempfile.mkdtemp(), "wrap.json")
        # gst-launch stands in for "your binary": wrap mode must not depend on dot dumps for topology or caps
        code = main(["wrap", "--duration", "3s", "--out", out, "--",
                     "gst-launch-1.0", "-q", "videotestsrc", "num-buffers=45", "!", "video/x-raw,width=320,height=240,framerate=30/1",
                     "!", "videoconvert", "!", "video/x-raw,format=NV12", "!", "fakesink", "sync=false"])
        self.assertEqual(code, 0)
        with open(out) as fh:
            d = json.load(fh)
        self.assertEqual(d["session"]["mode"], "wrap")
        self.assertEqual(d["session"]["command"][0], "gst-launch-1.0")
        ids = {e["id"] for e in d["graph"]["elements"]}
        self.assertTrue({"videotestsrc0", "videoconvert0", "fakesink0"} <= ids)
        self.assertTrue(all(l["memory"] == "sysmem" for l in d["graph"]["links"]))
        self.assertTrue(any(l["format"] == "NV12" for l in d["graph"]["links"]))     # caps came from GST_EVENT lines

    @unittest.skipUnless(shutil.which("gst-launch-1.0"), "GStreamer not installed")
    def test_run_real_pipeline(self):
        out = os.path.join(tempfile.mkdtemp(), "run.json")
        code = main(["run", "videotestsrc is-live=true ! video/x-raw,width=320,height=240,framerate=30/1 ! videoconvert ! queue ! fakesink sync=false",
                     "--duration", "2s", "--out", out, "--no-ui"])
        self.assertEqual(code, 0)
        with open(out) as fh:
            d = json.load(fh)
        self.assertEqual(d["session"]["mode"], "run")
        ids = [e["id"] for e in d["graph"]["elements"]]
        for want in ("videotestsrc0", "capsfilter0", "videoconvert0", "queue0", "fakesink0"):
            self.assertIn(want, ids)
        self.assertGreaterEqual(len(d["series"]["t"]), 4)
        self.assertTrue(any(l["format"] for l in d["graph"]["links"]))          # caps came from the dot dumps
        self.assertTrue(any(e["kind"] == "child-exit" for e in d["events"]))

    @unittest.skipUnless(shutil.which("gst-launch-1.0"), "GStreamer not installed")
    def test_duration_does_not_hide_a_child_that_died_on_its_own(self):
        out = os.path.join(tempfile.mkdtemp(), "crash.json")
        with redirect_stderr(io.StringIO()):
            code = main(["run", "videotestsrc ! nosuchelementxyz ! fakesink",
                         "--duration", "2s", "--out", out, "--no-ui"])
        self.assertEqual(code, 2)

    @unittest.skipUnless(shutil.which("gst-launch-1.0"), "GStreamer not installed")
    def test_duration_that_stops_a_healthy_child_is_clean(self):
        out = os.path.join(tempfile.mkdtemp(), "healthy.json")
        code = main(["run", "videotestsrc is-live=true ! fakesink sync=false",
                     "--duration", "2s", "--out", out, "--no-ui"])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
