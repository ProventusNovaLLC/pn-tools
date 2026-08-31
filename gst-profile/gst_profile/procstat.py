"""CPU sampling from /proc: per thread (GStreamer names streaming threads after
their pad, e.g. "videotestsrc0:src", truncated to 15 chars in `comm`), per process,
and per core. Zero log overhead; replaces the rusage tracer.
"""
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class CpuSample:
    proc_pct: float = 0.0                        # % of ONE core (can exceed 100 on multi-thread)
    threads: Dict[str, float] = field(default_factory=dict)      # "tid:comm" -> % of one core
    per_core: List[float] = field(default_factory=list)          # % busy per core
    total_pct: float = 0.0                       # % busy of the whole machine (0-100)


class ProcStat:
    def __init__(self, pid: Optional[int], root: str = "/proc"):
        self.pid = pid
        self.root = root
        self.hz = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
        self._prev_threads: Dict[int, int] = {}          # tid -> jiffies (utime+stime)
        self._prev_proc: Optional[int] = None
        self._prev_cores: List[List[int]] = []           # [busy, total] per core
        self._prev_time: Optional[float] = None
        self._comm: Dict[int, str] = {}

    # ---- readers -----------------------------------------------------
    def _read(self, path: str) -> Optional[str]:
        try:
            with open(path) as fh:
                return fh.read()
        except (OSError, IOError):
            return None

    def _stat_jiffies(self, path: str) -> Optional[int]:
        s = self._read(path)
        if not s:
            return None
        rest = s[s.rfind(")") + 2:].split()             # fields after "comm)"; utime is index 11, stime 12 (of the tail)
        try:
            return int(rest[11]) + int(rest[12])
        except (IndexError, ValueError):
            return None

    def _cores(self) -> List[List[int]]:
        out = []
        s = self._read(os.path.join(self.root, "stat")) or ""
        for line in s.splitlines():
            if line.startswith("cpu") and not line.startswith("cpu "):
                parts = line.split()
                vals = [int(x) for x in parts[1:9]]
                idle = vals[3] + vals[4]                   # idle + iowait
                out.append([sum(vals) - idle, sum(vals)])
        return out

    # ---- sampling ----------------------------------------------------
    def sample(self, now: float) -> CpuSample:
        smp = CpuSample()
        cores = self._cores()
        if self._prev_cores and len(self._prev_cores) == len(cores):
            for (pb, pt), (b, t) in zip(self._prev_cores, cores):
                dt = t - pt
                smp.per_core.append(round(100.0 * (b - pb) / dt, 1) if dt > 0 else 0.0)
            if smp.per_core:
                smp.total_pct = round(sum(smp.per_core) / len(smp.per_core), 1)
        self._prev_cores = cores
        if self.pid is not None:
            proc = self._stat_jiffies(os.path.join(self.root, str(self.pid), "stat"))
            elapsed = (now - self._prev_time) if self._prev_time is not None else None
            if proc is not None and self._prev_proc is not None and elapsed and elapsed > 0:
                smp.proc_pct = round(100.0 * (proc - self._prev_proc) / self.hz / elapsed, 1)
            self._prev_proc = proc
            task_dir = os.path.join(self.root, str(self.pid), "task")
            try:
                tids = [int(t) for t in os.listdir(task_dir)]
            except OSError:
                tids = []
            cur: Dict[int, int] = {}
            comms: Dict[int, str] = {}
            for tid in tids:
                j = self._stat_jiffies(os.path.join(task_dir, str(tid), "stat"))
                if j is None:
                    continue
                cur[tid] = j
                comm = (self._read(os.path.join(task_dir, str(tid), "comm")) or "").strip()
                comms[tid] = comm
                prev = self._prev_threads.get(tid)
                # a tid can be recycled between samples: a changed name or a jiffies count that went
                # backwards means "new thread"; skip it this round, it is measured from the next sample
                if prev is not None and elapsed and elapsed > 0 and j >= prev and self._comm.get(tid) == comm:
                    smp.threads[f"{tid}:{comm}"] = round(100.0 * (j - prev) / self.hz / elapsed, 1)
            self._prev_threads = cur
            self._comm = comms                                   # pruned to live threads every sample
        self._prev_time = now
        return smp


def thread_to_element(comm: str, element_ids) -> Optional[str]:
    """Map a thread comm ("nvarguscamerasr", truncated pad name "nvarguscamerasrc0:src") to an element id.
    Longest element id that the comm starts with, or that starts with the comm (truncation), wins."""
    best = None
    for eid in element_ids:
        head = comm.split(":")[0]
        if head == eid or (len(comm) >= 15 and eid.startswith(head)) or comm.startswith(eid + ":"):
            if best is None or len(eid) > len(best):
                best = eid
    return best
