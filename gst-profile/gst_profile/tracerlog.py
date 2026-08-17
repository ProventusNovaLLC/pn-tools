r"""Parse GStreamer debug-log lines produced by the core tracers.

Record line shape (GST_DEBUG=GST_TRACER:7):
  0:00:00.041343812 2724071 0x7b934c000d20 TRACE GST_TRACER :0:: element-latency, element-id=(string)0x5783585dbb30, element=(string)videoconvert0, src=(string)src, time=(guint64)157003, ts=(guint64)41360434;
Caps line shape (GST_DEBUG=GST_EVENT:5, wrap mode):
  0:00:00.017852044 2724438 0x761d8c000d50 DEBUG GST_EVENT gstpad.c:5892:gst_pad_send_event_unchecked:<capsfilter0:sink> have event type caps event: 0x..., time ..., seq-num 34, GstEventCaps, caps=(GstCaps)"video/x-raw\,\ format\=\(string\)I420\,\ ...";
"""
import re
from dataclasses import dataclass
from typing import Dict, Optional, Union

Value = Union[int, str, bool]

_HEAD = re.compile(
    r"^(?P<ts>\d+:\d\d:\d\d\.\d+)\s+(?P<pid>\d+)\s+(?P<thread>0x[0-9a-f]+)\s+"
    r"(?P<level>[A-Z]+)\s+(?P<cat>[A-Z_]+)\s+(?P<rest>.*)$"
)
_TRACER_REC = re.compile(r"^:0::\s+(?P<kind>[a-z][a-z0-9-]*),\s*(?P<body>.*);\s*$")
_FIELD = re.compile(r"(?P<key>[a-zA-Z0-9-]+)=\((?P<type>[A-Za-z0-9]+)\)(?P<val>\"(?:[^\"\\]|\\.)*\"|[^,;]*)")
_CAPS_LINE = re.compile(
    r"gst_pad_send_event_unchecked:<(?P<pad>[^>]+)> have event type caps event:.*?caps=\(GstCaps\)\"(?P<caps>(?:[^\"\\]|\\.)*)\""
)


@dataclass
class Record:
    kind: str                       # e.g. "element-latency", "buffer", "new-element"
    fields: Dict[str, Value]
    wall_ns: int                    # log timestamp (0:00:00.041343812 -> ns since process start)
    thread: str = ""


@dataclass
class CapsEvent:
    pad: str                        # "capsfilter0:sink"
    caps: str                       # unescaped caps string
    wall_ns: int


@dataclass
class ParseStats:
    lines: int = 0
    records: int = 0
    caps_events: int = 0
    format_decls: int = 0
    unparsed: int = 0


def parse_wall_ns(ts: str) -> int:
    h, m, s = ts.split(":")
    sec, frac = s.split(".")
    frac = (frac + "000000000")[:9]
    return ((int(h) * 60 + int(m)) * 60 + int(sec)) * 1_000_000_000 + int(frac)


def _coerce(typ: str, raw: str) -> Value:
    if raw.startswith('"') and raw.endswith('"'):
        return unescape_gst_string(raw[1:-1])
    if typ in ("guint64", "gint64", "uint", "int", "guint", "gint", "GstPadDirection", "GstBufferFlags"):
        try:
            return int(raw)
        except ValueError:
            return raw
    if typ == "boolean":
        return raw in ("1", "true", "TRUE")
    return raw


def unescape_gst_string(s: str) -> str:
    """Undo GstStructure string escaping: backslash-escaped chars."""
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            out.append(s[i + 1])
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def parse_line(line: str, stats: Optional[ParseStats] = None):
    """Return a Record, a CapsEvent, or None (format declarations and noise)."""
    if stats is not None:
        stats.lines += 1
    m = _HEAD.match(line.rstrip("\n"))
    if not m:
        if stats is not None:
            stats.unparsed += 1
        return None
    cat, rest = m.group("cat"), m.group("rest")
    wall_ns = parse_wall_ns(m.group("ts"))
    if cat == "GST_TRACER":
        if "gst_tracer_record_build_format" in rest:
            if stats is not None:
                stats.format_decls += 1
            return None
        if m.group("level") != "TRACE":
            return None                      # tracer registration chatter etc.
        r = _TRACER_REC.match(rest)
        if not r:
            if stats is not None:
                stats.unparsed += 1
            return None
        fields: Dict[str, Value] = {}
        for f in _FIELD.finditer(r.group("body")):
            fields[f.group("key")] = _coerce(f.group("type"), f.group("val").strip())
        if stats is not None:
            stats.records += 1
        return Record(kind=r.group("kind"), fields=fields, wall_ns=wall_ns, thread=m.group("thread"))
    if cat == "GST_EVENT":
        c = _CAPS_LINE.search(rest)
        if c:
            if stats is not None:
                stats.caps_events += 1
            return CapsEvent(pad=c.group("pad"), caps=unescape_gst_string(c.group("caps")), wall_ns=wall_ns)
        return None
    return None


def iter_records(lines, stats: Optional[ParseStats] = None):
    for line in lines:
        item = parse_line(line, stats)
        if item is not None:
            yield item
