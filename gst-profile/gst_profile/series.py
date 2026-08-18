"""Windowed aggregation of tracer records into fixed 250 ms rows.

Everything downstream (rules, panel, session JSON) reads rows, never raw records.
"""
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Set, Tuple

WINDOW_NS_DEFAULT = 250_000_000


def _pct(sorted_vals: List[float], p: float) -> Optional[float]:
    if not sorted_vals:
        return None
    k = max(0, min(len(sorted_vals) - 1, int(round(p * (len(sorted_vals) - 1)))))
    return sorted_vals[k]


@dataclass
class ElementRow:
    proc_ms_p50: Optional[float] = None
    proc_ms_p95: Optional[float] = None
    buffers: int = 0
    cpu_pct: Optional[float] = None          # filled by the /proc source
    queue_level: Optional[float] = None      # filled by the queue poller (run mode)


@dataclass
class LinkRow:
    fps: float = 0.0
    bytes_s: float = 0.0
    stalled: bool = False


@dataclass
class Row:
    t: float                                  # seconds since session start (window start)
    elements: Dict[str, ElementRow] = field(default_factory=dict)
    links: Dict[str, LinkRow] = field(default_factory=dict)
    latency_ms_p50: Optional[float] = None
    latency_ms_p95: Optional[float] = None
    reported_latency_ms: Optional[float] = None
    system: Dict[str, object] = field(default_factory=dict)   # cpu_pct_per_core, gr3d_pct, vic_pct, nvenc_pct, emc_pct


