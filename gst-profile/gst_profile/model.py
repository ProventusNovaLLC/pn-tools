"""Session model: graph + series + system + findings + events, and the builder
that feeds it from the sources. `to_json()` is the session file (schema gst-profile/1)."""
import json
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

from .graph import Graph
from .series import Aggregator
from .tracerlog import Record, CapsEvent, ParseStats, parse_line
from .procstat import thread_to_element

SCHEMA = "gst-profile/1"
STATS_KINDS = ("new-element", "new-pad", "buffer")


@dataclass
class Target:
    gstreamer: str = ""
    platform: str = "generic"        # jetson | mediatek | generic
    board: str = ""
    l4t: str = ""
    python: str = ""
    sources_present: List[str] = field(default_factory=list)
    sources_missing: List[str] = field(default_factory=list)
    capabilities: Dict[str, bool] = field(default_factory=dict)


@dataclass
class Event:
    t: float
    kind: str                        # mark | state | error | eos | child-exit | note
    text: str


class Session:
    def __init__(self, mode: str, target: Optional[Target] = None, launch: Optional[str] = None,
                 command: Optional[List[str]] = None, label: str = "", session_id: str = ""):
        self.id = session_id or time.strftime("%Y%m%dT%H%M%S")
        self.started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.mode = mode
        self.launch = launch
        self.command = command
        self.label = label
        self.parent_session: Optional[str] = None
        self.target = target or Target()
        self.graph = Graph(platform=self.target.platform)
        self.agg = Aggregator()
        self.findings: List[dict] = []
        self.events: List[Event] = []
        self.parse_stats = ParseStats()
        self.threads: Dict[str, float] = {}          # latest per-thread cpu ("tid:comm" -> %)
        self.duration_s: float = 0.0
        self.notes: List[str] = []

    # ---- ingest ------------------------------------------------------------
    def ingest_line(self, line: str):
        item = parse_line(line, self.parse_stats)
        if item is None:
            return
        if isinstance(item, CapsEvent):
            self.graph.set_pad_caps(item.pad, item.caps)
        elif isinstance(item, Record):
            self.ingest_record(item)

    def ingest_record(self, rec: Record):
        if rec.kind in STATS_KINDS:
            self.graph.ingest_record(rec)
        link_id = self.graph.link_for_stats_buffer(rec) if rec.kind == "buffer" else None
        self.agg.ingest(rec, link_id)
        if rec.kind == "message" and rec.fields.get("name") in ("error", "eos", "state-changed"):
            self.add_event(str(rec.fields.get("name")), str(rec.fields.get("structure", ""))[:200], ts_ns=int(rec.fields.get("ts", rec.wall_ns)))

    def ingest_dot(self, text: str) -> bool:
        return self.graph.ingest_dot(text)

    def ingest_cpu(self, sample):
        """CpuSample from procstat -> element cpu attribution + system row."""
        self.threads = dict(sample.threads)
        owners = {}
        for key, pct in sample.threads.items():
            comm = key.split(":", 1)[1] if ":" in key else key
            el = thread_to_element(comm, list(self.graph.elements))
            if el:
                owners[el] = owners.get(el, 0.0) + pct
        # attribute each thread's CPU to the segment it drives: owner -> downstream until the next thread owner (queue etc.)
        per_element: Dict[str, float] = {}
        for owner, pct in owners.items():
            for el in self._segment(owner, set(owners)):
                per_element[el] = per_element.get(el, 0.0) + pct
        self.agg.element_cpu = per_element
        sysrow = dict(self.agg.system_sample)
        sysrow["cpu_pct_per_core"] = sample.per_core
        sysrow["cpu_pct"] = sample.total_pct
        sysrow["proc_pct"] = sample.proc_pct
        self.agg.system_sample = sysrow

    def ingest_tegrastats(self, sample: Dict[str, object]):
        sysrow = dict(self.agg.system_sample)
        for k in ("gr3d_pct", "vic_pct", "nvenc_pct", "nvdec_pct", "emc_pct", "nvjpg_pct"):
            if k in sample:
                sysrow[k] = sample[k]
        if "cpu_pct_per_core" in sample and not sysrow.get("cpu_pct_per_core"):
            sysrow["cpu_pct_per_core"] = sample["cpu_pct_per_core"]
        self.agg.system_sample = sysrow

    def _segment(self, start: str, owners: set) -> List[str]:
        seg, frontier, seen = [], [start], set()
        while frontier:
            el = frontier.pop()
            if el in seen:
                continue
            seen.add(el); seg.append(el)
            for nxt in self.graph.downstream(el):
                if nxt not in owners:                    # a downstream thread owner starts a new segment
                    frontier.append(nxt)
        return seg

    def add_event(self, kind: str, text: str, ts_ns: Optional[int] = None):
        t = 0.0
        if ts_ns is not None and self.agg.t0_ns is not None:
            t = max(0.0, (ts_ns - self.agg.t0_ns) / 1e9)
        elif self.agg.rows:
            t = self.agg.rows[-1].t
        self.events.append(Event(t=round(t, 3), kind=kind, text=text))

    def tick(self, now_ns: int):
        self.agg.close_window(now_ns)

    # ---- serialization -------------------------------------------------------
    def to_dict(self) -> dict:
        series = self.series_dict()
        rows_t = series.get("t", [])
        if rows_t and not getattr(self, "_series_dict", None):
            self.duration_s = round(rows_t[-1] + self.agg.window_ns / 1e9, 3)
        return {
            "schema": SCHEMA,
            "session": {"id": self.id, "started": self.started, "duration_s": self.duration_s, "mode": self.mode,
                        "launch": self.launch, "command": self.command, "label": self.label,
                        "parent_session": self.parent_session,
                        "parse": asdict(self.parse_stats), "notes": self.notes},
            "target": asdict(self.target),
            "graph": self.graph.to_dict(),
            "series": series,
            "threads": self.threads,
            "findings": self.findings,
            "events": [asdict(e) for e in self.events],
        }

    def to_json(self, indent: Optional[int] = None) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, d: dict) -> "Session":
        s = cls(mode=d["session"].get("mode", "analyze"))
        s.id = d["session"].get("id", s.id); s.started = d["session"].get("started", s.started)
        s.launch = d["session"].get("launch"); s.command = d["session"].get("command")
        s.label = d["session"].get("label", ""); s.parent_session = d["session"].get("parent_session")
        s.duration_s = d["session"].get("duration_s", 0.0); s.notes = list(d["session"].get("notes", []))
        ps = d["session"].get("parse", {})
        for k, v in ps.items():
            if hasattr(s.parse_stats, k):
                setattr(s.parse_stats, k, v)
        t = d.get("target", {}); s.target = Target(**{k: t.get(k, getattr(Target(), k)) for k in Target().__dict__})
        s.graph = Graph.from_dict(d.get("graph", {}), platform=s.target.platform)
        s.findings = list(d.get("findings", [])); s.threads = dict(d.get("threads", {}))
        s.events = [Event(**e) for e in d.get("events", [])]
        s._series_dict = d.get("series", {})            # replayed sessions keep the columnar series as-is
        return s

    def series_dict(self) -> dict:
        return getattr(self, "_series_dict", None) or self.agg.to_dict()
