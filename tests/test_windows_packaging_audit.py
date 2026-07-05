from pathlib import Path
import tempfile
import unittest

from scripts import windows_packaging_audit


PROJECT_ROOT = Path(__file__).parent.parent
WINDOWS_ICON = PROJECT_ROOT / "assets" / "FixOnce.ico"


def write_required_root_files(package_dir: Path) -> None:
    for file_name in windows_packaging_audit.REQUIRED_ROOT_FILES:
        path = package_dir / file_name
        if file_name == "FixOnce.ico":
            path.write_bytes(WINDOWS_ICON.read_bytes())
        else:
            path.write_text("ok", encoding="utf-8")


class WindowsPackagingAuditTest(unittest.TestCase):
    def test_requires_fastmcp_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = Path(temp_dir)
            write_required_root_files(package_dir)

            report_path = package_dir / "packaging_audit.txt"
            result = windows_packaging_audit.main([__file__, str(package_dir), str(report_path)])

        self.assertEqual(result, 1)

    def test_accepts_fastmcp_metadata_under_internal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = Path(temp_dir)
            write_required_root_files(package_dir)
            metadata_dir = package_dir / "_internal" / "fastmcp-2.0.0.dist-info"
            metadata_dir.mkdir(parents=True)
            (metadata_dir / "METADATA").write_text("Name: fastmcp\n", encoding="utf-8")

            report_path = package_dir / "packaging_audit.txt"
            result = windows_packaging_audit.main([__file__, str(package_dir), str(report_path)])

        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
