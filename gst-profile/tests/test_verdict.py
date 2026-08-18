import json, os, unittest
from gst_profile import analysis, rules, verdict

FX = os.path.join(os.path.dirname(__file__), "fixtures")


def load(name):
    with open(os.path.join(FX, name)) as fh:
        return json.load(fh)


class VerdictTest(unittest.TestCase):
    def setUp(self):
        rules.VERIFIED_RULES.clear()

    def test_header_has_latency_and_hot(self):
        a = analysis.build(load("jetson-zc-break.json"))
        h = verdict.header(a)
        self.assertIn("latency p95 20.0 ms", h)
        self.assertIn("frame period", h)
        self.assertIn("videoconvert0", h)

    def test_text_render_lists_findings_and_scope_link(self):
        a = analysis.build(load("jetson-zc-break.json"))
        fs = rules.run_rules(a)
        txt = verdict.render_text(a, fs)
        self.assertIn("gst-profile verdict", txt)
        self.assertIn("ZC", txt)
        self.assertIn("fix:", txt)
        self.assertIn("utm_source=lead-magnet", txt)          # scoping CTA present
        self.assertIn("heuristic", txt)                       # info diagnostics are labelled

    def test_to_dict_shape_and_exit_flag(self):
        a = analysis.build(load("jetson-zc-break.json"))
        d = verdict.to_dict(a, rules.run_rules(a))
        self.assertIn("header", d)
        self.assertIn("hot", d)
        self.assertTrue(all("severity" in f and "fix_patch" in f for f in d["findings"]))
        self.assertFalse(d["has_high_or_medium"])             # nothing verified yet
        rules.VERIFIED_RULES.update({"ZC": ["hw"]})
        self.assertTrue(verdict.to_dict(a, rules.run_rules(a))["has_high_or_medium"])

    def test_healthy_verdict_is_clean(self):
        a = analysis.build(load("software-healthy.json"))
        txt = verdict.render_text(a, rules.run_rules(a))
        self.assertIn("within frame budget", txt)


if __name__ == "__main__":
    unittest.main()
