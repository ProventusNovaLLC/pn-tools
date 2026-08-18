"""Parse a GStreamer GST_DEBUG_DUMP_DOT_DIR file into elements / pads / links.

Format facts (GStreamer 1.24, unchanged since 1.x):
  subgraph cluster_<name>_<ptr> {  label="GstType\\nname\\n[state]\\nprop=value\\n..."  ... }
  pad nodes:  <name>_<ptr>_<pad>_<ptr> [ ... label="src\\n[>][bfb][T]" ]
  links:      <srcnode> -> <sinknode> [label="video/x-raw(memory:NVMM)\\l  format: NV12\\l ..."]
  intra-element helper edges carry style="invis" and are skipped.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

_CLUSTER = re.compile(r"^\s*subgraph\s+cluster_(?P<id>\S+)\s*\{")
_LABEL = re.compile(r'^\s*label="(?P<label>(?:[^"\\]|\\.)*)"')
_PADNODE = re.compile(r'^\s*(?P<node>[A-Za-z0-9_]+_0x[0-9a-f]+_(?P<pad>[A-Za-z0-9_%]+)_0x[0-9a-f]+)\s*\[(?P<attrs>.*)\];\s*$')
_EDGE = re.compile(r'^\s*(?P<src>[A-Za-z0-9_]+)\s*->\s*(?P<dst>[A-Za-z0-9_]+)\s*(?:\[(?P<attrs>.*)\])?;?\s*$')
_LABEL_ATTR = re.compile(r'label="(?P<label>(?:[^"\\]|\\.)*)"')


@dataclass
class DotElement:
    name: str
    gtype: str
    state: str = ""
    props: Dict[str, str] = field(default_factory=dict)
    parent: Optional[str] = None          # enclosing bin name, None for top-level pipeline
    is_bin: bool = False


@dataclass
class DotPad:
    node: str
    element: str
    name: str
    direction: str                        # "src" | "sink"


@dataclass
class DotLink:
    src_pad: str                          # "element:pad"
    sink_pad: str
    caps: str = ""                        # pretty caps text with \l separators (parse with capsutil)


@dataclass
class DotGraph:
    elements: List[DotElement] = field(default_factory=list)
    pads: Dict[str, DotPad] = field(default_factory=dict)      # node id -> pad
    links: List[DotLink] = field(default_factory=list)
    pipeline_name: str = ""


def _split_label(label: str) -> List[str]:
    return [p for p in label.replace("\\n", "\n").split("\n")]


def parse_dot(text: str) -> DotGraph:
    g = DotGraph()
    stack: List[Tuple[str, Optional[DotElement]]] = []     # (cluster id, element or None for pad clusters)
    raw_edges: List[Tuple[str, str, str]] = []             # (src node, dst node, caps label) resolved after the pass
    lines = text.splitlines()
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        m = _CLUSTER.match(line)
        if m:
            cid = m.group("id")
            # element clusters have a label on the following lines; pad clusters end in _sink/_src and have label=""
            if cid.endswith("_sink") or cid.endswith("_src"):
                stack.append((cid, None))
            else:
                stack.append((cid, DotElement(name="", gtype="")))
            continue
        if s.startswith("}"):
            if stack:
                stack.pop()
            continue
        if line.lstrip().startswith("label=") and stack and stack[-1][1] is not None and stack[-1][1].name == "":
            lm = _LABEL.match(line)
            if lm:
                parts = _split_label(lm.group("label"))
                el = stack[-1][1]
                el.gtype = parts[0].strip("<>") if parts else ""
                el.name = parts[1] if len(parts) > 1 else stack[-1][0]
                el.state = parts[2].strip("[]") if len(parts) > 2 else ""
                for p in parts[3:]:
                    if "=" in p:
                        k, v = p.split("=", 1)
                        el.props[k.strip()] = v.strip()
                el.parent = next((e.name for _, e in reversed(stack[:-1]) if e is not None and e.name), None)
                el.is_bin = "Bin" in el.gtype or "Pipeline" in el.gtype
                g.elements.append(el)
            continue
        if line.lstrip().startswith("label=") and not stack:
            lm = _LABEL.match(line)
            if lm and not g.pipeline_name:
                parts = _split_label(lm.group("label"))
                g.pipeline_name = parts[1] if len(parts) > 1 else ""
            continue
        pm = _PADNODE.match(line)
        if pm and "->" not in line:
            owner = next((e for _, e in reversed(stack) if e is not None and e.name), None)
            if owner is None:
                continue
            attrs = pm.group("attrs")
            la = _LABEL_ATTR.search(attrs)
            padname = _split_label(la.group("label"))[0] if la else pm.group("pad")
            g.pads[pm.group("node")] = DotPad(node=pm.group("node"), element=owner.name, name=padname,
                                              direction="src" if 'fillcolor="#ffaaaa"' in attrs else "sink")
            continue
        em = _EDGE.match(line)
        if em:
            attrs = em.group("attrs") or ""
            if 'style="invis"' in attrs or "style=dashed" in attrs or 'style="dashed"' in attrs:
                continue
            la = _LABEL_ATTR.search(attrs)
            raw_edges.append((em.group("src"), em.group("dst"), la.group("label") if la else ""))
    for src_node, dst_node, caps in raw_edges:          # second pass: pads may be declared after the edge
        src, dst = g.pads.get(src_node), g.pads.get(dst_node)
        if src and dst:
            # a ( ... ) bin's ghost pad and its internal proxypad are not the real element on the other
            # side of the boundary; emitting them would create a phantom link. Full collapse onto the
            # logical link is deferred to Plan 2 — for now just don't emit the phantom.
            if src.name.startswith(("ghost", "proxypad")) or dst.name.startswith(("ghost", "proxypad")):
                continue
            g.links.append(DotLink(src_pad=f"{src.element}:{src.name}", sink_pad=f"{dst.element}:{dst.name}", caps=caps))
    return g
