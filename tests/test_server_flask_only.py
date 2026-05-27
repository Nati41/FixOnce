import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


import server as server_module


class TestServerFlaskOnly(unittest.TestCase):
    def test_run_flask_reaches_blocking_server_path(self):
        with tempfile.TemporaryDirectory(prefix="fixonce-flask-only-") as temp_dir:
            data_dir = Path(temp_dir)

            with patch.object(server_module, "DATA_DIR", data_dir), \
                 patch.object(server_module, "acquire_server_lock", return_value=True), \
                 patch.object(server_module, "release_server_lock") as release_lock, \
                 patch.object(server_module, "clear_runtime_state") as clear_runtime, \
                 patch.object(server_module, "find_available_port", return_value=5123), \
                 patch.object(server_module, "set_actual_port") as set_actual_port, \
                 patch.object(server_module, "set_runtime_state", return_value=True) as set_runtime, \
                 patch.object(server_module, "set_preferred_port") as set_preferred, \
                 patch.object(server_module, "_serve_flask_blocking", side_effect=KeyboardInterrupt) as serve:
                server_module._run_flask()

            serve.assert_called_once_with("127.0.0.1", 5123)
            set_actual_port.assert_called_once_with(5123)
            set_runtime.assert_called_once()
            set_preferred.assert_called_once_with(5123)
            self.assertEqual((data_dir / "current_port.txt").read_text(encoding="utf-8"), "5123")
            clear_runtime.assert_called()
            release_lock.assert_called()


if __name__ == "__main__":
    unittest.main()
