import unittest
from gst_profile.tegrastats import parse_line


class TegrastatsTest(unittest.TestCase):
    def test_jp5_style(self):
        d = parse_line("RAM 2831/7620MB (lfb 4x2MB) SWAP 0/3810MB (cached 0MB) CPU [12%@1420,8%@1420,0%@1420,3%@1420,off,off] EMC_FREQ 3%@2133 GR3D_FREQ 27%@[624] VIC_FREQ 15%@115 NVENC 716 NVDEC off NVJPG off APE 174 cpu@45.5C")
        self.assertEqual(d["cpu_pct_per_core"], [12.0, 8.0, 0.0, 3.0, None, None])
        self.assertEqual(d["gr3d_pct"], 27.0)
        self.assertEqual(d["vic_pct"], 15.0)
        self.assertEqual(d["emc_pct"], 3.0)
        self.assertIsNone(d["nvenc_pct"])          # bare frequency: on, load unknown
        self.assertEqual(d["nvdec_pct"], 0.0)      # off

    def test_percent_only_variant(self):
        d = parse_line("RAM 1/2MB (lfb 1x1MB) SWAP 0/0MB (cached 0MB) CPU [1%@729,0%@729] GR3D_FREQ 0% VIC 0%@115 NVENC off EMC_FREQ 0%@2133")
        self.assertEqual(d["gr3d_pct"], 0.0)
        self.assertEqual(d["vic_pct"], 0.0)
        self.assertEqual(d["nvenc_pct"], 0.0)

    def test_garbage(self):
        self.assertEqual(parse_line("not a tegrastats line"), {})


if __name__ == "__main__":
    unittest.main()
