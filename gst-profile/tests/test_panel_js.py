"""Panel logic tests run under node's built-in test runner. Dev-machine only:
node is never required on a target board, so this module skips without it."""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(shutil.which("node"), "node not installed (panel JS tests are dev-machine only)")
class PanelJs(unittest.TestCase):
    def test_node_suite_is_green(self):
        p = subprocess.run(["node", "--test", str(ROOT / "tests" / "panel")],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()
