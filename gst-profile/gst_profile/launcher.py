"""Spawn the pipeline/app under the tracer environment, read the FIFO, own the lifecycle."""
import os
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable, Dict, List, Optional

TRACERS_FULL = "latency(flags=pipeline+element+reported);stats"
TRACERS_OLD = "latency;stats"                    # GStreamer < 1.18: no per-element flag
TRACERS_LITE = "latency(flags=pipeline+element+reported)"


def build_env(base: Dict[str, str], fifo: str, dot_dir: str, element_latency: bool, mode: str, lite: bool = False,
              tracers: Optional[str] = None) -> Dict[str, str]:
    env = dict(base)
    tr = tracers or (TRACERS_LITE if lite else (TRACERS_FULL if element_latency else TRACERS_OLD))
    env["GST_TRACERS"] = tr
    debug = "GST_TRACER:7"
    if mode == "wrap":
        debug += ",GST_EVENT:5"                  # negotiated caps per sink pad; run mode gets caps from dot dumps
    env["GST_DEBUG"] = debug
    env["GST_DEBUG_FILE"] = fifo
    env["GST_DEBUG_NO_COLOR"] = "1"
    env["GST_DEBUG_DUMP_DOT_DIR"] = dot_dir
    env.pop("GST_DEBUG_COLOR_MODE", None)
    return env


class Launcher:
    """Runs `cmd` with the tracer env. `on_line(str)` is called for every log line from a reader thread;
    `on_dot(text)` for every new dot dump. Use `stop()` for Ctrl-C semantics."""

    def __init__(self, cmd: List[str], on_line: Callable[[str], None], on_dot: Callable[[str], None],
                 mode: str = "run", element_latency: bool = True, lite: bool = False, tracers: Optional[str] = None,
                 workdir: Optional[str] = None):
        self.cmd = cmd
        self.on_line = on_line
        self.on_dot = on_dot
        self.mode = mode
        self.element_latency = element_latency
        self.lite = lite
        self.tracers = tracers
        self._own_workdir = workdir is None
        self.workdir = workdir or tempfile.mkdtemp(prefix="gst-profile-")
        self.fifo = os.path.join(self.workdir, "trace.fifo")
        self.dot_dir = os.path.join(self.workdir, "dot")
        self.proc: Optional[subprocess.Popen] = None
        self.exit_code: Optional[int] = None
        self._stop = threading.Event()
        self._reader: Optional[threading.Thread] = None
        self._dot_thread: Optional[threading.Thread] = None
        self.lines_read = 0
        self.dropped = 0
        self.dots_dropped = 0
        self._seen_dots: set = set()
        self._dot_attempts: Dict[str, int] = {}
        self.DOT_MAX_ATTEMPTS = 3

    def start(self):
        os.makedirs(self.dot_dir, exist_ok=True)
        if os.path.exists(self.fifo):
            os.unlink(self.fifo)
        os.mkfifo(self.fifo)
        # open the reader BEFORE spawning so the child's open-for-write never blocks
        self._fd = os.open(self.fifo, os.O_RDONLY | os.O_NONBLOCK)
        env = build_env(os.environ, self.fifo, self.dot_dir, self.element_latency, self.mode, self.lite, self.tracers)
        self.proc = subprocess.Popen(self.cmd, env=env, start_new_session=True)     # own process group -> clean signals
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()
        self._dot_thread = threading.Thread(target=self._watch_dots, daemon=True)
        self._dot_thread.start()

    def _pump(self):
        buf = b""
        while not self._stop.is_set():
            r, _, _ = select.select([self._fd], [], [], 0.2)
            if not r:
                if self.proc and self.proc.poll() is not None and not buf:
                    # child gone and nothing pending: drain once more then exit
                    try:
                        tail = os.read(self._fd, 1 << 20)
                    except BlockingIOError:
                        tail = b""
                    if not tail:
                        break
                    buf += tail
                continue
            try:
                chunk = os.read(self._fd, 1 << 16)
            except BlockingIOError:
                continue
            if not chunk:                     # writer not connected yet / closed
                if self.proc and self.proc.poll() is not None:
                    break
                time.sleep(0.05)
                continue
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                self.lines_read += 1
                try:
                    self.on_line(line.decode("utf-8", "replace"))
                except Exception:               # a bad line must never kill the capture
                    self.dropped += 1
        if buf:
            try:
                self.on_line(buf.decode("utf-8", "replace"))
            except Exception:               # a bad final partial line must never kill the capture
                self.dropped += 1
        try:
            os.close(self._fd)
        except OSError:
            pass

    def _watch_dots(self):
        while not self._stop.is_set():
            try:
                names = sorted(os.listdir(self.dot_dir))
            except OSError:
                names = []
            for n in names:
                if not n.endswith(".dot") or n in self._seen_dots:
                    continue
                time.sleep(0.05)              # let the writer finish
                try:
                    with open(os.path.join(self.dot_dir, n), encoding="utf-8", errors="replace") as fh:
                        text = fh.read()
                except Exception:             # OSError (unreadable) or a decode error must not kill this thread
                    self._dot_attempts[n] = self._dot_attempts.get(n, 0) + 1
                    if self._dot_attempts[n] >= self.DOT_MAX_ATTEMPTS:      # give up, but say so
                        self._seen_dots.add(n)
                        self.dots_dropped += 1
                    continue                                                # retry on the next scan
                self._seen_dots.add(n)                                      # delivered exactly once
                try:
                    self.on_dot(text)
                except Exception:
                    self.dots_dropped += 1
            if self.proc and self.proc.poll() is not None:
                break
            time.sleep(0.25)

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def wait(self, timeout: Optional[float] = None) -> Optional[int]:
        if not self.proc:
            return None
        try:
            self.exit_code = self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None
        return self.exit_code

    def stop(self, grace: float = 5.0) -> Optional[int]:
        """SIGINT the child's process group (gst-launch does a clean EOS on SIGINT), then TERM, then KILL."""
        escalate_msg = {
            signal.SIGTERM: "gst-profile: child ignored SIGINT, sending SIGTERM",
            signal.SIGKILL: "gst-profile: child ignored SIGTERM, sending SIGKILL",
        }
        if self.proc and self.proc.poll() is None:
            for sig, wait_s in ((signal.SIGINT, grace), (signal.SIGTERM, 3.0), (signal.SIGKILL, 2.0)):
                if sig in escalate_msg:
                    print(escalate_msg[sig], file=sys.stderr)
                try:
                    os.killpg(self.proc.pid, sig)
                except ProcessLookupError:
                    break
                try:
                    self.exit_code = self.proc.wait(timeout=wait_s)
                    break
                except subprocess.TimeoutExpired:
                    continue
        else:
            self.exit_code = self.proc.returncode if self.proc else None
        if self.proc and self.exit_code is None:            # child died between poll() and killpg(): reap it
            self.exit_code = self.proc.poll()
        # child is dead: let the reader drain to FIFO EOF on its own (it exits within ~0.2s of that) before
        # we force it to stop, so a fast pipeline's tail isn't lost to a mid-buffer _stop.
        if self._reader:
            self._reader.join(timeout=3)
        self._stop.set()
        if self._reader:
            self._reader.join(timeout=2)
        if self._dot_thread:
            self._dot_thread.join(timeout=2)
        return self.exit_code

    def cleanup(self):
        """Remove the FIFO; when the workdir was created by us (no `workdir=` given), remove it entirely."""
        try:
            os.unlink(self.fifo)
        except OSError:
            pass
        if self._own_workdir:
            shutil.rmtree(self.workdir, ignore_errors=True)
