import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


import core.install_state_machine as state_machine


class TestInstallStateMachine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="fixonce-install-machine-")
        self.data_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_default_snapshot_is_not_installed(self):
        snapshot = state_machine.load_snapshot(data_dir=self.data_dir)
        self.assertEqual(snapshot.state, state_machine.InstallState.NOT_INSTALLED)
        self.assertFalse(snapshot.installed)

    def test_runtime_promotes_state_to_ready(self):
        state_machine.persist_snapshot(
            state_machine.InstallState.WAITING_HEALTH,
            data_dir=self.data_dir,
            detail="Waiting for background startup",
        )

        with patch.object(state_machine, "get_runtime_state", return_value={"port": 5003, "pid": 88}):
            snapshot = state_machine.resolve_install_snapshot(request_port=5003, data_dir=self.data_dir)

        self.assertEqual(snapshot.state, state_machine.InstallState.READY)
        self.assertEqual(snapshot.runtime_port, 5003)
        self.assertTrue(snapshot.installed)

    def test_ready_without_runtime_stays_installed(self):
        state_machine.persist_snapshot(
            state_machine.InstallState.READY,
            data_dir=self.data_dir,
            detail="Install completed",
        )

        with patch.object(state_machine, "get_runtime_state", return_value=None):
            snapshot = state_machine.resolve_install_snapshot(request_port=5003, data_dir=self.data_dir)

        self.assertEqual(snapshot.state, state_machine.InstallState.READY)
        self.assertTrue(snapshot.installed)

    def test_ready_with_stale_runtime_stays_installed(self):
        state_machine.persist_snapshot(
            state_machine.InstallState.READY,
            data_dir=self.data_dir,
            detail="Install completed",
        )

        with patch.object(state_machine, "get_runtime_state", return_value=None):
            snapshot = state_machine.resolve_install_snapshot(request_port=5000, data_dir=self.data_dir)

        self.assertEqual(snapshot.state, state_machine.InstallState.READY)
        self.assertTrue(snapshot.installed)

    def test_active_install_flow_can_drop_back_to_starting_without_runtime(self):
        state_machine.persist_snapshot(
            state_machine.InstallState.READY,
            data_dir=self.data_dir,
            detail="Install is starting runtime",
            metadata={"active_install_flow": True},
        )

        with patch.object(state_machine, "get_runtime_state", return_value=None):
            snapshot = state_machine.resolve_install_snapshot(request_port=5003, data_dir=self.data_dir)

        self.assertEqual(snapshot.state, state_machine.InstallState.STARTING)
        self.assertFalse(snapshot.installed)

    def test_legacy_installed_marker_loads_as_ready(self):
        (self.data_dir / "install_state.json").write_text(json.dumps({
            "installed": True,
            "installed_at": "2026-03-19T12:11:00",
        }), encoding="utf-8")

        snapshot = state_machine.load_snapshot(data_dir=self.data_dir)

        self.assertEqual(snapshot.state, state_machine.InstallState.READY)
        self.assertTrue(snapshot.installed)
        self.assertTrue(snapshot.metadata["legacy_installed"])

    def test_legacy_installed_marker_stays_ready_without_runtime(self):
        (self.data_dir / "install_state.json").write_text(json.dumps({
            "installed": True,
            "installed_at": "2026-03-19T12:11:00",
        }), encoding="utf-8")

        with patch.object(state_machine, "get_runtime_state", return_value=None):
            snapshot = state_machine.resolve_install_snapshot(request_port=5003, data_dir=self.data_dir)

        self.assertEqual(snapshot.state, state_machine.InstallState.READY)
        self.assertTrue(snapshot.installed)


if __name__ == "__main__":
    unittest.main()
