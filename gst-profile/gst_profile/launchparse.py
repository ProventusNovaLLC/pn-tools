"""Minimal gst-launch syntax parser -> Graph (static analysis, before anything runs).

Bare caps (`! video/x-raw,format=NV12 !`) become `capsfilterN` elements exactly as
gst-launch materialises them, so static and runtime graphs line up.
Supported: `elem prop=val ... ! elem ! caps,filter ! ...`, `name=` , tee/named
branches (`t. ! ...`), quoted values. Not supported in v1: parentheses/bins,
`elem.pad ! ` pad-specific links beyond `name.`; the parser records an
`unsupported` note instead of failing, and rules simply see less.
"""
import re
import shlex
from typing import List, Optional, Tuple

from .graph import Graph

_ELEMENT_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


class LaunchParseError(ValueError):
    pass


def parse_launch(launch: str, platform: str = "generic") -> Tuple[Graph, List[str]]:
    """Return (graph, notes). Element ids follow gst-launch numbering: factory + running index (nvvidconv0, nvvidconv1, ...)
    unless `name=` overrides."""
    g = Graph(platform=platform)
    notes: List[str] = []
    try:
        tokens = shlex.split(launch)
    except ValueError as e:
        raise LaunchParseError(str(e))
    counters = {}
    prev_pad: Optional[str] = None            # "element:src" awaiting a link
    pending_caps: Optional[str] = None
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "!":
            i += 1
            continue
        if tok in ("(", ")"):
            notes.append("bins/parentheses are not analysed statically")
            i += 1
            continue
        if tok.endswith(".") and _ELEMENT_NAME.match(tok[:-1] or "x") and tok[:-1] in g.elements:
            prev_pad = f"{tok[:-1]}:src"        # branch off a named element (tee)
            i += 1
            continue
        if "/" in tok and "=" not in tok.split(",")[0]:      # caps filter: video/x-raw,format=NV12
            # gst-launch materialises this as a capsfilter element (capsfilter0, capsfilter1, ... in parse order)
            n = counters.get("capsfilter", 0)
            counters["capsfilter"] = n + 1
            name = f"capsfilter{n}"
            el = g.add_element(name, factory="capsfilter")
            el.props["caps"] = tok
            el.pads.setdefault("sink", "sink"); el.pads.setdefault("src", "src")
            if prev_pad is not None:
                g.add_link(prev_pad, f"{name}:sink")
            pending_caps = tok                                 # applies to the link OUT of the capsfilter
            prev_pad = f"{name}:src"
            i += 1
            continue
        if "=" in tok and prev_pad is not None and prev_pad.split(":")[0] in g.elements and _looks_like_prop(tok):
            k, v = tok.split("=", 1)
            g.elements[prev_pad.split(":")[0]].props[k] = v
            i += 1
            continue
        # element factory
        factory = tok
        if not _ELEMENT_NAME.match(factory):
            notes.append(f"unrecognised token '{factory}' skipped")
            i += 1
            continue
        # collect props that follow this element
        props = {}
        j = i + 1
        while j < len(tokens) and tokens[j] not in ("!", "(", ")") and _looks_like_prop(tokens[j]) and not ("/" in tokens[j] and "=" not in tokens[j].split(",")[0]):
            k, v = tokens[j].split("=", 1)
            props[k] = v
            j += 1
        name = props.pop("name", None)
        if name is None:
            n = counters.get(factory, 0)
            counters[factory] = n + 1
            name = f"{factory}{n}"
        el = g.add_element(name, factory=factory, gtype="")
        el.props.update(props)
        el.pads.setdefault("sink", "sink"); el.pads.setdefault("src", "src")
        if prev_pad is not None:
            link = g.add_link(prev_pad, f"{name}:sink")
            if pending_caps:
                link.set_caps(pending_caps, platform)
                pending_caps = None
        prev_pad = f"{name}:src"
        i = j
    # sources have no sink pad, sinks no src pad; tidy for from_launch graphs
    for el in g.elements.values():
        if not g.upstream(el.id):
            el.pads.pop("sink", None)
        if not g.downstream(el.id):
            el.pads.pop("src", None)
    return g, notes


def _looks_like_prop(tok: str) -> bool:
    return "=" in tok and not tok.startswith("=") and _ELEMENT_NAME.match(tok.split("=", 1)[0].replace("-", "_")) is not None
