import json
import os
import unittest

from gst_profile import analysis, rules, verdict
from gst_profile.cli import _tick_payload

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def load(name):
    with open(os.path.join(FIXTURES, name)) as fh:
        return json.load(fh)


class TickPayload(unittest.TestCase):
    def test_tick_carries_the_newest_value_of_every_column(self):
        d = load("jetson-zc-break.json")
        p = _tick_payload(d)
        s = d["series"]
        self.assertEqual(p["t"], s["t"][-1])
        self.assertEqual(p["rows"], len(s["t"]))
        self.assertEqual(p["latency_ms_p95"], s["pipeline"]["latency_ms_p95"][-1])
        el = next(iter(s["elements"]))
        self.assertEqual(p["row"]["elements"][el]["proc_ms_p95"], s["elements"][el]["proc_ms_p95"][-1])
        lid = next(iter(s["links"]))
        self.assertEqual(p["row"]["links"][lid]["fps"], s["links"][lid]["fps"][-1])
        self.assertEqual(p["row"]["system"]["vic_pct"], s["system"]["vic_pct"][-1])

    def test_empty_columns_become_null_not_a_crash(self):
        d = load("jetson-zc-break.json")
        d["series"]["system"]["nvdec_pct"] = []
        self.assertIsNone(_tick_payload(d)["row"]["system"]["nvdec_pct"])


class VerdictScope(unittest.TestCase):
    def test_verdict_dict_carries_the_scoping_url(self):
        d = load("jetson-zc-break.json")
        a = analysis.build(d)
        fs = rules.run_rules(a)
        self.assertEqual(verdict.to_dict(a, fs)["scope"], rules.SCOPE)


if __name__ == "__main__":
    unittest.main()
