import os
import shutil
import sys
import tempfile
import textwrap
import time
import unittest
from gst_profile.launcher import Launcher, build_env, TRACERS_FULL, TRACERS_OLD

FAKE_CHILD = textwrap.dedent('''
    import os, sys, time
    dot_dir = os.environ["GST_DEBUG_DUMP_DOT_DIR"]
    with open(os.path.join(dot_dir, "0.00.00.1-fake.PAUSED_PLAYING.dot"), "w") as fh:
        fh.write("digraph pipeline {\\n  label=\\"<GstPipeline>\\\\npipeline0\\\\n[>]\\";\\n}\\n")
    with open(os.environ["GST_DEBUG_FILE"], "w") as fh:
        for i in range(50):
            fh.write("0:00:00.%09d 1 0x1 TRACE GST_TRACER :0:: element-latency, element-id=(string)0x1, element=(string)e, src=(string)src, time=(guint64)1000, ts=(guint64)%d;\\n" % (i * 1000, i * 1000))
            fh.flush()
            time.sleep(0.01)
    sys.exit(7)
''')


class LauncherTest(unittest.TestCase):
    def test_build_env(self):
        env = build_env({"PATH": "/bin"}, "/tmp/f", "/tmp/d", element_latency=True, mode="wrap")
        self.assertEqual(env["GST_TRACERS"], TRACERS_FULL)
        self.assertEqual(env["GST_DEBUG"], "GST_TRACER:7,GST_EVENT:5")
        self.assertEqual(env["GST_DEBUG_FILE"], "/tmp/f")
        self.assertEqual(env["GST_DEBUG_DUMP_DOT_DIR"], "/tmp/d")
        self.assertEqual(env["GST_DEBUG_NO_COLOR"], "1")
        env = build_env({}, "/tmp/f", "/tmp/d", element_latency=False, mode="run")
        self.assertEqual(env["GST_TRACERS"], TRACERS_OLD)
        self.assertEqual(env["GST_DEBUG"], "GST_TRACER:7")

    def test_fifo_and_dot_pumped_and_exit_code(self):
        tmp = tempfile.mkdtemp()
        script = os.path.join(tmp, "child.py")
        with open(script, "w") as fh:
            fh.write(FAKE_CHILD)
        lines, dots = [], []
        l = Launcher([sys.executable, script], lines.append, dots.append, mode="wrap", workdir=tmp)
        l.start()
        self.assertIsNotNone(l.wait(timeout=10))
        code = l.stop()
        l.cleanup()
        self.assertEqual(code, 7)
        self.assertEqual(len(lines), 50)
        self.assertEqual(len(dots), 1)
        self.assertIn("pipeline0", dots[0])
        self.assertFalse(os.path.exists(l.fifo))
        shutil.rmtree(tmp)

    def test_unreadable_dot_is_retried_then_counted(self):
        tmp = tempfile.mkdtemp()
        script = os.path.join(tmp, "child.py")
        with open(script, "w") as fh:
            fh.write("import os, time\nd = os.environ['GST_DEBUG_DUMP_DOT_DIR']\nos.mkdir(os.path.join(d, 'not-a-file.dot'))\n"
                     "open(os.environ['GST_DEBUG_FILE'], 'w').close()\ntime.sleep(1.5)\n")
        dots = []
        l = Launcher([sys.executable, script], lambda s: None, dots.append, workdir=tmp)
        l.start()
        l.wait(timeout=10)
        l.stop()
        self.assertEqual(dots, [])
        self.assertEqual(l.dots_dropped, 1)              # a directory named *.dot: unreadable, retried, then given up on
        l.cleanup()
        shutil.rmtree(tmp)

    def test_stop_after_child_already_exited_keeps_exit_code(self):
        tmp = tempfile.mkdtemp()
        script = os.path.join(tmp, "quick.py")
        with open(script, "w") as fh:
            fh.write("import os, sys\nopen(os.environ['GST_DEBUG_FILE'], 'w').close()\nsys.exit(3)\n")
        l = Launcher([sys.executable, script], lambda s: None, lambda s: None, workdir=tmp)
        l.start()
        time.sleep(1.0)                                   # child is long gone and unreaped when stop() runs
        self.assertEqual(l.stop(), 3)
        l.cleanup()
        shutil.rmtree(tmp)

    def test_cleanup_removes_auto_created_workdir(self):
        script = os.path.join(tempfile.mkdtemp(), "noop.py")
        with open(script, "w") as fh:
            fh.write("import os\nopen(os.environ['GST_DEBUG_FILE'], 'w').close()\n")
        l = Launcher([sys.executable, script], lambda s: None, lambda s: None)      # no workdir= → we own it
        l.start()
        l.wait(timeout=10)
        l.stop()
        self.assertTrue(os.path.isdir(l.workdir))
        l.cleanup()
        self.assertFalse(os.path.exists(l.workdir))

    def test_stop_kills_a_stubborn_child(self):
        tmp = tempfile.mkdtemp()
        script = os.path.join(tmp, "stubborn.py")
        with open(script, "w") as fh:
            fh.write("import signal, time\nsignal.signal(signal.SIGINT, signal.SIG_IGN)\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\ntime.sleep(60)\n")
        l = Launcher([sys.executable, script], lambda s: None, lambda s: None, workdir=tmp)
        l.start()
        time.sleep(0.3)
        t0 = time.time()
        code = l.stop(grace=0.5)
        self.assertLess(time.time() - t0, 10)
        self.assertNotEqual(code, 0)
        self.assertFalse(l.running())
        shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
