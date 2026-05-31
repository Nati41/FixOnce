import builtins
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


import config
import server as server_module


class TestHealthEncoding(unittest.TestCase):
    def test_health_active_project_reads_hebrew_utf8_on_windows_like_locale(self):
        with tempfile.TemporaryDirectory(prefix="fixonce-health-encoding-") as temp_dir:
            data_dir = Path(temp_dir)
            projects_dir = data_dir / "projects_v2"
            projects_dir.mkdir(parents=True)

            project_id = "פרויקט_123"
            working_dir = r"C:\Users\nati3\פרויקט בדיקה"
            active_file = data_dir / "active_project.json"
            project_file = projects_dir / f"{project_id}.json"

            active_file.write_text(json.dumps({
                "active_id": project_id,
                "working_dir": working_dir,
            }, ensure_ascii=False), encoding="utf-8")
            project_file.write_text(json.dumps({
                "project_info": {
                    "name": "פרויקט בדיקה",
                    "working_dir": working_dir,
                }
            }, ensure_ascii=False), encoding="utf-8")

            guarded_paths = {str(active_file), str(project_file)}
            real_open = builtins.open

            def windows_charmap_guard(file, mode="r", *args, **kwargs):
                path = str(file)
                if "r" in mode and path in guarded_paths and kwargs.get("encoding") is None:
                    raise UnicodeDecodeError("charmap", b"\x9e", 0, 1, "character maps to <undefined>")
                return real_open(file, mode, *args, **kwargs)

            with patch.object(config, "DATA_DIR", data_dir), \
                 patch.object(config, "USER_DATA_DIR", data_dir), \
                 patch("builtins.open", side_effect=windows_charmap_guard):
                response = server_module.flask_app.test_client().get("/api/health")

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            active = payload["checks"]["active_project"]
            self.assertEqual(active["status"], "ok")
            self.assertEqual(active["project_id"], project_id)
            self.assertEqual(active["project_name"], "פרויקט בדיקה")
            self.assertEqual(active["working_dir"], working_dir)


if __name__ == "__main__":
    unittest.main()
