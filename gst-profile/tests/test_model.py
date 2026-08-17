import gzip
import json
import os
import unittest
from gst_profile.model import Session, Target
from gst_profile.procstat import CpuSample

HERE = os.path.dirname(__file__)
LOG = os.path.join(HERE, "..", "fixtures", "local-videotestsrc", "trace-run.log.gz")


class ModelTest(unittest.TestCase):
    def build(self):
        s = Session(mode="analyze", target=Target(gstreamer="1.24.2"))
        with gzip.open(LOG, "rt") as fh:
            for line in fh:
                s.ingest_line(line)
        s.tick(s.agg._win_start + s.agg.window_ns)
        return s

    def test_fixture_builds_full_session(self):
        s = self.build()
        d = s.to_dict()
        self.assertEqual(d["schema"], "gst-profile/1")
        self.assertEqual(sorted(e["id"] for e in d["graph"]["elements"]), ["capsfilter0", "fakesink0", "pipeline0", "queue0", "videoconvert0", "videotestsrc0"])
        self.assertEqual(len(d["graph"]["links"]), 4)
        self.assertTrue(all(l["memory"] == "sysmem" and l["format"] for l in d["graph"]["links"]))   # caps via GST_EVENT lines
        self.assertGreaterEqual(len(d["series"]["t"]), 6)                       # 2 s at 250 ms
        self.assertLessEqual(d["session"]["parse"]["unparsed"], 10)
        self.assertTrue(any(e["kind"] == "state-changed" for e in d["events"]))
        lat = [x for x in d["series"]["pipeline"]["latency_ms_p95"] if x is not None]
        self.assertTrue(lat and max(lat) > 0)

    def test_json_roundtrip(self):
        s = self.build()
        d = s.to_dict()
        s2 = Session.from_dict(json.loads(s.to_json()))
        self.assertEqual(s2.graph.to_dict(), d["graph"])
        self.assertEqual(s2.series_dict()["t"], d["series"]["t"])
        self.assertEqual(s2.mode, "analyze")

    def test_cpu_attributed_to_thread_segment(self):
        s = Session(mode="run")
        for a, b in (("src0:src", "conv0:sink"), ("conv0:src", "queue0:sink"), ("queue0:src", "enc0:sink"), ("enc0:src", "sink0:sink")):
            s.graph.add_link(a, b)
        s.ingest_cpu(CpuSample(proc_pct=50.0, threads={"1:src0:src": 30.0, "2:queue0:src": 20.0}, per_core=[50.0], total_pct=50.0))
        self.assertEqual(s.agg.element_cpu, {"src0": 30.0, "conv0": 30.0, "queue0": 20.0, "enc0": 20.0, "sink0": 20.0})
        self.assertEqual(s.agg.system_sample["cpu_pct_per_core"], [50.0])


if __name__ == "__main__":
    unittest.main()
