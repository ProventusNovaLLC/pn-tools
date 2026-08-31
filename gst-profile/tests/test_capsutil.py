import unittest
from gst_profile.capsutil import parse_caps, memory_domain


class CapsTest(unittest.TestCase):
    def test_serialized_form(self):
        c = parse_caps("video/x-raw(memory:NVMM), format=(string)NV12, width=(int)1920, height=(int)1080, framerate=(fraction)30/1")
        self.assertEqual(c.media, "video/x-raw")
        self.assertEqual(c.features, ["memory:NVMM"])
        self.assertEqual(c.format, "NV12")
        self.assertEqual(c.size(), (1920, 1080))
        self.assertEqual(c.framerate(), 30.0)
        self.assertEqual(memory_domain(c), "nvmm")

    def test_pretty_dot_form(self):
        c = parse_caps("video/x-raw(memory:NVMM)\\l              format: NV12\\l               width: 1920\\l              height: 1080\\l           framerate: 30/1\\l")
        self.assertEqual(c.media, "video/x-raw")
        self.assertEqual(c.format, "NV12")
        self.assertEqual(c.size(), (1920, 1080))
        self.assertEqual(memory_domain(c), "nvmm")

    def test_memory_domains(self):
        self.assertEqual(memory_domain(parse_caps("video/x-raw, format=(string)I420")), "sysmem")
        self.assertEqual(memory_domain(parse_caps("video/x-raw(memory:DMABuf), format=(string)NV12")), "dmabuf")
        self.assertEqual(memory_domain(parse_caps("video/x-raw(memory:CUDAMemory), format=(string)NV12")), "unknown")
        self.assertEqual(memory_domain(None), "unknown")
        self.assertEqual(memory_domain(parse_caps("ANY")), "unknown")

    def test_list_values_do_not_break_fields(self):
        c = parse_caps("video/x-raw, format=(string){ NV12, I420 }, width=(int)[ 16, 4096 ]")
        self.assertEqual(c.fields["format"], "{ NV12, I420 }")
        self.assertEqual(c.fields["width"], "[ 16, 4096 ]")


if __name__ == "__main__":
    unittest.main()
