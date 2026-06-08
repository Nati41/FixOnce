import json
import sys
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from core.boundary_detector import BoundaryEvent, handle_boundary_transition
from managers import multi_project_manager
from api.status import _dashboard_project_status, _sort_dashboard_projects


@contextmanager
def isolated_project_catalog():
    with tempfile.TemporaryDirectory(prefix="fixonce-project-catalog-") as temp_dir:
        data_dir = Path(temp_dir) / ".fixonce"
        projects_dir = data_dir / "projects_v2"
        projects_dir.mkdir(parents=True)

        with patch.object(multi_project_manager, "USER_DATA_DIR", data_dir), \
             patch.object(multi_project_manager, "DATA_DIR", data_dir), \
             patch.object(multi_project_manager, "PROJECTS_V2_DIR", projects_dir), \
             patch.object(multi_project_manager, "GLOBAL_DIR", data_dir / "global"), \
             patch.object(multi_project_manager, "ACTIVE_PROJECT_FILE", data_dir / "active_project.json"), \
             patch.object(multi_project_manager, "PROJECT_INDEX_FILE", data_dir / "project_index.json"), \
             patch.object(
                 multi_project_manager,
                 "PROJECT_CATALOG_MIGRATION_FILE",
                 data_dir / "project_catalog_migration_v1.json",
             ):
            yield data_dir, projects_dir


def write_project(
    projects_dir: Path,
    project_id: str,
    name: str,
    working_dir: str = "",
    provenance: str = None,
    archived: bool = False,
    **extra_info,
):
    info = {
        "name": name,
        "working_dir": working_dir,
        "archived": archived,
        **extra_info,
    }
    if provenance:
        info["provenance"] = provenance
    payload = {
        "project_info": info,
        "live_record": {"lessons": {"insights": []}},
        "stats": {"last_updated": "2026-06-08T09:00:00"},
        "decisions": [],
        "avoid": [],
    }
    path = projects_dir / f"{project_id}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class TestDashboardProjectSelection(unittest.TestCase):
    def test_existing_dashboard_selection_is_not_replaced_by_session_init(self):
        selected = {
            "active_id": "project-x",
            "display_name": "Project X",
            "working_dir": "/projects/x",
        }

        with patch.object(multi_project_manager, "get_active_project", return_value=selected), \
             patch.object(multi_project_manager, "set_active_project") as set_active:
            result = multi_project_manager.ensure_dashboard_project(
                "project-y",
                detected_from="fo_init",
                display_name="Project Y",
                working_dir="/projects/y",
            )

        self.assertEqual(result, selected)
        set_active.assert_not_called()

    def test_first_session_seeds_dashboard_selection(self):
        expected = {
            "active_id": "project-x",
            "display_name": "Project X",
            "working_dir": "/projects/x",
        }

        with patch.object(multi_project_manager, "get_active_project", return_value=None), \
             patch.object(multi_project_manager, "set_active_project", return_value=expected) as set_active:
            result = multi_project_manager.ensure_dashboard_project(
                "project-x",
                detected_from="fo_init",
                display_name="Project X",
                working_dir="/projects/x",
            )

        self.assertEqual(result, expected)
        set_active.assert_called_once_with(
            project_id="project-x",
            detected_from="fo_init",
            display_name="Project X",
            working_dir="/projects/x",
        )

    def test_boundary_transition_does_not_change_dashboard_selection(self):
        event = BoundaryEvent(
            old_project_id="project-x",
            old_working_dir="/projects/x",
            new_project_id="project-y",
            new_working_dir="/projects/y",
            file_path="/projects/y/src/main.py",
            reason="session_init",
            confidence="high",
            timestamp=datetime.now().isoformat(),
        )

        with patch("managers.multi_project_manager.load_project_memory", return_value={}), \
             patch("managers.multi_project_manager.init_project_memory") as init_project, \
             patch("core.boundary_detector._load_boundary_state", return_value={}), \
             patch("core.boundary_detector._save_boundary_state"):
            result = handle_boundary_transition(event)

        self.assertEqual(result, "project-y")
        init_project.assert_called_once_with(
            project_id="project-y",
            display_name="y",
            working_dir="/projects/y",
        )


