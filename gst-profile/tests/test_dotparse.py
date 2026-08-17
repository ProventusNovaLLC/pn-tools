import os
import unittest
from gst_profile.dotparse import parse_dot

HERE = os.path.dirname(__file__)
FIX = os.path.join(HERE, "..", "fixtures", "local-videotestsrc", "pipeline.PAUSED_PLAYING.dot")

MINI = r'''digraph pipeline {
  label="<GstPipeline>\npipeline0\n[>]";
  legend [
    label="Legend\lElement-States: [~] void-pending\l",
  ];
  subgraph cluster_nvvidconv0_0x1 {
    label="GstNvVidConv\nnvvidconv0\n[>]\nflip-method=2";
    subgraph cluster_nvvidconv0_0x1_sink {
      label="";
      nvvidconv0_0x1_sink_0x2 [color=black, fillcolor="#aaaaff", label="sink\n[>][bfb]", height="0.2", style="filled,solid"];
    }
    subgraph cluster_nvvidconv0_0x1_src {
      label="";
      nvvidconv0_0x1_src_0x3 [color=black, fillcolor="#ffaaaa", label="src\n[>][bfb]", height="0.2", style="filled,solid"];
    }
    nvvidconv0_0x1_sink_0x2 -> nvvidconv0_0x1_src_0x3 [style="invis"];
    fillcolor="#aaffaa";
  }
  nvvidconv0_0x1_src_0x3 -> nvv4l2h264enc0_0x4_sink_0x5 [label="video/x-raw(memory:NVMM)\l              format: NV12\l               width: 1920\l"]
  subgraph cluster_nvv4l2h264enc0_0x4 {
    label="GstNvV4l2H264Enc\nnvv4l2h264enc0\n[>]\nbitrate=4000000\ninsert-sps-pps=TRUE";
    subgraph cluster_nvv4l2h264enc0_0x4_sink {
      label="";
      nvv4l2h264enc0_0x4_sink_0x5 [color=black, fillcolor="#aaaaff", label="sink\n[>][bfb]", height="0.2", style="filled,solid"];
    }
    fillcolor="#aaaaff";
  }
}
'''


class DotParseTest(unittest.TestCase):
    def test_edge_declared_before_target_pads(self):
        g = parse_dot(MINI)
        self.assertEqual(g.pipeline_name, "pipeline0")
        self.assertEqual([e.name for e in g.elements], ["nvvidconv0", "nvv4l2h264enc0"])
        self.assertEqual(g.elements[0].props, {"flip-method": "2"})
        self.assertEqual(g.elements[1].props, {"bitrate": "4000000", "insert-sps-pps": "TRUE"})
        self.assertEqual(len(g.links), 1)
        self.assertEqual((g.links[0].src_pad, g.links[0].sink_pad), ("nvvidconv0:src", "nvv4l2h264enc0:sink"))
        self.assertIn("memory:NVMM", g.links[0].caps)

    def test_real_dump(self):
        with open(FIX) as fh:
            g = parse_dot(fh.read())
        self.assertEqual(g.pipeline_name, "pipeline0")
        self.assertEqual(sorted(e.name for e in g.elements), ["capsfilter0", "fakesink0", "queue0", "videoconvert0", "videotestsrc0"])
        self.assertEqual(len(g.links), 4)
        self.assertEqual(len(g.pads), 8)


if __name__ == "__main__":
    unittest.main()
