import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys


PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import install
import core.first_launch as first_launch


class TestWindowsStartupFlow(unittest.TestCase):
    def test_windows_launcher_command_prefers_packaged_exe(self):
        with tempfile.TemporaryDirectory(prefix="fixonce-win-launcher-") as temp_dir:
            temp_path = Path(temp_dir)
            exe_path = temp_path / "FixOnce.exe"
            exe_path.write_text("stub", encoding="utf-8")

            command, working_dir = install.get_windows_launcher_command(temp_path, server_mode=True)

            self.assertEqual(command, [str(exe_path), "--server"])
            self.assertEqual(working_dir, temp_path)

    def test_windows_launcher_command_falls_back_to_app_launcher(self):
        with tempfile.TemporaryDirectory(prefix="fixonce-win-launcher-") as temp_dir:
            temp_path = Path(temp_dir)
            launcher_path = temp_path / "scripts" / "app_launcher.py"
            launcher_path.parent.mkdir(parents=True, exist_ok=True)
            launcher_path.write_text("print('stub')", encoding="utf-8")

            command, working_dir = install.get_windows_launcher_command(temp_path, server_mode=True)

            self.assertEqual(command[1:], [str(launcher_path), "--server"])
            self.assertEqual(working_dir, temp_path)

    def test_cross_platform_launcher_command_routes_through_app_launcher(self):
        with tempfile.TemporaryDirectory(prefix="fixonce-launcher-") as temp_dir:
            temp_path = Path(temp_dir)
            launcher_path = temp_path / "scripts" / "app_launcher.py"
            launcher_path.parent.mkdir(parents=True, exist_ok=True)
            launcher_path.write_text("print('stub')", encoding="utf-8")

            with patch.object(install, "get_platform", return_value="mac"):
                command, working_dir = install.get_launcher_command(temp_path, server_mode=True)

            self.assertEqual(command, [sys.executable, str(launcher_path), "--server"])
            self.assertEqual(working_dir, temp_path)

    def test_windows_detached_creationflags_include_new_process_group(self):
        with patch.object(install, "get_platform", return_value="windows"), \
             patch.object(install.subprocess, "DETACHED_PROCESS", 0x8, create=True), \
             patch.object(install.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, create=True), \
             patch.object(install.subprocess, "CREATE_NO_WINDOW", 0x8000000, create=True):
            self.assertEqual(install.get_detached_creationflags(), 0x8000208)

    def test_first_launch_uses_install_templates_and_user_data_dir(self):
        with tempfile.TemporaryDirectory(prefix="fixonce-first-launch-") as temp_dir:
            temp_path = Path(temp_dir)
            install_data = temp_path / "install_data"
            user_data = temp_path / "user_data"
            install_data.mkdir(parents=True, exist_ok=True)
            user_data.mkdir(parents=True, exist_ok=True)

            for name in [
                "active_project.template.json",
                "session_registry.template.json",
                "activity_log.template.json",
                "project_memory.template.json",
            ]:
                (install_data / name).write_text("{}", encoding="utf-8")

            with patch.object(first_launch, "DATA_DIR", user_data), patch.object(first_launch, "INSTALL_DATA_DIR", install_data):
                initialized = first_launch.initialize_data_files()

            self.assertIn("active_project.json", initialized)
            self.assertTrue((user_data / "active_project.json").exists())
            self.assertTrue((user_data / "session_registry.json").exists())
            self.assertTrue((user_data / "activity_log.json").exists())
            self.assertTrue((user_data / "project_memory.json").exists())


if __name__ == "__main__":
    unittest.main()
