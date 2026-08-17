"""Pipeline graph model shared by every source (stats tracer, dot dump, launch string).

Element ids are GStreamer element names (unique within a pipeline). Link ids are
"srcelement:srcpad->sinkelement:sinkpad".
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .capsutil import parse_caps, memory_domain
from . import dotparse

# nv*/omx* = NVIDIA (nvarguscamerasrc, nvvidconv, nvv4l2h264enc, omxh264enc on JP4); mtk*/neuron* = MediaTek.
# v4l2 codec/convert elements are the MediaTek hardware path on Genio but generic elsewhere:
_MTK_V4L2 = ("v4l2h264enc", "v4l2h265enc", "v4l2h264dec", "v4l2h265dec", "v4l2convert", "v4l2jpegdec", "v4l2jpegenc")


def vendor_of(factory: str, platform: str = "generic") -> str:
    f = (factory or "").lower()
    if f.startswith("nv") or f.startswith("omx"):
        return "nvidia"
    if f.startswith("mtk") or f.startswith("neuron"):
        return "mediatek"
    if platform == "mediatek" and f in _MTK_V4L2:
        return "mediatek"
    return "generic"


@dataclass
class Element:
    id: str                                   # instance name, e.g. "nvvidconv0"
    factory: str = ""                         # "nvvidconv"; empty when only the GType is known
    gtype: str = ""                           # "GstNvVidConv"
    vendor: str = "generic"
    klass: str = ""                           # from gst-inspect if available
    props: Dict[str, str] = field(default_factory=dict)
    bin: Optional[str] = None
    is_bin: bool = False
    pads: Dict[str, str] = field(default_factory=dict)      # pad name -> "src" | "sink"


@dataclass
class Link:
    id: str
    src: str                                  # "element:pad"
    sink: str
    caps: str = ""                            # serialized caps as seen
    memory: str = "unknown"                   # nvmm | dmabuf | sysmem | unknown
    format: Optional[str] = None
    media: str = ""

    def set_caps(self, caps_text: str, platform: str = "generic"):
        c = parse_caps(caps_text)
        self.caps = caps_text.replace("\\l", " ").strip() if "\\l" in caps_text else caps_text
        self.memory = memory_domain(c, platform)
        self.format = c.format
        self.media = c.media


@dataclass
class Graph:
    platform: str = "generic"
    elements: Dict[str, Element] = field(default_factory=dict)
    links: Dict[str, Link] = field(default_factory=dict)
    pipeline: str = ""
    # stats-tracer bookkeeping (index -> name); not serialized
    _el_ix: Dict[int, str] = field(default_factory=dict, repr=False)
    _pad_ix: Dict[int, str] = field(default_factory=dict, repr=False)   # pad ix -> "element:pad"
    _pad_caps: Dict[str, str] = field(default_factory=dict, repr=False) # sink pad -> caps seen before its link existed

    # ---- construction -------------------------------------------------
    def add_element(self, name: str, gtype: str = "", factory: str = "", is_bin: bool = False, parent: Optional[str] = None) -> Element:
        el = self.elements.get(name)
        if el is None:
            el = Element(id=name, gtype=gtype, factory=factory or factory_from_gtype(gtype), is_bin=is_bin, bin=parent)
            el.vendor = vendor_of(el.factory or el.gtype, self.platform)
            self.elements[name] = el
        else:
            if gtype and not el.gtype:
                el.gtype = gtype
            if factory and not el.factory:
                el.factory = factory
            if not el.factory and el.gtype:
                el.factory = factory_from_gtype(el.gtype)
            el.vendor = vendor_of(el.factory or el.gtype, self.platform)
            el.is_bin = el.is_bin or is_bin
            el.bin = el.bin or parent
        return el

    def add_link(self, src: str, sink: str, caps: str = "") -> Link:
        lid = f"{src}->{sink}"
        link = self.links.get(lid)
        if link is None:
            link = Link(id=lid, src=src, sink=sink)
            self.links[lid] = link
            se, sp = src.split(":", 1)
            ke, kp = sink.split(":", 1)
            self.add_element(se).pads.setdefault(sp, "src")
            self.add_element(ke).pads.setdefault(kp, "sink")
            if not caps and sink in self._pad_caps:
                link.set_caps(self._pad_caps[sink], self.platform)
        if caps:
            link.set_caps(caps, self.platform)
        return link

    def set_pad_caps(self, sink_pad: str, caps: str) -> bool:
        """Caps event seen on a sink pad ("element:pad") -> apply to the link feeding it
        (now, or when that link appears — negotiation happens before the first buffer)."""
        self._pad_caps[sink_pad] = caps
        for link in self.links.values():
            if link.sink == sink_pad:
                link.set_caps(caps, self.platform)
                return True
        return False

    # ---- feed from tracer records ------------------------------------
    def ingest_record(self, rec) -> bool:
        """Consume a stats-tracer Record. Returns True if the topology changed."""
        f = rec.fields
        if rec.kind == "new-element":
            self._el_ix[int(f["ix"])] = f["name"]
            self.add_element(f["name"], gtype=str(f.get("type", "")), is_bin=bool(f.get("is-bin", False)))
            if f.get("is-bin") and not self.pipeline and "Pipeline" in str(f.get("type", "")):
                self.pipeline = f["name"]
            return True
        if rec.kind == "new-pad":
            owner = self._el_ix.get(int(f["parent-ix"]))
            if owner is None:
                return False
            self._pad_ix[int(f["ix"])] = f"{owner}:{f['name']}"
            self.elements[owner].pads[f["name"]] = "src" if int(f.get("pad-direction", 0)) == 1 else "sink"
            return False
        if rec.kind == "buffer":
            a = self._pad_ix.get(int(f.get("pad-ix", -1)))
            b = self._pad_ix.get(int(f.get("peer-pad-ix", -1)))
            if not a or not b:
                return False
            el = self.elements.get(a.split(":")[0])
            if el and el.pads.get(a.split(":")[1]) == "sink":           # record is from the receiving side; flip
                src, sink = b, a
            else:
                src, sink = a, b
            if f"{src}->{sink}" in self.links:
                return False
            self.add_link(src, sink)
            return True
        return False

    def link_for_stats_buffer(self, rec) -> Optional[str]:
        f = rec.fields
        a = self._pad_ix.get(int(f.get("pad-ix", -1)))
        b = self._pad_ix.get(int(f.get("peer-pad-ix", -1)))
        if not a or not b:
            return None
        return f"{a}->{b}" if f"{a}->{b}" in self.links else (f"{b}->{a}" if f"{b}->{a}" in self.links else None)

    # ---- feed from dot dump ------------------------------------------
    def ingest_dot(self, text: str) -> bool:
        d = dotparse.parse_dot(text)
        changed = False
        if d.pipeline_name and not self.pipeline:
            self.pipeline = d.pipeline_name
        for de in d.elements:
            el = self.add_element(de.name, gtype=de.gtype, is_bin=de.is_bin, parent=de.parent)
            for k, v in de.props.items():
                if k not in el.props:
                    el.props[k] = v
        for dl in d.links:
            before = dl.src_pad + "->" + dl.sink_pad in self.links
            self.add_link(dl.src_pad, dl.sink_pad, caps=dl.caps)
            changed = changed or not before
        return changed

    # ---- queries -----------------------------------------------------
    def downstream(self, element: str) -> List[str]:
        return [l.sink.split(":")[0] for l in self.links.values() if l.src.split(":")[0] == element]

    def upstream(self, element: str) -> List[str]:
        return [l.src.split(":")[0] for l in self.links.values() if l.sink.split(":")[0] == element]

    def sources(self) -> List[str]:
        return [e.id for e in self.elements.values() if not e.is_bin and not self.upstream(e.id) and self.downstream(e.id)]

    def sinks(self) -> List[str]:
        return [e.id for e in self.elements.values() if not e.is_bin and self.upstream(e.id) and not self.downstream(e.id)]

    def to_dict(self) -> dict:
        return {
            "pipeline": self.pipeline,
            "elements": [
                {"id": e.id, "factory": e.factory, "gtype": e.gtype, "vendor": e.vendor, "klass": e.klass,
                 "props": e.props, "bin": e.bin, "is_bin": e.is_bin, "pads": e.pads}
                for e in self.elements.values()
            ],
            "links": [
                {"id": l.id, "src": l.src, "sink": l.sink, "caps": l.caps, "memory": l.memory, "format": l.format, "media": l.media}
                for l in self.links.values()
            ],
        }

    @classmethod
    def from_dict(cls, d: dict, platform: str = "generic") -> "Graph":
        g = cls(platform=platform, pipeline=d.get("pipeline", ""))
        for e in d.get("elements", []):
            el = g.add_element(e["id"], gtype=e.get("gtype", ""), factory=e.get("factory", ""), is_bin=e.get("is_bin", False), parent=e.get("bin"))
            el.props = dict(e.get("props", {})); el.klass = e.get("klass", ""); el.pads = dict(e.get("pads", {}))
        for l in d.get("links", []):
            link = g.add_link(l["src"], l["sink"])
            link.caps, link.memory, link.format, link.media = l.get("caps", ""), l.get("memory", "unknown"), l.get("format"), l.get("media", "")
        return g


def factory_from_gtype(gtype: str) -> str:
    """Best-effort GType -> factory name ('GstVideoConvert' -> 'videoconvert', 'GstNvVidConv' -> 'nvvidconv').
    Exact mapping needs gst-inspect; this is the fallback used until preflight metadata is applied."""
    g = gtype or ""
    if g.startswith("Gst"):
        g = g[3:]
    return g.lower()
