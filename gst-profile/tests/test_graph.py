import unittest
from gst_profile.graph import Graph, vendor_of, factory_from_gtype
from gst_profile.tracerlog import Record


def rec(kind, **fields):
    return Record(kind=kind, fields=fields, wall_ns=0)


class GraphTest(unittest.TestCase):
    def test_vendor(self):
        self.assertEqual(vendor_of("nvvidconv"), "nvidia")
        self.assertEqual(vendor_of("omxh264enc", "jetson"), "nvidia")     # gst-omx on Jetson (JP4) is NVIDIA's
        self.assertEqual(vendor_of("omxh264enc", "generic"), "generic")  # gst-omx also exists on RPi/others
        self.assertEqual(vendor_of("videoconvert"), "generic")
        self.assertEqual(vendor_of("v4l2h264enc", "mediatek"), "mediatek")
        self.assertEqual(vendor_of("v4l2h264enc", "jetson"), "generic")
        self.assertEqual(factory_from_gtype("GstVideoConvert"), "videoconvert")

    def test_from_stats_records_with_pending_caps(self):
        g = Graph()
        g.set_pad_caps("enc:sink", "video/x-raw(memory:NVMM), format=(string)NV12")   # negotiation happens before first buffer
        g.ingest_record(rec("new-element", ix=0, name="src", type="GstNvArgusCameraSrc"))
        g.ingest_record(rec("new-element", ix=1, name="enc", type="GstNvV4l2H264Enc"))
        g.ingest_record(rec("new-element", ix=2, name="pipeline0", type="GstPipeline", **{"is-bin": True}))
        g.ingest_record(rec("new-pad", ix=0, **{"parent-ix": 0}, name="src", **{"pad-direction": 1}))
        g.ingest_record(rec("new-pad", ix=1, **{"parent-ix": 1}, name="sink", **{"pad-direction": 2}))
        changed = g.ingest_record(rec("buffer", **{"pad-ix": 0, "peer-pad-ix": 1, "buffer-size": 10}))
        self.assertTrue(changed)
        link = g.links["src:src->enc:sink"]
        self.assertEqual(link.memory, "nvmm")
        self.assertEqual(link.format, "NV12")
        self.assertEqual(g.elements["src"].vendor, "nvidia")
        self.assertEqual(g.pipeline, "pipeline0")
        self.assertEqual(g.sources(), ["src"])
        self.assertEqual(g.sinks(), ["enc"])
        # buffer seen from the receiving side resolves to the same link
        self.assertEqual(g.link_for_stats_buffer(rec("buffer", **{"pad-ix": 1, "peer-pad-ix": 0})), "src:src->enc:sink")
        # repeat records for an established link, from either side, do not report a topology change
        self.assertFalse(g.ingest_record(rec("buffer", **{"pad-ix": 0, "peer-pad-ix": 1})))
        self.assertFalse(g.ingest_record(rec("buffer", **{"pad-ix": 1, "peer-pad-ix": 0})))
        self.assertEqual(len(g.links), 1)

    def test_unnegotiated_caps_never_downgrade_known_caps(self):
        g = Graph(platform="jetson")
        link = g.add_link("nvvidconv0:src", "nvv4l2h264enc0:sink", caps="video/x-raw(memory:NVMM), format=(string)NV12")
        self.assertEqual((link.memory, link.format), ("nvmm", "NV12"))
        for teardown_caps in ("", "   ", "ANY", "EMPTY"):                 # what NULL_READY / PAUSED_READY dumps carry
            self.assertFalse(link.set_caps(teardown_caps, "jetson"))
            g.add_link("nvvidconv0:src", "nvv4l2h264enc0:sink", caps=teardown_caps)
        self.assertEqual((link.memory, link.format), ("nvmm", "NV12"))
        self.assertFalse(g.set_pad_caps("nvv4l2h264enc0:sink", "ANY"))
        self.assertEqual(link.memory, "nvmm")

    def test_dict_roundtrip(self):
        g = Graph(platform="jetson")
        g.add_element("nvvidconv0", factory="nvvidconv").props["flip-method"] = "2"
        g.add_link("nvvidconv0:src", "nvv4l2h264enc0:sink", caps="video/x-raw(memory:NVMM), format=(string)NV12")
        d = g.to_dict()
        g2 = Graph.from_dict(d, platform="jetson")
        self.assertEqual(g2.to_dict(), d)
        self.assertEqual(g2.links["nvvidconv0:src->nvv4l2h264enc0:sink"].memory, "nvmm")


if __name__ == "__main__":
    unittest.main()
