import json, os, unittest
from gst_profile import analysis, rules

FX = os.path.join(os.path.dirname(__file__), "fixtures")


def load(name):
    with open(os.path.join(FX, name)) as fh:
        return json.load(fh)


class RulesTest(unittest.TestCase):
    def setUp(self):
        _saved = dict(rules.VERIFIED_RULES)   # restore the real bench-verified default after each test
        def _restore():
            rules.VERIFIED_RULES.clear(); rules.VERIFIED_RULES.update(_saved)
        self.addCleanup(_restore)
        rules.VERIFIED_RULES.clear()          # isolate the gate: nothing verified inside this class

    def fired(self, session):
        return {f.rule for f in rules.run_rules(analysis.build(session))}

    def test_healthy_software_is_hot_plus_ok_only(self):
        fs = rules.run_rules(analysis.build(load("software-healthy.json")))
        kinds = {f.rule for f in fs}
        self.assertIn("HOT", kinds)
        self.assertIn("OK", kinds)
        self.assertNotIn("STALL", kinds)               # healthy teardown must not trip STALL
        self.assertTrue(all(f.severity == "info" for f in fs))  # nothing verified -> all info

    def test_zc_island_fires_on_round_trip(self):
        fs = {f.rule: f for f in rules.run_rules(analysis.build(load("jetson-zc-break.json")))}
        self.assertIn("ZC", fs)
        zc = fs["ZC"]
        self.assertIn("nvvidconv0:sink", "".join(zc.targets["links"]) + " " + str(zc.targets))
        self.assertEqual(zc.fix_patch["kind"], "set-caps")
        # SW (videoconvert), SYNC (udpsink sync=true), ENC (bframes/insert-sps-pps), VIC (85%), CAPS all present
        for r in ("SW", "SYNC", "ENC", "VIC", "CAPS"):
            self.assertIn(r, fs, r)

    def test_zc_silent_on_encoded_sysmem_link(self):
        # all-hardware encode->decode loopback: the h264 sysmem link between codecs is normal,
        # NOT a zero-copy break: ZC must not fire on an encoded-bitstream sysmem link.
        self.assertNotIn("ZC", self.fired(load("jetson-hw-loopback.json")))

    def test_zc_silent_on_clean_nvmm_pipeline(self):
        s = load("jetson-zc-break.json")
        for l in s["graph"]["links"]:
            if l["format"]:
                l["memory"] = "nvmm"
        self.assertNotIn("ZC", self.fired(s))

    def test_gate_promotes_only_verified_rules(self):
        s = load("jetson-zc-break.json")
        base = {f.rule: f.severity for f in rules.run_rules(analysis.build(s))}
        self.assertTrue(all(v == "info" for v in base.values()))
        rules.VERIFIED_RULES.update({"ZC": ["orin-nx-r36.4"], "SW": ["orin-nx-r36.4"]})
        after = {f.rule: (f.severity, f.heuristic) for f in rules.run_rules(analysis.build(s))}
        self.assertEqual(after["ZC"][0], "high")
        self.assertEqual(after["SW"][0], "medium")
        self.assertFalse(after["ZC"][1])
        self.assertEqual(after["SYNC"][0], "info")     # still not verified
        self.assertTrue(any(f.severity in ("high", "medium") for f in rules.run_rules(analysis.build(s))))

    def test_ok_suppressed_when_something_fires(self):
        # the zc fixture has real findings -> OK must not appear even though latency < frame period
        self.assertNotIn("OK", self.fired(load("jetson-zc-break.json")))

    def test_ranking_orders_by_severity_then_share(self):
        rules.VERIFIED_RULES.update({"ZC": ["hw"], "SW": ["hw"], "VIC": ["hw"], "ENC": ["hw"]})
        fs = rules.run_rules(analysis.build(load("jetson-zc-break.json")))
        sev = [f.severity for f in fs]
        order = {"high": 0, "medium": 1, "info": 2}
        self.assertEqual(sev, sorted(sev, key=lambda s: order[s]))
        self.assertEqual(fs[0].rank, 1)

    def test_tegrastats_rules_absent_without_the_source(self):
        s = load("jetson-zc-break.json")
        s["target"]["capabilities"]["tegrastats"] = False
        self.assertNotIn("VIC", self.fired(s))
        self.assertNotIn("HW", self.fired(s))


if __name__ == "__main__":
    unittest.main()
