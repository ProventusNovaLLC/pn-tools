"""Caps string helpers: parse GstCaps text into media type / features / fields,
and classify the memory domain of a link."""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

_TYPE_RE = re.compile(r"^\s*(?P<media>[A-Za-z0-9_+.-]+/[A-Za-z0-9_+.-]+)(?:\((?P<features>[^)]*)\))?")
_FIELD_RE = re.compile(r",\s*(?P<key>[A-Za-z0-9_-]+)=(?:\((?P<type>[A-Za-z0-9]+)\))?(?P<val>\{[^}]*\}|\[[^\]]*\]|\"(?:[^\"\\]|\\.)*\"|[^,]*)")


@dataclass
class Caps:
    media: str = ""                       # "video/x-raw"
    features: List[str] = field(default_factory=list)   # ["memory:NVMM"]
    fields: Dict[str, str] = field(default_factory=dict) # {"format": "NV12", "width": "1920", ...}
    raw: str = ""

    @property
    def format(self) -> Optional[str]:
        return self.fields.get("format")

    def size(self):
        try:
            return int(self.fields["width"]), int(self.fields["height"])
        except (KeyError, ValueError):
            return None

    def framerate(self) -> Optional[float]:
        fr = self.fields.get("framerate")
        if not fr:
            return None
        try:
            n, d = fr.split("/")
            return int(n) / int(d) if int(d) else None
        except ValueError:
            return None


def parse_caps(text: str) -> Caps:
    """Parse the serialized form ('video/x-raw(memory:NVMM), format=(string)NV12, width=(int)1920')
    or the dot-dump pretty form ('video/x-raw(memory:NVMM)\\l  format: NV12\\l  width: 1920\\l')."""
    text = text.strip()
    if text in ("ANY", "EMPTY", "NULL", ""):
        return Caps(media=text or "EMPTY", raw=text)
    if "\\l" in text or "\n" in text:
        return _parse_pretty(text)
    m = _TYPE_RE.match(text)
    if not m:
        return Caps(raw=text)
    caps = Caps(media=m.group("media"), raw=text)
    if m.group("features"):
        caps.features = [f.strip() for f in m.group("features").split(",") if f.strip()]
    for f in _FIELD_RE.finditer(text[m.end():]):
        val = f.group("val").strip()
        if val.startswith('"') and val.endswith('"'):
            val = val[1:-1]
        caps.fields[f.group("key")] = val
    return caps


def _parse_pretty(text: str) -> Caps:
    lines = [l.strip() for l in re.split(r"\\l|\n", text) if l.strip()]
    if not lines:
        return Caps(raw=text)
    m = _TYPE_RE.match(lines[0])
    caps = Caps(media=m.group("media") if m else lines[0], raw=text)
    if m and m.group("features"):
        caps.features = [f.strip() for f in m.group("features").split(",") if f.strip()]
    for l in lines[1:]:
        if ":" in l:
            k, v = l.split(":", 1)
            caps.fields[k.strip()] = v.strip()
    return caps


def memory_domain(caps: Optional[Caps], platform: str = "generic") -> str:
    """'nvmm' | 'dmabuf' | 'sysmem' | 'unknown'."""
    if caps is None or not caps.media or caps.media in ("ANY", "EMPTY", "NULL"):
        return "unknown"
    feats = [f.lower() for f in caps.features]
    if any("memory:nvmm" in f for f in feats):
        return "nvmm"
    if any("memory:dmabuf" in f for f in feats):
        return "dmabuf"
    if any(f.startswith("memory:") and "systemmemory" not in f for f in feats):
        return "unknown"          # some other exotic memory feature (e.g. memory:CUDAMemory); v1 does not classify
    return "sysmem"
