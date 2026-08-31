import json, os, unittest
from gst_profile import analysis

FX = os.path.join(os.path.dirname(__file__), "fixtures")


def load(name):
    with open(os.path.join(FX, name)) as fh:
        return json.load(fh)


class AnalysisTest(unittest.TestCase):
    def test_zc_fixture_aggregates(self):
        a = analysis.build(load("jetson-zc-break.json"))
        self.assertEqual(a.platform, "jetson")
        self.assertTrue(a.caps["tegrastats"])
        # videoconvert0 is the hot element (9 ms p95 vs 2-3 for the rest)
        hot = a.hot_share()
        self.assertEqual(hot[0][0], "videoconvert0")
        self.assertGreater(hot[0][2], 50.0)
        self.assertEqual(a.latency_ms_p95, 20.0)
        self.assertAlmostEqual(a.frame_period_ms, 1000.0 / 30.0, places=1)
        self.assertEqual(a.system_peak["vic_pct"], 86.0)
        self.assertEqual({e.id for e in a.real_elements()}, {"nvarguscamerasrc0", "videoconvert0", "nvvidconv0", "nvv4l2h264enc0", "udpsink0"})

    def test_link_memory_and_graph_helpers(self):
        a = analysis.build(load("jetson-zc-break.json"))
        mems = {l.src_el + "->" + l.sink_el: l.memory for l in a.links}
        self.assertEqual(mems["nvarguscamerasrc0->videoconvert0"], "nvmm")
        self.assertEqual(mems["videoconvert0->nvvidconv0"], "sysmem")
        self.assertEqual(a.downstream("videoconvert0"), ["nvvidconv0"])
        self.assertEqual(a.upstream("nvvidconv0"), ["videoconvert0"])
        self.assertIsNotNone(a.link_between("videoconvert0", "nvvidconv0"))

    def test_sustained_interior_stall(self):
        s = load("jetson-zc-break.json")
        # a link stalled in the interior (windows 1..3) but flowing at the tail -> stall_interior True
        s["series"]["links"]["videoconvert0:src->nvvidconv0:sink"]["stalled"] = [False, True, True, True, False]
        a = analysis.build(s)
        lk = a.link_between("videoconvert0", "nvvidconv0")
        self.assertTrue(lk.stall_interior)
        # a stall only in the final windows (teardown) -> not interior
        s["series"]["links"]["videoconvert0:src->nvvidconv0:sink"]["stalled"] = [False, False, False, True, True]
        a2 = analysis.build(s)
        self.assertFalse(a2.link_between("videoconvert0", "nvvidconv0").stall_interior)

    def test_healthy_software_fixture_builds(self):
        a = analysis.build(load("software-healthy.json"))
        self.assertEqual(a.platform, "generic")
        # pipeline0 is a bin: real_elements() and hot_share() must exclude it
        self.assertIn("pipeline0", a.elements)
        self.assertTrue(a.elements["pipeline0"].is_bin)
        self.assertNotIn("pipeline0", {e.id for e in a.real_elements()})
        self.assertNotIn("pipeline0", {eid for eid, _, _ in a.hot_share()})
        self.assertTrue(a.hot_share())                      # non-empty: real elements have timing
        self.assertIsNotNone(a.frame_period_ms)

    def test_frame_period_falls_back_to_fastest_link_when_source_has_no_fps(self):
        s = load("jetson-zc-break.json")
        # drop fps from the source link so the source-cadence path finds nothing -> fallback to fastest link
        s["series"]["links"]["nvarguscamerasrc0:src->videoconvert0:sink"]["fps"] = [None, None, None, None, None]
        a = analysis.build(s)
        self.assertAlmostEqual(a.frame_period_ms, 1000.0 / 30.0, places=1)   # the other link (30 fps) still gives the period


if __name__ == "__main__":
    unittest.main()
