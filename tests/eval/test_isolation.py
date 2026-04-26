"""Filesystem isolation primitives — no Docker calls in unit tests."""
from __future__ import annotations

import pathlib

from eval.isolation import seed_drive, temp_drive_root


def test_temp_drive_root_creates_subdirs(tmp_path):
    with temp_drive_root("X_test", "run123") as drive:
        assert (drive / "logs").is_dir()
        assert (drive / "state").is_dir()
        assert (drive / "memory" / "knowledge").is_dir()
        assert (drive / "task_results").is_dir()
    # cleanup happened
    assert not drive.exists()


def test_seed_drive_writes_string_and_dict(tmp_path):
    drive = tmp_path / "drive"
    drive.mkdir()
    seed_drive(drive, {
        "memory/identity.md": "I am test",
        "state/state.json": {"owner_id": 0, "spent_usd": 0.0},
    }, fixtures_dir=pathlib.Path("/nonexistent"))
    assert (drive / "memory" / "identity.md").read_text() == "I am test"
    import json
    state = json.loads((drive / "state" / "state.json").read_text())
    assert state["owner_id"] == 0
