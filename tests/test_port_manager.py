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


class TestPortSelectionRegression(unittest.TestCase):
    """Regression tests for port selection behavior."""

    def test_stale_fallback_port_does_not_override_free_5000(self):
        """
        Regression: If config.json contains a stale fallback port (e.g. 5002),
        but 5000 is available, we should use 5000.
        """
        with tempfile.TemporaryDirectory(prefix="fixonce-port-") as temp_dir:
            temp_home = Path(temp_dir)
            config_dir = temp_home / ".fixonce"
            config_dir.mkdir(parents=True, exist_ok=True)

            # Simulate stale config with fallback port 5002 (not user-configured)
            (config_dir / "config.json").write_text(
                json.dumps({"port": 5002, "user": "tester"}),
                encoding="utf-8",
            )

            with patch("pathlib.Path.home", return_value=temp_home):
                # Mock port 5000 as available
                with patch.object(port_manager, "is_port_available", return_value=True):
                    port = port_manager.find_available_port()
                    self.assertEqual(port, 5000, "Should use 5000 when available, not stale 5002")

    def test_user_configured_port_is_respected_when_5000_busy(self):
        """
        If user explicitly configured a custom port and 5000 is busy,
        use the user's configured port.
        """
        with tempfile.TemporaryDirectory(prefix="fixonce-port-") as temp_dir:
            temp_home = Path(temp_dir)
            config_dir = temp_home / ".fixonce"
            config_dir.mkdir(parents=True, exist_ok=True)

            # User explicitly configured port 5005
            (config_dir / "config.json").write_text(
                json.dumps({"port": 5005, "user": "tester", "user_configured": True}),
                encoding="utf-8",
            )

            with patch("pathlib.Path.home", return_value=temp_home):
                def mock_port_available(port):
                    return port != 5000  # 5000 is busy

                with patch.object(port_manager, "is_port_available", side_effect=mock_port_available):
                    port = port_manager.find_available_port()
                    self.assertEqual(port, 5005, "Should use user-configured port when 5000 busy")

    def test_fallback_port_is_not_sticky(self):
        """
        Fallback ports should not be persisted as preferences.
        allocate_and_save_port should only save when using 5000.
        """
        with tempfile.TemporaryDirectory(prefix="fixonce-port-") as temp_dir:
            temp_home = Path(temp_dir)
            config_dir = temp_home / ".fixonce"
            config_dir.mkdir(parents=True, exist_ok=True)

            # Start with clean config
            (config_dir / "config.json").write_text(
                json.dumps({"user": "tester"}),
                encoding="utf-8",
            )

            with patch("pathlib.Path.home", return_value=temp_home):
                def mock_port_available(port):
                    return port != 5000  # 5000 is busy, will fallback

                with patch.object(port_manager, "is_port_available", side_effect=mock_port_available):
                    port = port_manager.allocate_and_save_port()
                    self.assertNotEqual(port, 5000, "Should fallback when 5000 busy")

                    # Check that fallback port was NOT saved
                    config = json.loads((config_dir / "config.json").read_text())
                    self.assertNotIn("port", config, "Fallback port should not be saved to config")

    def test_5000_is_saved_when_used(self):
        """When using port 5000, it should be saved to config."""
        with tempfile.TemporaryDirectory(prefix="fixonce-port-") as temp_dir:
            temp_home = Path(temp_dir)
            config_dir = temp_home / ".fixonce"
            config_dir.mkdir(parents=True, exist_ok=True)

            (config_dir / "config.json").write_text(
                json.dumps({"user": "tester"}),
                encoding="utf-8",
            )

            with patch("pathlib.Path.home", return_value=temp_home):
                with patch.object(port_manager, "is_port_available", return_value=True):
                    port = port_manager.allocate_and_save_port()
                    self.assertEqual(port, 5000)

                    config = json.loads((config_dir / "config.json").read_text())
                    self.assertEqual(config.get("port"), 5000, "Port 5000 should be saved")

    def test_clear_stale_port_preference(self):
        """clear_stale_port_preference removes non-user-configured ports."""
        with tempfile.TemporaryDirectory(prefix="fixonce-port-") as temp_dir:
            temp_home = Path(temp_dir)
            config_dir = temp_home / ".fixonce"
            config_dir.mkdir(parents=True, exist_ok=True)

            # Stale config with fallback port
            (config_dir / "config.json").write_text(
                json.dumps({"port": 5002, "user": "tester"}),
                encoding="utf-8",
            )

            with patch("pathlib.Path.home", return_value=temp_home):
                result = port_manager.clear_stale_port_preference()
                self.assertTrue(result, "Should return True when config modified")

                config = json.loads((config_dir / "config.json").read_text())
                self.assertNotIn("port", config, "Stale port should be removed")

    def test_clear_stale_preserves_user_configured(self):
        """clear_stale_port_preference preserves user-configured ports."""
        with tempfile.TemporaryDirectory(prefix="fixonce-port-") as temp_dir:
            temp_home = Path(temp_dir)
            config_dir = temp_home / ".fixonce"
            config_dir.mkdir(parents=True, exist_ok=True)

            # User-configured port
            (config_dir / "config.json").write_text(
                json.dumps({"port": 5005, "user": "tester", "user_configured": True}),
                encoding="utf-8",
            )

            with patch("pathlib.Path.home", return_value=temp_home):
                result = port_manager.clear_stale_port_preference()
                self.assertFalse(result, "Should not modify user-configured")

                config = json.loads((config_dir / "config.json").read_text())
                self.assertEqual(config.get("port"), 5005, "User port preserved")
                self.assertTrue(config.get("user_configured"), "Flag preserved")


if __name__ == "__main__":
    unittest.main()
