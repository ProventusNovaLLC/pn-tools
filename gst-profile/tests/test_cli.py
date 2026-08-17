import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
