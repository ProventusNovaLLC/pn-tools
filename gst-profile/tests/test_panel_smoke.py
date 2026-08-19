"""Headless-browser smoke: a report built from each fixture renders every tab with
zero console errors. Dev-machine only (needs google-chrome/chromium); boards never
run this - it skips cleanly when no browser is present."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from gst_profile.cli import main as cli_main

ROOT = Path(__file__).resolve().parent.parent
CHROME = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
TRAP = ("<script>window.__errors=[];window.onerror=function(m,s,l){window.__errors.push(m+' @'+l);};"
        "setTimeout(function(){document.title=window.__errors.length?"
        "('PANEL-ERR: '+window.__errors.join(' | ')):'PANEL-OK';},1200);</script>")


def render(fixture, tab):
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "r.html"
        rc = cli_main(["report", str(ROOT / "tests" / "fixtures" / fixture), "-o", str(out)])
        if rc != 0:
            raise AssertionError(f"report failed for {fixture}")
        html = out.read_text(encoding="utf-8").replace("<script>", TRAP + "<script>", 1)
        out.write_text(html, encoding="utf-8")
        p = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--window-size=1440,900",
                            "--virtual-time-budget=4000", "--dump-dom", f"file://{out}#tab={tab}"],
                           capture_output=True, text=True, timeout=90)
        return p.stdout


@unittest.skipUnless(CHROME, "no chrome/chromium (panel smoke is dev-machine only)")
class PanelSmoke(unittest.TestCase):
    def test_zc_fixture_renders_every_tab(self):
        for tab in ("pipeline", "timeline", "system", "analysis"):
            dom = render("jetson-zc-break.json", tab)
            self.assertIn("PANEL-OK", dom, f"tab {tab}: …{dom[-400:]}")

    def test_other_fixtures_render(self):
        for fixture in ("software-healthy.json", "jetson-hw-loopback.json"):
            dom = render(fixture, "pipeline")
            self.assertIn("PANEL-OK", dom, f"{fixture}: …{dom[-400:]}")


if __name__ == "__main__":
    unittest.main()