class TestDashboardProjectUi(unittest.TestCase):
    def test_dashboard_exposes_explicit_project_selector(self):
        html = (PROJECT_ROOT / "data" / "dashboard.html").read_text(encoding="utf-8")

        self.assertIn('id="projectSelect"', html)
        self.assertIn("switchDisplayedProject", html)
        self.assertIn("/api/projects/switch/", html)
        self.assertIn('id="projectPresence"', html)


class TestCanonicalProjectCatalog(unittest.TestCase):
    def test_only_real_user_visible_projects_are_returned(self):
        with isolated_project_catalog() as (_, projects_dir):
            valid_dir = projects_dir.parent / "workspaces" / "FixOnce"
            valid_dir.mkdir(parents=True)
            deleted_dir = projects_dir.parent / "workspaces" / "deleted"

            write_project(
                projects_dir,
                "FixOnce_real",
                "FixOnce",
                str(valid_dir),
                provenance="user",
            )
            deleted_path = write_project(
                projects_dir,
                "Deleted_temp",
                "Deleted",
                str(deleted_dir),
                provenance="user",
            )
            write_project(
                projects_dir,
                "Archived_real",
                "Archived",
                str(valid_dir),
                provenance="user",
                archived=True,
            )
            write_project(projects_dir, "memory_legacy", "memory")
            write_project(
                projects_dir,
                "fixonce-init-valid-test",
                "fixonce-init-valid-test",
                str(valid_dir),
                provenance="test",
            )

            projects = multi_project_manager.list_projects()

            self.assertEqual([project["name"] for project in projects], ["FixOnce"])
            quarantined = json.loads(deleted_path.read_text(encoding="utf-8"))
            self.assertTrue(quarantined["project_info"]["archived"])
            self.assertEqual(
                quarantined["project_info"]["quarantine"]["reason"],
                "missing_working_dir",
            )

    def test_pinned_or_imported_legacy_project_can_remain_visible(self):
        with isolated_project_catalog() as (_, projects_dir):
            write_project(
                projects_dir,
                "Imported_project",
                "Imported",
                imported=True,
            )

            projects = multi_project_manager.list_projects()

            self.assertEqual([project["name"] for project in projects], ["Imported"])

    def test_project_index_recovers_real_legacy_working_directory(self):
        with isolated_project_catalog() as (data_dir, projects_dir):
            real_dir = data_dir.parent / "TaskPilot"
            real_dir.mkdir()
            write_project(projects_dir, "TaskPilot_real", "TaskPilot")
            (data_dir / "project_index.json").write_text(json.dumps({
                "projects": {
                    "TaskPilot_real": {
                        "working_dir": str(real_dir),
                    }
                }
            }), encoding="utf-8")

            projects = multi_project_manager.list_projects()

            self.assertEqual([project["name"] for project in projects], ["TaskPilot"])
            self.assertEqual(projects[0]["working_dir"], str(real_dir))
            self.assertEqual(projects[0]["provenance"], "user")

    def test_active_and_recent_status_sort_without_changing_inclusion(self):
        now = datetime(2026, 6, 8, 12, 0, 0)
        projects = [
            {"id": "stale", "last_updated": "2026-05-01T12:00:00"},
            {"id": "recent", "last_updated": "2026-06-07T12:00:00"},
            {"id": "active", "last_updated": "2026-04-01T12:00:00"},
        ]
        decorated = [
            {
                **project,
                "status": _dashboard_project_status(project, "active", now),
            }
            for project in projects
        ]

        sorted_projects = _sort_dashboard_projects(decorated)

        self.assertEqual(
            [project["id"] for project in sorted_projects],
            ["active", "recent", "stale"],
        )
        self.assertEqual(len(sorted_projects), len(projects))

    def test_test_project_name_is_not_user_visible(self):
        with isolated_project_catalog() as (_, projects_dir):
            real_dir = projects_dir.parent / "FixOnceTestProject"
            real_dir.mkdir()
            write_project(
                projects_dir,
                "FixOnceTestProject_id",
                "FixOnceTestProject",
                str(real_dir),
            )

            projects = multi_project_manager.list_projects()

            self.assertEqual(projects, [])


if __name__ == "__main__":
    unittest.main()
