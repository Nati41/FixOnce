import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent
EXTENSION_DIR = PROJECT_ROOT / "extension"


class TestExtensionClearOnSuccess(unittest.TestCase):
    def test_loaded_injected_script_emits_page_load_success_through_bridge(self):
        manifest = json.loads((EXTENSION_DIR / "manifest.json").read_text(encoding="utf-8"))
        scripts = [
            script
            for entry in manifest["content_scripts"]
            for script in entry.get("js", [])
        ]

        self.assertIn("injected.js", scripts)
        self.assertIn("bridge.js", scripts)

        injected = (EXTENSION_DIR / "injected.js").read_text(encoding="utf-8")
        bridge = (EXTENSION_DIR / "bridge.js").read_text(encoding="utf-8")
        background = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")

        self.assertIn('source: "FIXONCE"', injected)
        self.assertIn('type: "page_load_success"', injected)
        self.assertIn("window.postMessage", injected)
        self.assertNotIn("http://localhost:5000/log", injected)

        self.assertIn("PAGE_LOAD_SUCCESS", bridge)
        self.assertIn("PAGE_LOAD_SUCCESS", background)
        self.assertIn("/api/page-load-success", background)
        self.assertIn("discoverServer().finally", background)


if __name__ == "__main__":
    unittest.main()
