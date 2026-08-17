import os
import tempfile
import unittest
from gst_profile.procstat import ProcStat, thread_to_element


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


STAT_TEMPLATE = "{pid} ({comm}) S 1 1 1 0 -1 4194560 0 0 0 0 {ut} {st} 0 0 20 0 3 0 100 0 0 18446744073709551615 0 0 0 0 0 0 0 0 0 0 0 0 17 0 0 0 0 0 0 0 0 0 0 0 0 0 0"


class ProcStatTest(unittest.TestCase):
    def test_sampling_from_fake_proc(self):
        root = tempfile.mkdtemp()
        def snapshot(cpu_busy, cpu_total, proc_j, thread_j):
            write(f"{root}/stat", f"cpu  {cpu_busy} 0 0 {cpu_total - cpu_busy} 0 0 0 0 0 0\ncpu0 {cpu_busy} 0 0 {cpu_total - cpu_busy} 0 0 0 0 0 0\n")
            write(f"{root}/42/stat", STAT_TEMPLATE.format(pid=42, comm="gst-launch-1.0", ut=proc_j, st=0))
            write(f"{root}/42/task/43/stat", STAT_TEMPLATE.format(pid=43, comm="videotestsrc0:s", ut=thread_j, st=0))
            write(f"{root}/42/task/43/comm", "videotestsrc0:s\n")
        ps = ProcStat(42, root=root)
        ps.hz = 100
        snapshot(0, 100, 0, 0)
        ps.sample(1000.0)
        snapshot(50, 200, 50, 30)                # 1 s later: core 50% busy, proc used 50 jiffies (=50%), thread 30 (=30%)
        s = ps.sample(1001.0)
        self.assertEqual(s.per_core, [50.0])
        self.assertEqual(s.total_pct, 50.0)
        self.assertEqual(s.proc_pct, 50.0)
        self.assertEqual(s.threads, {"43:videotestsrc0:s": 30.0})

    def test_thread_to_element_truncation(self):
        ids = ["nvarguscamerasrc0", "nvvidconv0", "queue0", "nvv4l2h264enc0"]
        self.assertEqual(thread_to_element("nvarguscamerasr", ids), "nvarguscamerasrc0")   # 15-char comm truncation
        self.assertEqual(thread_to_element("queue0:src", ids), "queue0")
        self.assertIsNone(thread_to_element("gmain", ids))
        self.assertIsNone(thread_to_element("pool-spawner", ids))


if __name__ == "__main__":
    unittest.main()
