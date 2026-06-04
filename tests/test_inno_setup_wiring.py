import unittest
import struct
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent
INNO_SETUP = PROJECT_ROOT / "installer" / "fixonce_setup.iss"
PYINSTALLER_SPEC = PROJECT_ROOT / "fixonce.spec"
ROOT_ICON = PROJECT_ROOT / "FixOnce.ico"


class TestInnoSetupWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inno_text = INNO_SETUP.read_text(encoding="utf-8")
        cls.inno_flat = cls.inno_text.replace("\r", "").replace("\n", " ")
        cls.spec_text = PYINSTALLER_SPEC.read_text(encoding="utf-8")

    def test_bootstrap_run_entry_waits_for_completion(self):
        self.assertIn('Parameters: "--bootstrap"', self.inno_text)
        bootstrap_lines = [
            line
            for line in self.inno_text.splitlines()
            if "--bootstrap" in line and line.strip().startswith("Filename:")
        ]
        self.assertEqual(len(bootstrap_lines), 1)
        self.assertIn("waituntilterminated", bootstrap_lines[0])
        self.assertIn("skipifdoesntexist", bootstrap_lines[0])
        self.assertNotIn("nowait", bootstrap_lines[0].lower())
        self.assertNotIn("postinstall", bootstrap_lines[0].lower())
        self.assertNotIn("Description:", bootstrap_lines[0])

    def test_no_minimized_hkcu_run_autostart(self):
        self.assertNotIn("--minimized", self.inno_text)
        self.assertNotIn("startupicon", self.inno_text)

    def test_legacy_run_key_is_not_created_on_install(self):
        registry_run_lines = [
            line
            for line in self.inno_text.splitlines()
            if "CurrentVersion\\Run" in line and "FixOnce" in line and line.strip().startswith("Root:")
        ]
        self.assertEqual(len(registry_run_lines), 1)
        self.assertIn("dontcreatekey", registry_run_lines[0])
        self.assertIn("uninsdeletevalue", registry_run_lines[0])

    def test_legacy_startup_shortcut_is_removed_on_install_and_uninstall(self):
        startup_delete_lines = [
            line
            for line in self.inno_text.splitlines()
            if "{userstartup}\\FixOnceServer.lnk" in line and line.strip().startswith("Type: files;")
        ]
        self.assertEqual(len(startup_delete_lines), 2)
        self.assertIn("[InstallDelete]", self.inno_text)
        self.assertIn("[UninstallDelete]", self.inno_text)

    def test_success_message_happens_after_install_phase(self):
        self.assertIn("ssDone", self.inno_text)
        self.assertIn("FixOnce is ready", self.inno_text)
        self.assertNotIn(
            "installed successfully",
            self.inno_text.lower().split("ssdone")[0],
        )

    def test_bootstrap_is_not_optional_postinstall_action(self):
        postinstall_runs = [
            line
            for line in self.inno_text.splitlines()
            if "postinstall" in line.lower() and "filename:" in line.lower()
        ]
        self.assertFalse(postinstall_runs)

    def test_windows_icon_is_multi_size_square_ico(self):
        data = ROOT_ICON.read_bytes()
        self.assertGreaterEqual(len(data), 6)
        reserved, icon_type, count = struct.unpack_from("<HHH", data, 0)
        self.assertEqual(reserved, 0)
        self.assertEqual(icon_type, 1)
        self.assertGreaterEqual(count, 4)
        self.assertGreaterEqual(len(data), 6 + (16 * count))

        sizes = set()
        for index in range(count):
            width_raw, height_raw = struct.unpack_from("<BB", data, 6 + (16 * index))
            width = 256 if width_raw == 0 else width_raw
            height = 256 if height_raw == 0 else height_raw
            self.assertEqual(width, height)
            sizes.add(width)

        self.assertTrue({16, 32, 48, 256}.issubset(sizes))

    def test_windows_icon_wiring_uses_root_icon(self):
        self.assertIn('icon=str(PROJECT_ROOT / "FixOnce.ico")', self.spec_text)
        self.assertIn('"FixOnce.ico"', self.spec_text)
        self.assertIn("SetupIconFile=..\\FixOnce.ico", self.inno_text)
        self.assertIn('Source: "..\\FixOnce.ico"; DestDir: "{app}"', self.inno_text)
        self.assertIn('IconFilename: "{app}\\FixOnce.ico"', self.inno_text)

    def test_installer_version_matches_app_version(self):
        version_file = PROJECT_ROOT / "src" / "version.py"
        version_text = version_file.read_text(encoding="utf-8")
        self.assertIn('__version__ = "1.0.12"', version_text)
        self.assertIn('#define MyAppVersion "1.0.12"', self.inno_text)


if __name__ == "__main__":
    unittest.main()
