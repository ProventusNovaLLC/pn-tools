"""Analysis: a loaded session made convenient for rules, precomputed per-element/link/pipeline
aggregates over the whole run (or the live window). Rules read this, never the raw columnar series."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional


def _vals(col):
    return [x for x in col if x is not None]


def _p95(col):
    v = sorted(_vals(col))
    return v[int(round(0.95 * (len(v) - 1)))] if v else None


def _last(col):
    v = _vals(col)
    return v[-1] if v else None


def _max(col):
    v = _vals(col)
    return max(v) if v else None

def _sustained_interior_stall(stalled_col, tail=2, run=2):
    """True if there is a run of >= `run` stalled windows ending before the last `tail` windows
    (teardown stalls at the tail are expected and ignored)."""
    if len(stalled_col) <= tail + run:
        return False
    c = 0
    for v in stalled_col[:len(stalled_col) - tail]:
        c = c + 1 if v else 0
        if c >= run:
            return True
    return False



def _mean(col):
    v = _vals(col)
    return sum(v) / len(v) if v else None


@dataclass
class ElementStat:
    id: str
    factory: str
    vendor: str
    is_bin: bool
    klass: str
    props: Dict[str, str]
    proc_ms_p95: Optional[float]        # p95 of the per-window p95s over the run
    proc_ms_typ: Optional[float]        # mean of per-window p50s
    cpu_pct: Optional[float]            # peak segment cpu
    buffers: int


@dataclass
class LinkStat:
    id: str
    src: str                            # element:pad
    sink: str
    src_el: str
    sink_el: str
    memory: str
    media: str                          # "video/x-raw", "video/x-h264", ...  (ZC only cares about raw frames)
    fmt: Optional[str]
    fps: Optional[float]                # peak fps over the run (source cadence proxy)
    bytes_s: Optional[float]
    ever_stalled: bool                  # any stalled window (raw)
    stall_interior: bool                # >=2 consecutive stalled windows before the final 2 (a real mid-capture stall, not teardown)


@dataclass
class Analysis:
    session: dict
    platform: str
    caps: Dict[str, bool]
    elements: Dict[str, ElementStat]
    links: List[LinkStat]
    latency_ms_p95: Optional[float]
    reported_latency_ms: Optional[float]
    frame_period_ms: Optional[float]    # from the fastest source link fps, if any
    system_peak: Dict[str, Optional[float]]
    duration_s: float
    notes: List[str] = field(default_factory=list)

    # ---- graph helpers ----
    def downstream(self, el: str) -> List[str]:
        return [l.sink_el for l in self.links if l.src_el == el]

    def upstream(self, el: str) -> List[str]:
        return [l.src_el for l in self.links if l.sink_el == el]

    def link_between(self, a: str, b: str) -> Optional[LinkStat]:
        for l in self.links:
            if l.src_el == a and l.sink_el == b:
                return l
        return None

    def real_elements(self) -> List[ElementStat]:
        """Non-bin elements only; rules iterate these."""
        return [e for e in self.elements.values() if not e.is_bin]

    def hot_share(self) -> List[tuple]:
        """(element_id, proc_ms_p95, share_of_sum) sorted desc: the profile itself."""
        rows = [(e.id, e.proc_ms_p95 or 0.0) for e in self.real_elements() if e.proc_ms_p95]
        total = sum(v for _, v in rows) or 1.0
        return sorted(((eid, v, 100.0 * v / total) for eid, v in rows), key=lambda r: -r[1])


def build(session: dict) -> Analysis:
    g, s = session["graph"], session["series"]
    tgt = session.get("target", {})
    el_by_id = {e["id"]: e for e in g["elements"]}
    elements = {}
    for eid, e in el_by_id.items():
        col = s["elements"].get(eid, {})
        elements[eid] = ElementStat(
            id=eid, factory=e.get("factory", ""), vendor=e.get("vendor", "generic"),
            is_bin=e.get("is_bin", False), klass=e.get("klass", ""), props=e.get("props", {}),
            proc_ms_p95=_p95(col.get("proc_ms_p95", [])), proc_ms_typ=_mean(col.get("proc_ms_p50", [])),
            cpu_pct=_max(col.get("cpu_pct", [])), buffers=sum(x or 0 for x in col.get("buffers", [])),
        )
    links = []
    for l in g["links"]:
        col = s["links"].get(l["id"], {})
        se, ke = l["src"].split(":")[0], l["sink"].split(":")[0]
        links.append(LinkStat(
            id=l["id"], src=l["src"], sink=l["sink"], src_el=se, sink_el=ke,
            memory=l.get("memory", "unknown"), media=l.get("media", ""), fmt=l.get("format"),
            fps=_max(col.get("fps", [])), bytes_s=_max(col.get("bytes_s", [])),
            ever_stalled=any(col.get("stalled", [])),
            stall_interior=_sustained_interior_stall(col.get("stalled", [])),
        ))
    # frame period: the top source link's fps (max fps among links out of a source element)
    src_els = [e.id for e in elements.values() if not e.is_bin and not [l for l in links if l.sink_el == e.id] and [l for l in links if l.src_el == e.id]]
    src_fps = [l.fps for l in links if l.src_el in src_els and l.fps]
    frame_period = (1000.0 / max(src_fps)) if src_fps else None
    if frame_period is None:                                   # fall back to the fastest link anywhere
        anyfps = [l.fps for l in links if l.fps]
        frame_period = (1000.0 / max(anyfps)) if anyfps else None
    sysrow = s.get("system", {})
    system_peak = {k: _max(sysrow.get(k, [])) for k in ("cpu_pct", "gr3d_pct", "vic_pct", "nvenc_pct", "nvdec_pct", "emc_pct")}
    return Analysis(
        session=session, platform=tgt.get("platform", "generic"), caps=tgt.get("capabilities", {}),
        elements=elements, links=links,
        latency_ms_p95=_p95(s["pipeline"].get("latency_ms_p95", [])),
        reported_latency_ms=_last(s["pipeline"].get("reported_latency_ms", [])),
        frame_period_ms=frame_period, system_peak=system_peak,
        duration_s=session.get("session", {}).get("duration_s", 0.0),
        notes=list(session.get("session", {}).get("notes", [])),
    )
