"""The committed live.html must always equal a fresh build of panel/src (no drift),
must be self-contained (no external fetches - D8), and must inline every source file."""
import importlib.util
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("build_panel", ROOT / "tools" / "build_panel.py")
build_panel = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_panel)


class PanelBuild(unittest.TestCase):
    def test_committed_page_matches_a_fresh_build(self):
        built = build_panel.build(ROOT / "gst_profile" / "panel" / "src")
        committed = (ROOT / "gst_profile" / "panel" / "live.html").read_text(encoding="utf-8")
        self.assertEqual(committed, built,
                         "gst_profile/panel/live.html is stale - run python3 tools/build_panel.py")

    def test_page_is_self_contained(self):
        page = (ROOT / "gst_profile" / "panel" / "live.html").read_text(encoding="utf-8")
        self.assertNotRegex(page, r'(src|href)="https?://')
        self.assertNotIn("@import", page)

    def test_every_source_file_is_inlined(self):
        src = ROOT / "gst_profile" / "panel" / "src"
        template = (src / "panel.html").read_text(encoding="utf-8")
        markers = set(re.findall(r"/\*@inline ([\w.]+)\*/", template))
        files = {p.name for p in src.iterdir() if p.name != "panel.html"}
        self.assertEqual(markers, files)


if __name__ == "__main__":
    unittest.main()
