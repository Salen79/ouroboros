"""D20 — state.json.current_sha must refresh after self-commit.

Pre-D20 only `supervisor.git_ops.checkout_and_reset` wrote `current_sha`.
THAI's own commits via repo_write_commit / repo_commit_push left state.json
behind. On 2026-04-12 state said `e5ddd048…` while live HEAD was `fd687fb`
because an auto-commit had landed without updating state.

The fix lives in ouroboros/tools/git.py::_refresh_current_sha. We test the
helper directly against a real git repo to avoid mocking subprocess.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
from types import SimpleNamespace

import pytest


def _run(args, cwd):
    subprocess.run(args, cwd=str(cwd), check=True, capture_output=True)


def _make_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init", "-b", "main"], repo)
    _run(["git", "config", "user.email", "t@t"], repo)
    _run(["git", "config", "user.name", "t"], repo)
    (repo / "README.md").write_text("seed\n")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "init"], repo)
    return repo


def _make_ctx(repo: pathlib.Path, drive: pathlib.Path):
    """Tiny ToolContext stand-in: only repo_dir and drive_path are used."""
    drive.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        repo_dir=repo,
        drive_root=drive,
        drive_path=lambda rel: drive / rel,
    )


def _head_sha(repo: pathlib.Path) -> str:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo), capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def test_refresh_creates_state_json_when_missing(tmp_path):
    from ouroboros.tools.git import _refresh_current_sha

    repo = _make_repo(tmp_path)
    drive = tmp_path / "drive"
    ctx = _make_ctx(repo, drive)

    sha = _head_sha(repo)
    out = _refresh_current_sha(ctx)

    assert out == sha
    state_path = drive / "state" / "state.json"
    assert state_path.exists()
    data = json.loads(state_path.read_text())
    assert data["current_sha"] == sha


def test_refresh_updates_existing_state_json_preserving_other_fields(tmp_path):
    from ouroboros.tools.git import _refresh_current_sha

    repo = _make_repo(tmp_path)
    drive = tmp_path / "drive"
    state_path = drive / "state" / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({
        "current_sha": "stale_sha",
        "current_branch": "main",
        "owner_id": 12345,
        "spent_usd": 4.20,
    }), encoding="utf-8")

    ctx = _make_ctx(repo, drive)
    out = _refresh_current_sha(ctx)

    sha = _head_sha(repo)
    assert out == sha
    data = json.loads(state_path.read_text())
    assert data["current_sha"] == sha
    # All other fields must survive
    assert data["current_branch"] == "main"
    assert data["owner_id"] == 12345
    assert data["spent_usd"] == 4.20


def test_refresh_picks_up_new_commit(tmp_path):
    """The whole point: after a new commit, current_sha must be the new HEAD."""
    from ouroboros.tools.git import _refresh_current_sha

    repo = _make_repo(tmp_path)
    drive = tmp_path / "drive"
    ctx = _make_ctx(repo, drive)
    _refresh_current_sha(ctx)
    state_path = drive / "state" / "state.json"
    first_sha = json.loads(state_path.read_text())["current_sha"]

    # Make another commit (simulating self-commit through repo_commit_push)
    (repo / "x.txt").write_text("hello\n")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "second"], repo)

    new_sha = _refresh_current_sha(ctx)
    assert new_sha != first_sha
    assert new_sha == _head_sha(repo)
    assert json.loads(state_path.read_text())["current_sha"] == new_sha


def test_refresh_swallows_subprocess_failure(tmp_path):
    """Helper must never raise even when not in a git repo."""
    from ouroboros.tools.git import _refresh_current_sha

    not_a_repo = tmp_path / "norepo"
    not_a_repo.mkdir()
    drive = tmp_path / "drive"
    ctx = _make_ctx(not_a_repo, drive)

    out = _refresh_current_sha(ctx)
    assert out is None
    # Must not have created state.json
    assert not (drive / "state" / "state.json").exists()


def test_refresh_called_from_repo_commit_push(tmp_path, monkeypatch):
    """End-to-end: the helper is wired from _repo_commit_push after push.

    We monkeypatch the lock + push paths so the test stays hermetic and
    isolated from a real remote.
    """
    from ouroboros.tools import git as git_mod

    repo = _make_repo(tmp_path)
    drive = tmp_path / "drive"
    state_path = drive / "state" / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"current_sha": "stale"}), encoding="utf-8")

    # Make a working-tree change so commit has something to do
    (repo / "x.txt").write_text("change\n")

    ctx = SimpleNamespace(
        repo_dir=repo,
        drive_root=drive,
        drive_path=lambda rel: drive / rel,
        branch_dev="main",
        last_push_succeeded=False,
    )

    # Stub remote-touching helpers
    monkeypatch.setattr(git_mod, "_acquire_git_lock", lambda c, **_: pathlib.Path("/tmp/x.lock"))
    monkeypatch.setattr(git_mod, "_release_git_lock", lambda _: None)
    monkeypatch.setattr(git_mod, "_git_push_with_tests", lambda c: None)

    result = git_mod._repo_commit_push(ctx, "test commit")
    assert "OK" in result
    assert ctx.last_push_succeeded is True

    # state.json must now reflect the new HEAD
    new_sha = _head_sha(repo)
    assert json.loads(state_path.read_text())["current_sha"] == new_sha
    assert new_sha != "stale"
