from pathlib import Path
import tempfile
import unittest

from scripts import windows_packaging_audit


class WindowsPackagingAuditTest(unittest.TestCase):
    def test_requires_fastmcp_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = Path(temp_dir)
            for file_name in windows_packaging_audit.REQUIRED_ROOT_FILES:
                (package_dir / file_name).write_text("ok", encoding="utf-8")

            report_path = package_dir / "packaging_audit.txt"
            result = windows_packaging_audit.main([__file__, str(package_dir), str(report_path)])

        self.assertEqual(result, 1)

    def test_accepts_fastmcp_metadata_under_internal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = Path(temp_dir)
            for file_name in windows_packaging_audit.REQUIRED_ROOT_FILES:
                (package_dir / file_name).write_text("ok", encoding="utf-8")
            metadata_dir = package_dir / "_internal" / "fastmcp-2.0.0.dist-info"
            metadata_dir.mkdir(parents=True)
            (metadata_dir / "METADATA").write_text("Name: fastmcp\n", encoding="utf-8")

            report_path = package_dir / "packaging_audit.txt"
            result = windows_packaging_audit.main([__file__, str(package_dir), str(report_path)])

        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
