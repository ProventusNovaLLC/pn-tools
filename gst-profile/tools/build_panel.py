#!/usr/bin/env python3
"""Build the single-file panel: inline panel.css and the JS sources into panel.html
at the /*@inline name*/ markers, writing gst_profile/panel/live.html (the file the
server serves and `report` embeds). Stdlib only; deterministic output.

Usage: python3 tools/build_panel.py            (from gst-profile/)
       python3 tools/build_panel.py <src_dir> <dest_file>
"""
import re
import sys
from pathlib import Path

BANNER = "<!-- built by tools/build_panel.py - edit gst_profile/panel/src/, not this file -->\n"


def build(src_dir: Path) -> str:
    template = (src_dir / "panel.html").read_text(encoding="utf-8")

    def inline(m):
        name = m.group(1)
        body = (src_dir / name).read_text(encoding="utf-8").rstrip("\n")
        if name.endswith(".js") and "</script" in body.lower():
            raise SystemExit(f"{name}: contains '</script' - it would break out of the inline script tag")
        return body

    out, n = re.subn(r"/\*@inline ([\w.]+)\*/", inline, template)
    if n == 0:
        raise SystemExit("no /*@inline*/ markers found in panel.html")
    if re.search(r"/\*@inline", out):
        raise SystemExit("unresolved @inline marker remains after build")
    return out.replace("<!doctype html>", "<!doctype html>\n" + BANNER, 1)


def main():
    root = Path(__file__).resolve().parent.parent / "gst_profile" / "panel"
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "src"
    dest = Path(sys.argv[2]) if len(sys.argv) > 2 else root / "live.html"
    dest.write_text(build(src), encoding="utf-8")
    print(f"built {dest} ({dest.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
