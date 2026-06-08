import sys
import tempfile
import types
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "src" / "mcp_server"))


class _FakeFastMCP:
    def __init__(self, *_args, **_kwargs):
        pass

    def tool(self, *_args, **_kwargs):
        def decorator(func):
            return func
        return decorator


sys.modules["fastmcp"] = types.SimpleNamespace(FastMCP=_FakeFastMCP)
sys.modules.pop("mcp_memory_server_v2", None)

import mcp_memory_server_v2 as server
from core import boundary_detector, session_registry
from managers import multi_project_manager


@contextmanager
def isolated_fixonce_user_data():
    with tempfile.TemporaryDirectory(prefix="fixonce-user-data-") as temp_dir:
        user_data_dir = Path(temp_dir) / ".fixonce"
        projects_dir = user_data_dir / "projects_v2"
        projects_dir.mkdir(parents=True)
        (user_data_dir / "global").mkdir()

        with ExitStack() as stack:
            for target, attribute, value in [
                (server, "USER_DATA_DIR", user_data_dir),
                (server, "DATA_DIR", projects_dir),
                (server, "INDEX_FILE", user_data_dir / "project_index.json"),
                (server, "ENABLED_FLAG_FILE", user_data_dir / "fixonce_enabled.json"),
                (server, "SESSION_FILE", user_data_dir / "mcp_session.json"),
                (server, "COMPLIANCE_FILE", user_data_dir / "mcp_compliance.json"),
                (server, "AI_CONNECTIONS_FILE", user_data_dir / "ai_connections.json"),
                (multi_project_manager, "USER_DATA_DIR", user_data_dir),
                (multi_project_manager, "DATA_DIR", user_data_dir),
                (multi_project_manager, "PROJECTS_V2_DIR", projects_dir),
                (multi_project_manager, "GLOBAL_DIR", user_data_dir / "global"),
                (multi_project_manager, "ACTIVE_PROJECT_FILE", user_data_dir / "active_project.json"),
                (multi_project_manager, "PROJECT_INDEX_FILE", user_data_dir / "project_index.json"),
                (
                    multi_project_manager,
                    "PROJECT_CATALOG_MIGRATION_FILE",
                    user_data_dir / "project_catalog_migration_v1.json",
                ),
                (boundary_detector, "DATA_DIR", user_data_dir),
                (boundary_detector, "BOUNDARY_STATE_FILE", user_data_dir / "boundary_state.json"),
                (boundary_detector, "ACTIVE_PROJECT_FILE", user_data_dir / "active_project.json"),
                (session_registry, "DATA_DIR", user_data_dir),
                (session_registry, "REGISTRY_FILE", user_data_dir / "session_registry.json"),
                (session_registry, "_registry", None),
                (session_registry.SessionRegistry, "_instance", None),
            ]:
                stack.enter_context(patch.object(target, attribute, value))
            yield user_data_dir


class TestInitValidation(unittest.TestCase):
    def test_valid_project_passes_both_init_entry_points(self):
        real_store = Path.home() / ".fixonce" / "projects_v2"
        before = {
            path.name for path in real_store.glob("fixonce-init-valid-*.json")
        } if real_store.exists() else set()

        with isolated_fixonce_user_data() as user_data_dir, \
             tempfile.TemporaryDirectory(prefix="fixonce-init-valid-") as temp_dir:
            project_dir = Path(temp_dir)
            (project_dir / "pyproject.toml").write_text(
                "[project]\nname='demo'\n",
                encoding="utf-8",
            )

            fo_result = server.fo_init(str(project_dir))
            init_result = server.init_session(str(project_dir))

            self.assertIn("Ready.", fo_result)
            self.assertNotIn("Error:", init_result)
            self.assertTrue(any((user_data_dir / "projects_v2").glob("*.json")))

        after = {
            path.name for path in real_store.glob("fixonce-init-valid-*.json")
        } if real_store.exists() else set()
        self.assertEqual(after, before)

    def test_home_directory_is_rejected_by_both_init_entry_points(self):
        with isolated_fixonce_user_data():
            home_dir = str(Path.home())

            fo_result = server.fo_init(home_dir)
            init_result = server.init_session(home_dir)

            self.assertEqual(fo_result, "Open from a project folder to continue.")
            self.assertIn("Error: Invalid project directory", init_result)


if __name__ == "__main__":
    unittest.main()
