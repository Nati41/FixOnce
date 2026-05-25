import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import core.port_manager as port_manager


class TestPortManager(unittest.TestCase):
    def test_get_preferred_port_ignores_corrupted_string_values(self):
        with tempfile.TemporaryDirectory(prefix="fixonce-port-manager-") as temp_dir:
            temp_home = Path(temp_dir)
            config_dir = temp_home / ".fixonce"
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "config.json").write_text(
                json.dumps({"port": "Opening FixOnce...\n5001", "user": "tester"}),
                encoding="utf-8",
            )

            with patch("pathlib.Path.home", return_value=temp_home):
                self.assertIsNone(port_manager.get_preferred_port())


if __name__ == "__main__":
    unittest.main()
