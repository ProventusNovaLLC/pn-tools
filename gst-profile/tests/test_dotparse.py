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


MINI_BIN = r'''digraph pipeline {
  label="<GstPipeline>\npipeline0\n[>]";
  subgraph cluster_bin0_0x10 {
    label="GstBin\nbin0\n[>]";
    subgraph cluster_bin0_0x10_sink {
      label="";
      style="invis";
      _proxypad0_0x11 [color=black, fillcolor="#ddddff", label="proxypad0\n[>][bfb]", height="0.2", style="filled,solid"];
      bin0_0x10_ghost0_0x12 -> _proxypad0_0x11 [style=dashed, minlen=0]
      bin0_0x10_ghost0_0x12 [color=black, fillcolor="#ddddff", label="ghost0\n[>][bfb]", height="0.2", style="filled,solid"];
    }
    subgraph cluster_queue0_0x13 {
      label="GstQueue\nqueue0\n[>]";
      subgraph cluster_queue0_0x13_sink {
        label="";
        queue0_0x13_sink_0x14 [color=black, fillcolor="#aaaaff", label="sink\n[>][bfb]", height="0.2", style="filled,solid"];
      }
      subgraph cluster_queue0_0x13_src {
        label="";
        queue0_0x13_src_0x15 [color=black, fillcolor="#ffaaaa", label="src\n[>][bfb][T]", height="0.2", style="filled,solid"];
      }
      queue0_0x13_sink_0x14 -> queue0_0x13_src_0x15 [style="invis"];
    }
    subgraph cluster_fakesink0_0x16 {
      label="GstFakeSink\nfakesink0\n[>]";
      subgraph cluster_fakesink0_0x16_sink {
        label="";
        fakesink0_0x16_sink_0x17 [color=black, fillcolor="#aaaaff", label="sink\n[>][bfb]", height="0.2", style="filled,solid"];
      }
    }
    _proxypad0_0x11 -> queue0_0x13_sink_0x14 [label="video/x-raw\l"]
    queue0_0x13_src_0x15 -> fakesink0_0x16_sink_0x17 [label="video/x-raw\l"]
  }
  subgraph cluster_videotestsrc0_0x18 {
    label="GstVideoTestSrc\nvideotestsrc0\n[>]";
    subgraph cluster_videotestsrc0_0x18_src {
      label="";
      videotestsrc0_0x18_src_0x19 [color=black, fillcolor="#ffaaaa", label="src\n[>][bfb][T]", height="0.2", style="filled,solid"];
    }
  }
  videotestsrc0_0x18_src_0x19 -> bin0_0x10_ghost0_0x12 [label="video/x-raw\l"]
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

    def test_bin_ghost_proxypad_edges_are_dropped(self):
        # a `( queue ! fakesink )` bin: the src->ghost edge and the internal ghost/proxypad chain
        # must never surface as links — only the real queue0:src -> fakesink0:sink link should.
        g = parse_dot(MINI_BIN)
        self.assertEqual(len(g.links), 1)
        self.assertEqual((g.links[0].src_pad, g.links[0].sink_pad), ("queue0:src", "fakesink0:sink"))
        for l in g.links:
            self.assertNotIn("ghost", l.src_pad)
            self.assertNotIn("ghost", l.sink_pad)
            self.assertNotIn("proxypad", l.src_pad)
            self.assertNotIn("proxypad", l.sink_pad)

    def test_real_dump(self):
        with open(FIX) as fh:
            g = parse_dot(fh.read())
        self.assertEqual(g.pipeline_name, "pipeline0")
        self.assertEqual(sorted(e.name for e in g.elements), ["capsfilter0", "fakesink0", "queue0", "videoconvert0", "videotestsrc0"])
        self.assertEqual(len(g.links), 4)
        self.assertEqual(len(g.pads), 8)


if __name__ == "__main__":
    unittest.main()
