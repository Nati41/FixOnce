import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent


class TestReleaseConsistency(unittest.TestCase):
    def test_landing_page_mirror_is_synchronized(self):
        docs = (PROJECT_ROOT / "docs" / "index.html").read_text(encoding="utf-8")
        website = (PROJECT_ROOT / "website" / "index.html").read_text(encoding="utf-8")

        self.assertEqual(docs, website)

    def test_landing_page_has_no_smart_quote_javascript_delimiters(self):
        html = (PROJECT_ROOT / "docs" / "index.html").read_text(encoding="utf-8")
        script_blocks = re.findall(r"<script\b[^>]*>(.*?)</script>", html, flags=re.DOTALL | re.IGNORECASE)

        self.assertTrue(script_blocks)
        for script in script_blocks:
            self.assertNotRegex(script, r"=\s*[“”]")
            self.assertNotRegex(script, r"\(\s*[“”]")
        self.assertIn("Open Anyway", html)
        self.assertIn("Python 3.10+", html)
        self.assertNotIn("Control-click", html)
        self.assertNotIn("right-click", html.lower())

    def test_macos_release_asset_name_is_consistent(self):
        expected = "FixOnce-mac.dmg"
        relevant_files = [
            PROJECT_ROOT / "README.md",
            PROJECT_ROOT / "RELEASE.md",
            PROJECT_ROOT / "installer" / "macos" / "build_installer.sh",
            PROJECT_ROOT / "installer" / "macos" / "build_dmg.sh",
            PROJECT_ROOT / ".github" / "workflows" / "build-release.yml",
        ]

        for path in relevant_files:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(PROJECT_ROOT)):
                self.assertIn("FixOnce-mac", text)
                self.assertNotIn("FixOnce-mac-beta", text)
        self.assertIn(expected, (PROJECT_ROOT / "RELEASE.md").read_text(encoding="utf-8"))