class Aggregator:
    """Feed records with `ingest(record, link_id=None)`; call `close_window(now_ns)` regularly;
    read finished rows from `rows`."""

    def __init__(self, window_ns: int = WINDOW_NS_DEFAULT, max_rows: int = 4 * 3600 * 4):
        self.window_ns = window_ns
        self.rows: Deque[Row] = deque(maxlen=max_rows)
        self.t0_ns: Optional[int] = None
        self._win_start: Optional[int] = None
        self._el_lat: Dict[str, List[float]] = defaultdict(list)       # element -> proc times (ms) this window
        self._link_n: Dict[str, int] = defaultdict(int)
        self._link_bytes: Dict[str, int] = defaultdict(int)
        self._pipe_lat: List[float] = []
        self._reported: Dict[str, float] = {}                          # element -> reported min latency (ms)
        self._seen_links: Set[str] = set()
        self._ever_flowed: Set[str] = set()
        self.system_sample: Dict[str, object] = {}                     # latest /proc + tegrastats sample
        self.gaps: List[Tuple[float, float]] = []                                    # (from_s, to_s) stretches skipped as one jump
        self.element_cpu: Dict[str, float] = {}                        # latest per-element cpu %
        self.queue_levels: Dict[str, float] = {}

    # ---- ingest --------------------------------------------------------
    MAX_FLUSH_PER_CALL = 400          # 100 s of empty windows; beyond that the axis jumps (gap noted)

    def _ensure_window(self, ts_ns: int):
        if self.t0_ns is None:
            self.t0_ns = ts_ns
            self._win_start = ts_ns
        self._advance_to(ts_ns)

    def _advance_to(self, ts_ns: int):
        n = 0
        while ts_ns >= self._win_start + self.window_ns:
            if n >= self.MAX_FLUSH_PER_CALL:
                # jump: align the window start to ts_ns, keep the time axis honest by recording the gap
                self.gaps.append(((self._win_start - self.t0_ns) / 1e9, (ts_ns - self.t0_ns) / 1e9))
                self._win_start = ts_ns - (ts_ns - self._win_start) % self.window_ns
                break
            self._flush()
            n += 1

    def ingest(self, rec, link_id: Optional[str] = None):
        f = rec.fields
        ts = int(f.get("ts", rec.wall_ns))
        self._ensure_window(ts)
        if rec.kind == "element-latency":
            self._el_lat[str(f["element"])].append(int(f["time"]) / 1e6)
        elif rec.kind == "latency":
            self._pipe_lat.append(int(f["time"]) / 1e6)
        elif rec.kind == "element-reported-latency":
            mn = int(f.get("min", 0))
            if mn < (1 << 62):
                self._reported[str(f.get("element", "?"))] = mn / 1e6
        elif rec.kind == "buffer" and link_id:
            self._link_n[link_id] += 1
            self._link_bytes[link_id] += int(f.get("buffer-size", 0))
            self._seen_links.add(link_id)
            self._ever_flowed.add(link_id)

    def note_link(self, link_id: str):
        self._seen_links.add(link_id)

    def close_window(self, now_ns: int):
        """Flush windows up to `now_ns` (wall-clock ns in the tracer's clock domain)."""
        if self.t0_ns is None:
            return
        self._advance_to(now_ns)

    # ---- flush ---------------------------------------------------------
    def _flush(self):
        secs = self.window_ns / 1e9
        row = Row(t=(self._win_start - self.t0_ns) / 1e9)
        for el, vals in self._el_lat.items():
            vals.sort()
            row.elements[el] = ElementRow(proc_ms_p50=_pct(vals, 0.5), proc_ms_p95=_pct(vals, 0.95), buffers=len(vals))
        for el, cpu in self.element_cpu.items():
            row.elements.setdefault(el, ElementRow()).cpu_pct = cpu
        for el, q in self.queue_levels.items():
            row.elements.setdefault(el, ElementRow()).queue_level = q
        any_flow = any(self._link_n.get(l, 0) for l in self._seen_links)
        for lid in self._seen_links:
            n = self._link_n.get(lid, 0)
            row.links[lid] = LinkRow(fps=n / secs, bytes_s=self._link_bytes.get(lid, 0) / secs,
                                     stalled=(n == 0 and lid in self._ever_flowed and any_flow))
        pl = sorted(self._pipe_lat)
        row.latency_ms_p50, row.latency_ms_p95 = _pct(pl, 0.5), _pct(pl, 0.95)
        row.reported_latency_ms = max(self._reported.values()) if self._reported else None
        row.system = dict(self.system_sample)
        self.rows.append(row)
        self._el_lat.clear(); self._link_n.clear(); self._link_bytes.clear(); self._pipe_lat.clear()
        self._win_start += self.window_ns

    # ---- serialization (columnar, per session schema) ------------------
    def to_dict(self) -> dict:
        rows = list(self.rows)
        el_names = sorted({e for r in rows for e in r.elements})
        link_ids = sorted({l for r in rows for l in r.links})
        out = {
            "window_ms": self.window_ns // 1_000_000,
            "t": [r.t for r in rows],
            "elements": {e: {"proc_ms_p50": [], "proc_ms_p95": [], "cpu_pct": [], "queue_level": [], "buffers": []} for e in el_names},
            "links": {l: {"fps": [], "bytes_s": [], "stalled": []} for l in link_ids},
            "pipeline": {"latency_ms_p50": [], "latency_ms_p95": [], "reported_latency_ms": []},
            "system": {"cpu_pct_per_core": [], "cpu_pct": [], "gr3d_pct": [], "vic_pct": [], "nvenc_pct": [], "nvdec_pct": [], "emc_pct": []},
        }
        for r in rows:
            for e in el_names:
                er = r.elements.get(e, ElementRow())
                d = out["elements"][e]
                d["proc_ms_p50"].append(er.proc_ms_p50); d["proc_ms_p95"].append(er.proc_ms_p95)
                d["cpu_pct"].append(er.cpu_pct); d["queue_level"].append(er.queue_level); d["buffers"].append(er.buffers)
            for l in link_ids:
                lr = r.links.get(l, LinkRow())
                d = out["links"][l]
                d["fps"].append(round(lr.fps, 3)); d["bytes_s"].append(round(lr.bytes_s, 1)); d["stalled"].append(lr.stalled)
            out["pipeline"]["latency_ms_p50"].append(r.latency_ms_p50)
            out["pipeline"]["latency_ms_p95"].append(r.latency_ms_p95)
            out["pipeline"]["reported_latency_ms"].append(r.reported_latency_ms)
            for k in out["system"]:
                out["system"][k].append(r.system.get(k))
        return out
