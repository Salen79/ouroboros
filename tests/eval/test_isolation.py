"""Filesystem isolation primitives — no Docker calls in unit tests."""
from __future__ import annotations

import pathlib
import subprocess

from eval.isolation import (
    clone_path_for,
    seed_drive,
    shallow_clone_repo,
    temp_drive_root,
)


def _git(args, cwd):
    return subprocess.check_output(["git", "-C", str(cwd)] + args, text=True).strip()


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


# B-O8: shallow_clone_repo must produce an isolated working tree —
# commits in the clone never reach the source repo.

def _make_seed_repo(root: pathlib.Path) -> pathlib.Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(["git", "init", "-q", "-b", "main", str(root)])
    subprocess.check_call(["git", "-C", str(root), "config", "user.email", "test@test"])
    subprocess.check_call(["git", "-C", str(root), "config", "user.name", "test"])
    (root / "README.md").write_text("seed\n")
    subprocess.check_call(["git", "-C", str(root), "add", "."])
    subprocess.check_call(["git", "-C", str(root), "commit", "-q", "-m", "seed"])
    return root


def test_shallow_clone_isolates_commits_from_source(tmp_path):
    src = _make_seed_repo(tmp_path / "src")
    src_head_before = _git(["rev-parse", "HEAD"], src)

    clone = shallow_clone_repo(src, src_head_before, tmp_path / "clone")

    # Make a commit IN THE CLONE.
    (clone / "new_file.txt").write_text("from agent\n")
    subprocess.check_call(["git", "-C", str(clone), "add", "new_file.txt"])
    subprocess.check_call(["git", "-C", str(clone), "commit", "-q", "-m", "auto-rescue: simulated"])
    clone_head_after = _git(["rev-parse", "HEAD"], clone)

    src_head_after = _git(["rev-parse", "HEAD"], src)
    assert src_head_before == src_head_after, \
        "live repo HEAD must not move when clone gets committed"
    assert clone_head_after != clone_head_before_clone(src_head_before), \
        "clone HEAD must have moved"
    # Cross-check: the clone's commit author was set by shallow_clone_repo.
    log = _git(["log", "-1", "--format=%an <%ae>"], clone)
    assert log == "eval-sandbox <eval-sandbox@localhost>"


def clone_head_before_clone(sha: str) -> str:
    """Trivial helper to make the assertion above readable."""
    return sha


def test_shallow_clone_remote_unset(tmp_path):
    src = _make_seed_repo(tmp_path / "src")
    head = _git(["rev-parse", "HEAD"], src)
    clone = shallow_clone_repo(src, head, tmp_path / "clone")
    remotes = subprocess.check_output(
        ["git", "-C", str(clone), "remote"], text=True
    ).strip()
    assert remotes == "", f"clone must have no remote (got: {remotes!r})"


def test_clone_path_for_is_sibling_of_drive_root(tmp_path):
    drive = tmp_path / "thai_eval_xyz" / "drive_root"
    drive.mkdir(parents=True)
    p = clone_path_for(drive)
    assert p == tmp_path / "thai_eval_xyz" / "repo_clone"
    assert p.parent == drive.parent  # cleaned by temp_drive_root teardown
