"""Git tools: repo_write_commit, repo_commit_push, git_status, git_diff."""

from __future__ import annotations

import json
import logging
import os
import pathlib
import subprocess
import time
from typing import Any, Dict, List, Optional

from ouroboros.tools.registry import ToolContext, ToolEntry
from ouroboros.utils import utc_now_iso, write_text, safe_relpath, run_cmd

log = logging.getLogger(__name__)


# --- D20: refresh state.json.current_sha after self-commit -----------------
#
# Pre-D20 only `supervisor.git_ops.checkout_and_reset` updated state.json's
# `current_sha`. THAI's own commits via repo_write_commit / repo_commit_push
# bypassed that path, so on every self-commit `state.json` started drifting:
# anything reading it as ground truth (drift diagnostics, /branches Telegram
# command, worker_sha_verify) would silently use yesterday's SHA.

def _refresh_current_sha(ctx: ToolContext) -> Optional[str]:
    """Read git HEAD and persist it into state.json.current_sha.

    Best-effort: never raise. Prefers supervisor.state.load_state/save_state
    when initialized (matches the locking used by every other writer); falls
    back to a direct atomic write when running outside the supervisor (e.g.
    in tests).

    Returns the new SHA on success, None otherwise.
    """
    try:
        sha = run_cmd(["git", "rev-parse", "HEAD"], cwd=ctx.repo_dir).strip()
    except Exception:
        log.debug("Could not rev-parse HEAD to refresh current_sha", exc_info=True)
        return None
    if not sha:
        return None

    # Preferred path: use supervisor.state when its DRIVE_ROOT matches the
    # context we were called with. The match check protects tests (which use
    # a temp drive_root) from being routed at production paths via the
    # module-level singleton in supervisor.state.
    try:
        from supervisor import state as ss
        ss_root = getattr(ss, "DRIVE_ROOT", None)
        if ss_root is not None and pathlib.Path(ss_root).resolve() == pathlib.Path(ctx.drive_root).resolve():
            st = ss.load_state()
            st["current_sha"] = sha
            ss.save_state(st)
            return sha
    except Exception:
        log.debug("supervisor.state path failed, using direct write", exc_info=True)

    # Fallback: direct read/write of state.json under drive_root.
    try:
        state_path = ctx.drive_path("state/state.json")
        state_path.parent.mkdir(parents=True, exist_ok=True)
        if state_path.exists():
            try:
                data = json.loads(state_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        else:
            data = {}
        data["current_sha"] = sha
        tmp = state_path.with_suffix(state_path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(state_path)
        return sha
    except Exception:
        log.debug("Direct state.json write failed", exc_info=True)
        return None


# --- Git lock ---

def _acquire_git_lock(ctx: ToolContext, timeout_sec: int = 120) -> pathlib.Path:
    lock_dir = ctx.drive_path("locks")
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / "git.lock"
    stale_sec = 600
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if lock_path.exists():
            try:
                age = time.time() - lock_path.stat().st_mtime
                if age > stale_sec:
                    lock_path.unlink()
                    continue
            except (FileNotFoundError, OSError):
                pass
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            try:
                os.write(fd, f"locked_at={utc_now_iso()}\n".encode("utf-8"))
            finally:
                os.close(fd)
            return lock_path
        except FileExistsError:
            time.sleep(0.5)
    raise TimeoutError(f"Git lock not acquired within {timeout_sec}s: {lock_path}")


def _release_git_lock(lock_path: pathlib.Path) -> None:
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


# --- Pre-push test gate ---

MAX_TEST_OUTPUT = 8000

def _run_pre_push_tests(ctx: ToolContext) -> Optional[str]:
    """Run pre-push tests if enabled. Returns None if tests pass, error string if they fail."""
    # Guard against ctx=None
    if ctx is None:
        log.warning("_run_pre_push_tests called with ctx=None, skipping tests")
        return None

    if os.environ.get("OUROBOROS_PRE_PUSH_TESTS", "1") != "1":
        return None

    tests_dir = pathlib.Path(ctx.repo_dir) / "tests"
    if not tests_dir.exists():
        return None

    try:
        result = subprocess.run(
            ["pytest", "tests/", "-q", "--tb=line", "--no-header"],
            cwd=ctx.repo_dir,
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            return None

        # Truncate output if too long
        output = result.stdout + result.stderr
        if len(output) > MAX_TEST_OUTPUT:
            output = output[:MAX_TEST_OUTPUT] + "\n...(truncated)..."
        return output

    except subprocess.TimeoutExpired:
        return "⚠️ PRE_PUSH_TEST_ERROR: pytest timed out after 30 seconds"

    except FileNotFoundError:
        return "⚠️ PRE_PUSH_TEST_ERROR: pytest not installed or not found in PATH"

    except Exception as e:
        log.warning(f"Pre-push tests failed with exception: {e}", exc_info=True)
        return f"⚠️ PRE_PUSH_TEST_ERROR: Unexpected error running tests: {e}"


def _git_push_with_tests(ctx: ToolContext) -> Optional[str]:
    """Run pre-push tests, then pull --rebase and push. Returns None on success, error string on failure."""
    test_error = _run_pre_push_tests(ctx)
    if test_error:
        log.error("Pre-push tests failed, blocking push")
        ctx.last_push_succeeded = False
        return f"⚠️ PRE_PUSH_TESTS_FAILED: Tests failed, push blocked.\n{test_error}\nCommitted locally but NOT pushed. Fix tests and push manually."

    try:
        run_cmd(["git", "pull", "--rebase", "origin", ctx.branch_dev], cwd=ctx.repo_dir)
    except Exception:
        log.debug(f"Failed to pull --rebase before push", exc_info=True)
        pass

    try:
        run_cmd(["git", "push", "origin", ctx.branch_dev], cwd=ctx.repo_dir)
    except Exception as e:
        return f"⚠️ GIT_ERROR (push): {e}\nCommitted locally but NOT pushed."

    return None


# --- Tool implementations ---

def _repo_write_commit(ctx: ToolContext, path: str, content: str, commit_message: str) -> str:
    ctx.last_push_succeeded = False
    if not commit_message.strip():
        return "⚠️ ERROR: commit_message must be non-empty."
    lock = _acquire_git_lock(ctx)
    try:
        try:
            run_cmd(["git", "checkout", ctx.branch_dev], cwd=ctx.repo_dir)
        except Exception as e:
            return f"⚠️ GIT_ERROR (checkout): {e}"
        try:
            write_text(ctx.repo_path(path), content)
        except Exception as e:
            return f"⚠️ FILE_WRITE_ERROR: {e}"
        try:
            run_cmd(["git", "add", safe_relpath(path)], cwd=ctx.repo_dir)
        except Exception as e:
            return f"⚠️ GIT_ERROR (add): {e}"
        try:
            run_cmd(["git", "commit", "-m", commit_message], cwd=ctx.repo_dir)
        except Exception as e:
            return f"⚠️ GIT_ERROR (commit): {e}"

        push_error = _git_push_with_tests(ctx)
        if push_error:
            return push_error
    finally:
        _release_git_lock(lock)
    ctx.last_push_succeeded = True

    # D20: refresh state.json.current_sha after our own commit.
    _refresh_current_sha(ctx)

    # After push — smoke test for Python files
    if path.endswith(".py"):
        try:
            result = subprocess.run(
                ["python3", "-c", "import ouroboros.loop; print('SMOKE_OK')"],
                capture_output=True, text=True, timeout=15,
                cwd=str(ctx.repo_dir)
            )
            if result.returncode != 0 or "SMOKE_OK" not in result.stdout:
                return f"⚠️ SMOKE TEST FAILED after commit. Output: {result.stderr[:200] or result.stdout[:200]}\nCommit was pushed but system may be broken. Run restart to verify."
        except Exception as e:
            pass  # Non-critical — don't block on smoke test failure

    return f"OK: committed and pushed to {ctx.branch_dev}: {commit_message}"


def _repo_commit_push(ctx: ToolContext, commit_message: str, paths: Optional[List[str]] = None) -> str:
    ctx.last_push_succeeded = False
    if not commit_message.strip():
        return "⚠️ ERROR: commit_message must be non-empty."
    lock = _acquire_git_lock(ctx)
    try:
        try:
            run_cmd(["git", "checkout", ctx.branch_dev], cwd=ctx.repo_dir)
        except Exception as e:
            return f"⚠️ GIT_ERROR (checkout): {e}"
        if paths:
            try:
                safe_paths = [safe_relpath(p) for p in paths if str(p).strip()]
            except ValueError as e:
                return f"⚠️ PATH_ERROR: {e}"
            add_cmd = ["git", "add"] + safe_paths
        else:
            add_cmd = ["git", "add", "-A"]
        try:
            run_cmd(add_cmd, cwd=ctx.repo_dir)
        except Exception as e:
            return f"⚠️ GIT_ERROR (add): {e}"
        try:
            status = run_cmd(["git", "status", "--porcelain"], cwd=ctx.repo_dir)
        except Exception as e:
            return f"⚠️ GIT_ERROR (status): {e}"
        if not status.strip():
            return "⚠️ GIT_NO_CHANGES: nothing to commit."
        try:
            run_cmd(["git", "commit", "-m", commit_message], cwd=ctx.repo_dir)
        except Exception as e:
            return f"⚠️ GIT_ERROR (commit): {e}"

        push_error = _git_push_with_tests(ctx)
        if push_error:
            return push_error
    finally:
        _release_git_lock(lock)
    ctx.last_push_succeeded = True

    # D20: refresh state.json.current_sha after our own commit.
    _refresh_current_sha(ctx)

    # After push — smoke test for Python files
    if any(p.endswith(".py") for p in (paths or [])):
        try:
            smoke = subprocess.run(
                ["python3", "-c", "import ouroboros.loop; print('SMOKE_OK')"],
                capture_output=True, text=True, timeout=15,
                cwd=str(ctx.repo_dir)
            )
            if smoke.returncode != 0 or "SMOKE_OK" not in smoke.stdout:
                return f"⚠️ SMOKE TEST FAILED after commit. Output: {smoke.stderr[:200] or smoke.stdout[:200]}\nCommit was pushed but system may be broken. Run restart to verify."
        except Exception as e:
            pass  # Non-critical — don't block on smoke test failure

    result = f"OK: committed and pushed to {ctx.branch_dev}: {commit_message}"
    if paths is not None:
        try:
            untracked = run_cmd(["git", "ls-files", "--others", "--exclude-standard"], cwd=ctx.repo_dir)
            if untracked.strip():
                files = ", ".join(untracked.strip().split("\n"))
                result += f"\n⚠️ WARNING: untracked files remain: {files} — they are NOT in git. Use repo_commit_push without paths to add everything."
        except Exception:
            log.debug("Failed to check for untracked files after repo_commit_push", exc_info=True)
            pass
    return result


def _git_status(ctx: ToolContext) -> str:
    try:
        return run_cmd(["git", "status", "--porcelain"], cwd=ctx.repo_dir)
    except Exception as e:
        return f"⚠️ GIT_ERROR: {e}"


def _git_diff(ctx: ToolContext, staged: bool = False) -> str:
    try:
        cmd = ["git", "diff"]
        if staged:
            cmd.append("--staged")
        return run_cmd(cmd, cwd=ctx.repo_dir)
    except Exception as e:
        return f"⚠️ GIT_ERROR: {e}"


def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry("repo_write_commit", {
            "name": "repo_write_commit",
            "description": "Write one file + commit + push to ouroboros branch. For small deterministic edits.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "commit_message": {"type": "string"},
            }, "required": ["path", "content", "commit_message"]},
        }, _repo_write_commit, is_code_tool=True),
        ToolEntry("repo_commit_push", {
            "name": "repo_commit_push",
            "description": "Commit + push already-changed files. Does pull --rebase before push.",
            "parameters": {"type": "object", "properties": {
                "commit_message": {"type": "string"},
                "paths": {"type": "array", "items": {"type": "string"}, "description": "Files to add (empty = git add -A)"},
            }, "required": ["commit_message"]},
        }, _repo_commit_push, is_code_tool=True),
        ToolEntry("git_status", {
            "name": "git_status",
            "description": "git status --porcelain",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }, _git_status, is_code_tool=True),
        ToolEntry("git_diff", {
            "name": "git_diff",
            "description": "git diff (use staged=true to see staged changes after git add)",
            "parameters": {"type": "object", "properties": {
                "staged": {"type": "boolean", "default": False, "description": "If true, show staged changes (--staged)"},
            }, "required": []},
        }, _git_diff, is_code_tool=True),
    ]
