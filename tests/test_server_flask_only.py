import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


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

    def test_flask_only_uses_explicit_werkzeug_serve_forever(self):
        fake_server = Mock()
        fake_server.serve_forever.side_effect = KeyboardInterrupt
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch.object(server_module.flask_app, "run") as app_run, \
             patch("werkzeug.serving.make_server", return_value=fake_server) as make_server, \
             patch("socketserver.BaseServer.serve_forever", side_effect=KeyboardInterrupt) as serve_forever, \
             patch("sys.stdout", stdout), \
             patch("sys.stderr", stderr):
            with self.assertRaises(KeyboardInterrupt):
                server_module._serve_flask_blocking("127.0.0.1", 5123)

        app_run.assert_not_called()
        make_server.assert_called_once_with("127.0.0.1", 5123, server_module.flask_app, threaded=True)
        serve_forever.assert_called_once_with(fake_server)
        output = stdout.getvalue()
        self.assertIn("[FIXONCE-PROBE flask-only-serve-v3] entered _serve_flask_blocking", output)
        self.assertIn("file=", output)
        self.assertIn("[FIXONCE-PROBE flask-only-serve-v3] server_class=", output)
        self.assertIn("[FIXONCE-PROBE flask-only-serve-v3] make_server returned; serve_forever will be reached", output)
        self.assertIn("[FIXONCE-PROBE flask-only-serve-v3] BEFORE serve_forever", output)
        self.assertIn("[FIXONCE-PROBE flask-only-serve-v3] server.server_close CALLED", output)
        self.assertNotIn("[FIXONCE-PROBE flask-only-serve-v3] AFTER serve_forever", output)

    def test_unexpected_serve_forever_return_is_logged(self):
        fake_server = Mock()
        stderr = io.StringIO()
        stdout = io.StringIO()

        with patch("werkzeug.serving.make_server", return_value=fake_server), \
             patch("socketserver.BaseServer.serve_forever", return_value=None), \
             patch("sys.stderr", stderr), \
             patch("sys.stdout", stdout):
            server_module._serve_flask_blocking("127.0.0.1", 5123)

        self.assertIn("[ERROR] Flask run returned unexpectedly", stderr.getvalue())
        self.assertIn("[FIXONCE-PROBE flask-only-serve-v3] AFTER serve_forever", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
