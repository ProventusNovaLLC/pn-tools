import unittest
from gst_profile.preflight import check, render, parse_l4t


def fake_runner(version):
    def run(cmd):
        if cmd[-1] == "--version":
            return f"gst-launch-1.0 version {version}\nGStreamer {version}\n"
        if cmd[-1] == "coretracers":
            return "  latency (GstTracerFactory)\n  stats (GstTracerFactory)\n  rusage (GstTracerFactory)\n"
        return ""
    return run


class PreflightTest(unittest.TestCase):
    def test_modern_gstreamer(self):
        c = check(run=fake_runner("1.20.3"), which=lambda name: "/usr/bin/" + name if name != "tegrastats" else None)
        self.assertEqual(c.gstreamer, "1.20.3")
        self.assertTrue(c.element_latency)
        self.assertEqual(c.tracers, ["latency", "stats", "rusage"])
        self.assertIn("tegrastats", c.sources_missing())
        t = c.to_target()
        self.assertTrue(t.capabilities["element_latency"])
        self.assertIn("gstreamer         1.20.3", render(c))

    def test_old_gstreamer_degrades(self):
        c = check(run=fake_runner("1.16.3"), which=lambda name: "/usr/bin/" + name)
        self.assertFalse(c.element_latency)
        self.assertTrue(any("1.18" in p for p in c.problems))
        self.assertIn("element-latency", c.sources_missing())
        self.assertTrue(c.tegrastats)

    def test_missing_gst_launch(self):
        c = check(run=lambda cmd: None, which=lambda name: None)
        self.assertIsNone(c.gst_launch)
        self.assertTrue(any("gst-launch-1.0 not found" in p for p in c.problems))

    def test_l4t_regex_crosses_the_comma(self):
        # "R(\d+)[^,]*REVISION:" used to fail here because [^,]* can't cross the comma before REVISION:
        self.assertEqual(parse_l4t("# R35 (release), REVISION: 4.1, GCID: 12345678, BOARD: t186ref\n"), "35.4.1")
        self.assertEqual(parse_l4t(""), "")
        self.assertEqual(parse_l4t("not an l4t release string"), "")


if __name__ == "__main__":
    unittest.main()
