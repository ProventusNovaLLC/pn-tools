import unittest
from gst_profile.launchparse import parse_launch


class LaunchParseTest(unittest.TestCase):
    def test_capsfilters_are_elements_like_gst_launch(self):
        g, notes = parse_launch('nvarguscamerasrc sensor-id=0 ! "video/x-raw(memory:NVMM),width=1920,height=1080" ! nvvidconv ! video/x-raw,format=BGRx ! appsink name=out sync=false', platform="jetson")
        self.assertEqual(list(g.elements), ["nvarguscamerasrc0", "capsfilter0", "nvvidconv0", "capsfilter1", "out"])
        self.assertEqual(g.elements["nvarguscamerasrc0"].props, {"sensor-id": "0"})
        self.assertEqual(g.elements["out"].props, {"sync": "false"})
        self.assertEqual(g.links["capsfilter0:src->nvvidconv0:sink"].memory, "nvmm")
        self.assertEqual(g.links["capsfilter1:src->out:sink"].memory, "sysmem")
        self.assertEqual(g.links["nvarguscamerasrc0:src->capsfilter0:sink"].memory, "unknown")
        self.assertEqual(notes, [])
        self.assertNotIn("sink", g.elements["nvarguscamerasrc0"].pads)
        self.assertNotIn("src", g.elements["out"].pads)

    def test_tee_branches(self):
        g, _ = parse_launch("v4l2src ! tee name=t ! queue ! fakesink t. ! queue ! fakesink")
        self.assertIn("t:src->queue0:sink", g.links)
        self.assertIn("t:src->queue1:sink", g.links)
        self.assertEqual(g.downstream("t"), ["queue0", "queue1"])
        self.assertEqual(sorted(g.sinks()), ["fakesink0", "fakesink1"])

    def test_notes_on_bins(self):
        g, notes = parse_launch("videotestsrc ! ( queue ! fakesink )")
        self.assertTrue(any("bins" in n for n in notes))
        self.assertIn("videotestsrc0", g.elements)


if __name__ == "__main__":
    unittest.main()
