"""`gst-profile check`: discover what this machine can measure. Never fails; it narrows."""
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .model import Target

Runner = Callable[[List[str]], Optional[str]]


def _run(cmd: List[str]) -> Optional[str]:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None


@dataclass
class Capabilities:
    python: str = ""
    gst_launch: Optional[str] = None
    gst_inspect: Optional[str] = None
    gstreamer: str = ""
    tracers: List[str] = field(default_factory=list)
    element_latency: bool = False           # latency tracer per-element flag (>= 1.18)
    stats: bool = False
    tegrastats: bool = False
    dot: bool = True
    platform: str = "generic"
    board: str = ""
    l4t: str = ""
    problems: List[str] = field(default_factory=list)

    def sources_present(self) -> List[str]:
        out = ["tracer-log"] if self.gst_launch else []
        if self.dot:
            out.append("dot")
        out.append("procstat")
        if self.tegrastats:
            out.append("tegrastats")
        return out

    def sources_missing(self) -> List[str]:
        out = []
        if not self.tegrastats:
            out.append("tegrastats")
        if not self.element_latency:
            out.append("element-latency")
        return out

    def to_target(self) -> Target:
        return Target(gstreamer=self.gstreamer, platform=self.platform, board=self.board, l4t=self.l4t,
                      python=self.python, sources_present=self.sources_present(), sources_missing=self.sources_missing(),
                      capabilities={"element_latency": self.element_latency, "stats": self.stats,
                                    "queue_levels": False, "tegrastats": self.tegrastats})


def _version_tuple(v: str):
    try:
        return tuple(int(x) for x in v.split(".")[:3])
    except ValueError:
        return (0, 0, 0)


def read_file(path: str) -> str:
    try:
        with open(path, "rb") as fh:
            return fh.read().decode("utf-8", "replace").strip("\x00\n ")
    except OSError:
        return ""


def parse_l4t(text: str) -> str:
    """Extract 'MAJOR.REVISION' (e.g. '35.4.1') from /etc/nv_tegra_release content
    (e.g. '# R35 (release), REVISION: 4.1, GCID: ...'). '.*?' crosses the comma between
    the release marker and REVISION: — a plain [^,]* can't."""
    mm = re.search(r"R(\d+).*?REVISION:\s*([\d.]+)", text)
    return f"{mm.group(1)}.{mm.group(2)}" if mm else ""


def check(run: Runner = _run, which=shutil.which) -> Capabilities:
    c = Capabilities(python=".".join(map(str, sys.version_info[:3])))
    if sys.version_info < (3, 8):
        c.problems.append("python >= 3.8 required")
    c.gst_launch = which("gst-launch-1.0")
    c.gst_inspect = which("gst-inspect-1.0")
    if not c.gst_launch:
        c.problems.append("gst-launch-1.0 not found (needed for `run`; `wrap`/`analyze` still work if the app links GStreamer)")
    out = run([c.gst_launch or "gst-launch-1.0", "--version"]) or ""
    m = re.search(r"GStreamer\s+(\d+\.\d+\.\d+)", out)
    if m:
        c.gstreamer = m.group(1)
    if c.gst_inspect:
        ins = run([c.gst_inspect, "coretracers"]) or ""
        c.tracers = re.findall(r"^\s+([a-z]+)\s+\(GstTracerFactory\)", ins, re.M) or re.findall(r"^\s{2}([a-z]+):", ins, re.M)
    c.stats = "stats" in c.tracers or not c.tracers
    c.element_latency = _version_tuple(c.gstreamer) >= (1, 18, 0)
    if c.gstreamer and not c.element_latency:
        c.problems.append(f"GStreamer {c.gstreamer}: per-element latency needs >= 1.18 — HOT ranks by CPU/fps instead")
    c.tegrastats = which("tegrastats") is not None
    model = read_file("/proc/device-tree/model") or read_file("/sys/firmware/devicetree/base/model")
    c.board = model
    l4t = read_file("/etc/nv_tegra_release")
    if l4t or "NVIDIA" in model or "Jetson" in model:
        c.platform = "jetson"
        c.l4t = parse_l4t(l4t)
    elif "MediaTek" in model or "Genio" in model or "MT8" in model:
        c.platform = "mediatek"
    return c


def render(c: Capabilities) -> str:
    def yn(b):
        return "yes" if b else "no"
    lines = [
        f"gst-profile check",
        f"  python            {c.python}",
        f"  gstreamer         {c.gstreamer or 'not found'}   (gst-launch-1.0: {c.gst_launch or 'missing'})",
        f"  platform          {c.platform}  {c.board}  {('L4T ' + c.l4t) if c.l4t else ''}".rstrip(),
        f"  tracers           {', '.join(c.tracers) or 'unknown'}",
        f"  element latency   {yn(c.element_latency)}",
        f"  stats (topology)  {yn(c.stats)}",
        f"  tegrastats        {yn(c.tegrastats)}",
        f"  sources           present: {', '.join(c.sources_present())}   missing: {', '.join(c.sources_missing()) or '-'}",
    ]
    for p in c.problems:
        lines.append(f"  ! {p}")
    return "\n".join(lines)
