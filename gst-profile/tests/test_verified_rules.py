"""Bench-verification promotion: the rules verified on hardware (bench/) must emit at
their target severity with a verified_on tag, the healthy twin must stay clean, and the
gate must still demote any unverified rule to info+heuristic."""
import json
import os
import unittest

from gst_profile import analysis, rules

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
CONFIG = "orin-nx-jp6-r36.4"


def findings(name):
    with open(os.path.join(FIXTURES, name)) as fh:
        d = json.load(fh)
    return rules.run_rules(analysis.build(d))


class PromotedRules(unittest.TestCase):
    # (rule, bad fixture, target severity)
    CASES = [
        ("ZC", "orin-nx-jp6-zc-break.json", "high"),
        ("SW", "orin-nx-jp6-sw.json", "medium"),
        ("QUEUE", "orin-nx-jp6-no-queue.json", "medium"),
    ]

    def test_bad_pipeline_emits_the_verified_finding(self):
        for rule, fixture, sev in self.CASES:
            with self.subTest(rule=rule):
                hits = [f for f in findings(fixture) if f.rule == rule]
                self.assertTrue(hits, f"{rule} did not fire on {fixture}")
                f = hits[0]
                self.assertEqual(f.severity, sev)
                self.assertFalse(f.heuristic, f"{rule} still heuristic after verification")
                self.assertEqual(f.verified_on, [CONFIG])

    def test_bad_pipeline_trips_exit_code(self):
        # a verified high/medium finding is what makes the CLI exit non-zero
        for rule, fixture, _ in self.CASES:
            with self.subTest(rule=rule):
                fs = findings(fixture)
                self.assertTrue(any(f.severity in ("high", "medium") for f in fs))

    def test_healthy_twin_is_clean(self):
        fs = findings("orin-nx-jp6-healthy.json")
        promoted = [f for f in fs if f.rule in ("ZC", "SW", "QUEUE")]
        self.assertEqual(promoted, [], f"healthy fixture tripped {[f.rule for f in promoted]}")
        self.assertFalse(any(f.severity in ("high", "medium") for f in fs))


class GateStillDemotes(unittest.TestCase):
    def test_unverified_rule_stays_info_heuristic(self):
        # SYNC is deliberately NOT in VERIFIED_RULES; the gate must keep any SYNC finding info+heuristic.
        self.assertNotIn("SYNC", rules.VERIFIED_RULES)
        sev, heuristic, verified = rules._gate("SYNC", "medium")
        self.assertEqual(sev, "info")
        self.assertTrue(heuristic)
        self.assertEqual(verified, [])

    def test_verified_rule_gate_promotes(self):
        sev, heuristic, verified = rules._gate("ZC", "high")
        self.assertEqual(sev, "high")
        self.assertFalse(heuristic)
        self.assertEqual(verified, [CONFIG])


if __name__ == "__main__":
    unittest.main()
