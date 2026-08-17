"""tegrastats line parser + subprocess source (NVIDIA Jetson only; absent elsewhere).

Line shapes vary by JetPack; the parser is token-based and tolerant:
  RAM 2831/7620MB (lfb 4x2MB) SWAP 0/3810MB (cached 0MB) CPU [12%@1420,8%@1420,off,off] EMC_FREQ 3%@2133 GR3D_FREQ 27%@[624] VIC_FREQ 15%@115 NVENC 716 NVDEC off ...
Values: N%@F, N%@[F], F (a bare frequency = unit on, load unknown), off.
"""
import re
import shutil
import subprocess
import threading
from typing import Dict, Optional

_CPU = re.compile(r"CPU \[(?P<cores>[^\]]*)\]")
_UNIT = re.compile(r"(?P<name>[A-Z0-9_]+)\s+(?P<val>\d+%@\[?\d+\]?|\d+%|off|\d+)(?=\s|$)")

UNIT_KEYS = {"GR3D_FREQ": "gr3d_pct", "GR3D": "gr3d_pct", "VIC_FREQ": "vic_pct", "VIC": "vic_pct",
             "NVENC": "nvenc_pct", "NVENC1": "nvenc_pct", "NVDEC": "nvdec_pct", "NVDEC1": "nvdec_pct",
             "EMC_FREQ": "emc_pct", "EMC": "emc_pct", "NVJPG": "nvjpg_pct"}


def parse_line(line: str) -> Dict[str, object]:
    out: Dict[str, object] = {}
    m = _CPU.search(line)
    if m:
        cores = []
        for tok in m.group("cores").split(","):
            tok = tok.strip()
            if tok == "off" or not tok:
                cores.append(None)
            else:
                try:
                    cores.append(float(tok.split("%")[0]))
                except ValueError:
                    cores.append(None)
        out["cpu_pct_per_core"] = cores
    for u in _UNIT.finditer(line):
        key = UNIT_KEYS.get(u.group("name"))
        if not key:
            continue
        val = u.group("val")
        if val == "off":
            out[key] = 0.0
        elif "%" in val:
            out[key] = float(val.split("%")[0])
        else:
            out.setdefault(key, None)         # unit on, load not reported by this tegrastats version
    return out


class TegrastatsSource:
    """Runs `tegrastats --interval <ms>` and keeps the latest parsed sample. Call `latest()` from the aggregator tick."""

    def __init__(self, interval_ms: int = 250, binary: str = "tegrastats"):
        self.binary = shutil.which(binary)
        self.interval_ms = interval_ms
        self._latest: Dict[str, object] = {}
        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def available(self) -> bool:
        return self.binary is not None

    def start(self):
        if not self.available:
            return False
        try:
            self._proc = subprocess.Popen([self.binary, "--interval", str(self.interval_ms)], stdout=subprocess.PIPE,
                                          stderr=subprocess.DEVNULL, text=True, bufsize=1)
        except OSError:
            self.binary = None
            return False
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()
        return True

    def _pump(self):
        assert self._proc and self._proc.stdout
        for line in self._proc.stdout:
            self._latest = parse_line(line)

    def latest(self) -> Dict[str, object]:
        return dict(self._latest)

    def stop(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
