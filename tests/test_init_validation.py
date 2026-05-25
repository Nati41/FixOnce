import sys
import tempfile
import types
import unittest
from pathlib import Path


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


class TestInitValidation(unittest.TestCase):
    def test_valid_project_passes_both_init_entry_points(self):
        with tempfile.TemporaryDirectory(prefix="fixonce-init-valid-") as temp_dir:
            project_dir = Path(temp_dir)
            (project_dir / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

            fo_result = server.fo_init(str(project_dir))
            init_result = server.init_session(str(project_dir))

            self.assertIn("Ready.", fo_result)
            self.assertNotIn("Error:", init_result)

    def test_home_directory_is_rejected_by_both_init_entry_points(self):
        home_dir = str(Path.home())

        fo_result = server.fo_init(home_dir)
        init_result = server.init_session(home_dir)

        self.assertEqual(fo_result, "Open from a project folder to continue.")
        self.assertIn("Error: Invalid project directory", init_result)


if __name__ == "__main__":
    unittest.main()
