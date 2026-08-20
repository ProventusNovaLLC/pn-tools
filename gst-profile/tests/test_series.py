import unittest
from gst_profile.series import Aggregator
from gst_profile.tracerlog import Record

W = 250_000_000


def rec(kind, ts, **f):
    return Record(kind=kind, fields=dict(ts=ts, **f), wall_ns=ts)


class SeriesTest(unittest.TestCase):
    def test_windows_percentiles_fps_bytes(self):
        a = Aggregator()
        for i in range(8):                                    # 8 buffers in window 0 (250 ms) = 32 fps
            a.ingest(rec("element-latency", ts=i * 30_000_000, element="conv", time=(i + 1) * 100_000))
            a.ingest(rec("buffer", ts=i * 30_000_000, **{"buffer-size": 1000}), link_id="a:src->conv:sink")
            a.ingest(rec("latency", ts=i * 30_000_000, time=5_000_000))
        a.ingest(rec("element-reported-latency", ts=0, element="src", min=33_333_333, max=(1 << 64) - 1))
        a.ingest(rec("element-reported-latency", ts=0, element="q", min=10_000_000, max=(1 << 64) - 1))
        a.close_window(W)                                     # flush window 0
        self.assertEqual(len(a.rows), 1)
        row = a.rows[0]
        self.assertEqual(row.t, 0.0)
        self.assertEqual(row.elements["conv"].buffers, 8)
        self.assertAlmostEqual(row.elements["conv"].proc_ms_p50, 0.5, places=3)   # index round(0.5*7)=4 -> 0.5 ms
        self.assertAlmostEqual(row.elements["conv"].proc_ms_p95, 0.8, places=3)   # index round(0.95*7)=7 -> 0.8 ms
        self.assertAlmostEqual(row.links["a:src->conv:sink"].fps, 32.0)
        self.assertAlmostEqual(row.links["a:src->conv:sink"].bytes_s, 32000.0)
        self.assertFalse(row.links["a:src->conv:sink"].stalled)
        self.assertAlmostEqual(row.latency_ms_p95, 5.0)
        self.assertAlmostEqual(row.reported_latency_ms, 33.333333, places=3)     # max of per-element minimums

    def test_stall_and_gap(self):
        a = Aggregator()
        a.ingest(rec("buffer", ts=0, **{"buffer-size": 1}), link_id="l")
        a.close_window(2 * W)                                 # window 0 (flowing) and window 1 (nothing)
        # window 1 carries no buffers on ANY link (e.g. teardown quiet at the capture's last window):
        # that's the whole pipeline going quiet, not this one link stalling, so it must read False too.
        self.assertEqual([r.links["l"].stalled for r in a.rows], [False, False])
        a.close_window(10**18)                                # absurd jump must be bounded and recorded
        self.assertLessEqual(len(a.rows), 2 + Aggregator.MAX_FLUSH_PER_CALL)
        self.assertEqual(len(a.gaps), 1)

    def test_single_link_stall_while_pipeline_still_flows(self):
        a = Aggregator()
        # two links share a window; one keeps flowing, the other goes quiet in the SAME window:
        # that is a genuine single-link stall and must still report True.
        a.ingest(rec("buffer", ts=0, **{"buffer-size": 1}), link_id="flowing")
        a.ingest(rec("buffer", ts=0, **{"buffer-size": 1}), link_id="quiet")
        a.close_window(W)                                     # window 0: both links carried a buffer
        a.ingest(rec("buffer", ts=W, **{"buffer-size": 1}), link_id="flowing")
        a.note_link("quiet")                                  # "quiet" still tracked but carries nothing this window
        a.close_window(2 * W)                                 # window 1: "flowing" flows, "quiet" doesn't
        self.assertFalse(a.rows[1].links["flowing"].stalled)
        self.assertTrue(a.rows[1].links["quiet"].stalled)

    def test_to_dict_columns_align(self):
        a = Aggregator()
        a.ingest(rec("element-latency", ts=0, element="x", time=1000))
        a.ingest(rec("element-latency", ts=W, element="y", time=2000))
        a.close_window(2 * W)
        d = a.to_dict()
        self.assertEqual(d["t"], [0.0, 0.25])
        self.assertEqual(d["elements"]["x"]["proc_ms_p95"], [0.001, None])
        self.assertEqual(d["elements"]["y"]["proc_ms_p95"], [None, 0.002])
        self.assertEqual(len(d["pipeline"]["latency_ms_p95"]), 2)
        self.assertEqual(d["window_ms"], 250)


if __name__ == "__main__":
    unittest.main()
