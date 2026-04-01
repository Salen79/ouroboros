"""
Ouroboros — Safe Self-Modification Pipeline.

Classifies files into zones (GREEN/YELLOW/RED), manages modification
lifecycle with rollback support, runs smoke tests, and gates merges
by zone level.

Session 1 of the Self-Evolution Plan.
"""

from __future__ import annotations

import enum
import fnmatch
import logging
import os
import pathlib
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import json
import shutil

import yaml

log = logging.getLogger(__name__)

# File extensions that should be routed through Claude Code CLI
CODE_EXTENSIONS = frozenset((
    ".py", ".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs",
))

DATA_DIR = pathlib.Path(os.environ.get("DRIVE_ROOT", os.path.expanduser("~/ouroboros-data")))

REPO_DIR = pathlib.Path(os.environ.get("OUROBOROS_REPO_DIR", os.path.expanduser("~/ouroboros")))
ZONES_PATH = REPO_DIR / "config" / "FILE_ZONES.yaml"


class FileZone(enum.Enum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


@dataclass
class ModificationContext:
    """Tracks an in-progress self-modification."""
    branch: str
    base_sha: str
    files_changed: List[str] = field(default_factory=list)
    zone: FileZone = FileZone.YELLOW
    started_at: float = field(default_factory=time.time)
    committed: bool = False
    merged: bool = False


class SelfEvolution:
    """Safe self-modification pipeline with zone-based gating."""

    def __init__(self, repo_dir: Optional[pathlib.Path] = None):
        self.repo_dir = repo_dir or REPO_DIR
        self._zones_config: Optional[Dict[str, Any]] = None
        self._active_mod: Optional[ModificationContext] = None

    # ── Zone config loading ──────────────────────────────────────

    def _load_zones(self) -> Dict[str, Any]:
        """Load and cache FILE_ZONES.yaml."""
        if self._zones_config is not None:
            return self._zones_config
        zones_path = self.repo_dir / "config" / "FILE_ZONES.yaml"
        if not zones_path.exists():
            log.warning("FILE_ZONES.yaml not found at %s, using defaults", zones_path)
            self._zones_config = {"zones": {}, "defaults": {"unknown_file": "yellow", "file_deletion": "red"}}
            return self._zones_config
        with open(zones_path, "r", encoding="utf-8") as f:
            self._zones_config = yaml.safe_load(f)
        return self._zones_config

    # ── Classification ───────────────────────────────────────────

    def classify_file(self, filepath: str) -> FileZone:
        """Classify a single file path into a zone.

        Args:
            filepath: Relative path from repo root (e.g. 'ouroboros/agent.py')

        Returns:
            FileZone enum value
        """
        config = self._load_zones()
        zones = config.get("zones", {})
        defaults = config.get("defaults", {})

        # Normalize path separators
        filepath = filepath.replace("\\", "/").lstrip("/")

        # Check each zone in priority order: red > yellow > green
        for zone_name in ("red", "yellow", "green"):
            zone_data = zones.get(zone_name, {})
            paths = zone_data.get("paths", [])
            patterns = zone_data.get("patterns", [])

            for pattern in paths:
                if self._path_matches(filepath, pattern):
                    return FileZone(zone_name)

            for pattern in patterns:
                if fnmatch.fnmatch(filepath, pattern) or fnmatch.fnmatch(os.path.basename(filepath), pattern):
                    return FileZone(zone_name)

        # Default for unknown files
        default_zone = defaults.get("unknown_file", "yellow")
        return FileZone(default_zone)

    def classify_changeset(self, filepaths: List[str], has_deletions: bool = False) -> FileZone:
        """Classify a set of changed files, returning the highest zone.

        File deletion always elevates to RED regardless of file location.

        Args:
            filepaths: List of relative file paths being changed
            has_deletions: Whether any files are being deleted

        Returns:
            The highest (most restrictive) zone across all files
        """
        if has_deletions:
            return FileZone.RED

        if not filepaths:
            return FileZone.GREEN

        highest = FileZone.GREEN
        zone_priority = {FileZone.GREEN: 0, FileZone.YELLOW: 1, FileZone.RED: 2}

        for fp in filepaths:
            zone = self.classify_file(fp)
            if zone_priority[zone] > zone_priority[highest]:
                highest = zone
            if highest == FileZone.RED:
                break  # Can't go higher

        return highest

    @staticmethod
    def _path_matches(filepath: str, pattern: str) -> bool:
        """Check if a filepath matches a zone pattern.

        Supports:
          - Exact match: 'ouroboros/agent.py'
          - Glob with **: 'supervisor/**'
          - Glob with *: '*.key'
        """
        if pattern == filepath:
            return True
        if "**" in pattern:
            prefix = pattern.replace("/**", "").replace("**", "")
            if filepath.startswith(prefix):
                return True
        return fnmatch.fnmatch(filepath, pattern)

    # ── Modification lifecycle ───────────────────────────────────

    def _git(self, *args: str, check: bool = True, timeout: int = 30) -> subprocess.CompletedProcess:
        """Run a git command in the repo directory."""
        return subprocess.run(
            ["git"] + list(args),
            cwd=str(self.repo_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
        )

    def begin_modification(self, branch_name: str, description: str = "") -> ModificationContext:
        """Start a new modification: create branch, record base SHA.

        Args:
            branch_name: Name for the feature branch
            description: Human-readable description of the change

        Returns:
            ModificationContext tracking this modification
        """
        # Get current HEAD SHA
        result = self._git("rev-parse", "HEAD")
        base_sha = result.stdout.strip()

        # Create and checkout new branch
        self._git("checkout", "-b", branch_name)

        self._active_mod = ModificationContext(
            branch=branch_name,
            base_sha=base_sha,
        )
        log.info("Self-evolution: began modification on branch %s (base: %s)", branch_name, base_sha[:8])
        return self._active_mod

    def commit_changes(
        self,
        message: str,
        files: Optional[List[str]] = None,
        task_description: Optional[str] = None,
        constraints: Optional[List[str]] = None,
    ) -> str:
        """Stage and commit changes.

        If task_description is provided and the changeset includes code files,
        Claude Code CLI is invoked first to perform the actual edits.  THAI
        decides WHAT and WHY; Claude Code handles HOW.

        Args:
            message: Commit message
            files: Specific files to stage (None = all tracked changes)
            task_description: If set, delegate code edits to Claude Code CLI
            constraints: Constraints to pass to Claude Code CLI

        Returns:
            Commit SHA
        """
        # ── Claude Code delegation for code files ──────────────────
        if task_description and files:
            code_files = [f for f in files if self._is_code_file(f)]
            if code_files:
                cc_result = self.claude_code_execute(
                    task_description=task_description,
                    files=code_files,
                    constraints=constraints,
                )
                if cc_result["fallback"]:
                    log.warning(
                        "Claude Code CLI unavailable/failed — expecting files "
                        "already written via write_file"
                    )
                elif not cc_result["success"]:
                    log.error("Claude Code CLI failed: %s", cc_result["output"][:300])

        if files:
            for f in files:
                self._git("add", f)
        else:
            self._git("add", "-u")

        self._git("commit", "-m", message)
        result = self._git("rev-parse", "HEAD")
        sha = result.stdout.strip()

        if self._active_mod:
            self._active_mod.files_changed = files or []
            self._active_mod.committed = True
            # Classify the changeset
            has_deletions = any(
                line.startswith("D")
                for line in self._git("diff", "--name-status", self._active_mod.base_sha, "HEAD").stdout.splitlines()
            )
            self._active_mod.zone = self.classify_changeset(
                files or [],
                has_deletions=has_deletions,
            )

        log.info("Self-evolution: committed %s (%s)", sha[:8], message[:60])
        return sha

    def run_smoke_tests(self) -> Tuple[bool, str]:
        """Run smoke tests on the current state.

        Returns:
            (passed, output) tuple
        """
        smoke_script = self.repo_dir / "scripts" / "smoke_test.py"
        if not smoke_script.exists():
            return False, "smoke_test.py not found"

        try:
            result = subprocess.run(
                ["python3", str(smoke_script)],
                cwd=str(self.repo_dir),
                capture_output=True,
                text=True,
                timeout=60,
            )
            passed = result.returncode == 0
            output = result.stdout + result.stderr
            log.info("Self-evolution: smoke tests %s", "PASSED" if passed else "FAILED")
            return passed, output
        except subprocess.TimeoutExpired:
            return False, "Smoke tests timed out (60s)"
        except Exception as e:
            return False, f"Smoke test error: {e}"

    def auto_merge(self, target_branch: str = "ouroboros") -> Tuple[bool, str]:
        """Auto-merge if zone allows it.

        GREEN  -> auto-merge after smoke tests pass
        YELLOW -> returns requires_approval message
        RED    -> returns blocked message

        Returns:
            (merged, message) tuple
        """
        if self._active_mod is None:
            return False, "No active modification"

        zone = self._active_mod.zone

        if zone == FileZone.RED:
            return False, f"BLOCKED: changeset is RED zone — requires explicit owner permission"

        if zone == FileZone.YELLOW:
            return False, f"REQUIRES APPROVAL: changeset is YELLOW zone — owner must approve merge"

        # GREEN zone: run smoke tests first
        passed, test_output = self.run_smoke_tests()
        if not passed:
            return False, f"Smoke tests failed — not merging.\n{test_output}"

        # Merge
        try:
            self._git("checkout", target_branch)
            self._git("merge", "--no-ff", self._active_mod.branch, "-m",
                       f"auto-merge: {self._active_mod.branch} (GREEN zone, smoke tests passed)")
            self._active_mod.merged = True
            log.info("Self-evolution: auto-merged %s into %s", self._active_mod.branch, target_branch)
            return True, f"Auto-merged {self._active_mod.branch} into {target_branch}"
        except subprocess.CalledProcessError as e:
            return False, f"Merge failed: {e.stderr}"

    def rollback(self) -> Tuple[bool, str]:
        """Rollback the active modification: checkout base branch and delete feature branch.

        Returns:
            (success, message) tuple
        """
        if self._active_mod is None:
            return False, "No active modification to rollback"

        branch = self._active_mod.branch
        base_sha = self._active_mod.base_sha

        try:
            # Go back to the branch that contains base_sha
            self._git("checkout", "-", check=False)
            # Delete the feature branch
            self._git("branch", "-D", branch, check=False)
            self._active_mod = None
            log.info("Self-evolution: rolled back branch %s", branch)
            return True, f"Rolled back: deleted branch {branch}, returned to previous branch"
        except Exception as e:
            return False, f"Rollback error: {e}"

    def health_check(self) -> Dict[str, Any]:
        """Run a health check on the self-evolution system.

        Returns:
            Dict with status info
        """
        checks: Dict[str, Any] = {}

        # 1. FILE_ZONES.yaml exists and is valid
        zones_path = self.repo_dir / "config" / "FILE_ZONES.yaml"
        checks["zones_config"] = zones_path.exists()

        # 2. smoke_test.py exists
        smoke_path = self.repo_dir / "scripts" / "smoke_test.py"
        checks["smoke_test_exists"] = smoke_path.exists()

        # 3. Git status clean
        try:
            result = self._git("status", "--porcelain")
            checks["git_clean"] = result.stdout.strip() == ""
        except Exception:
            checks["git_clean"] = False

        # 4. Active modification state
        checks["active_modification"] = self._active_mod is not None
        if self._active_mod:
            checks["active_branch"] = self._active_mod.branch
            checks["active_zone"] = self._active_mod.zone.value

        # 5. Zone self-protection: FILE_ZONES.yaml should be RED
        zones_zone = self.classify_file("config/FILE_ZONES.yaml")
        checks["zones_self_protection"] = zones_zone == FileZone.RED

        checks["status"] = "ok" if all([
            checks["zones_config"],
            checks["smoke_test_exists"],
            checks["zones_self_protection"],
        ]) else "degraded"

        return checks

    # ── Claude Code CLI integration ───────────────────────────────

    @staticmethod
    def _is_code_file(filepath: str) -> bool:
        """Return True if the file extension indicates source code."""
        return pathlib.PurePosixPath(filepath).suffix.lower() in CODE_EXTENSIONS

    @staticmethod
    def _claude_cli_available() -> bool:
        """Check whether the Claude Code CLI binary is on PATH."""
        return shutil.which("claude") is not None

    def claude_code_execute(
        self,
        task_description: str,
        files: List[str],
        constraints: Optional[List[str]] = None,
        timeout: int = 300,
    ) -> Dict[str, Any]:
        """Invoke Claude Code CLI to make code changes.

        THAI decides WHAT to change and WHY; Claude Code handles HOW.

        Args:
            task_description: What the change should accomplish and why.
            files: List of file paths (relative to repo root) to modify.
            constraints: Optional list of constraints / patterns to follow.
            timeout: Maximum seconds for the CLI invocation.

        Returns:
            {success: bool, output: str, files_changed: list, fallback: bool}
        """
        if not self._claude_cli_available():
            log.warning("Claude Code CLI not available — falling back to write_file")
            return {
                "success": False,
                "output": "Claude Code CLI not found on server. Falling back to write_file.",
                "files_changed": [],
                "fallback": True,
            }

        # Build a clear prompt for Claude Code
        file_list = "\n".join(f"  - {f}" for f in files)
        prompt_parts = [
            f"Task: {task_description}",
            f"\nFiles to modify:\n{file_list}",
        ]
        if constraints:
            constraint_list = "\n".join(f"  - {c}" for c in constraints)
            prompt_parts.append(f"\nConstraints:\n{constraint_list}")
        prompt_parts.append(
            f"\nIMPORTANT: Only modify the listed files inside {self.repo_dir}. "
            f"Do NOT create new files unless absolutely necessary. "
            f"Do NOT commit or push."
        )
        prompt = "\n".join(prompt_parts)

        claude_bin = shutil.which("claude")
        cmd = [
            claude_bin, "-p", prompt,
            "--output-format", "json",
            "--max-turns", "12",
            "--tools", "Read,Edit,Grep,Glob",
        ]

        # Permission mode
        perm_mode = os.environ.get(
            "OUROBOROS_CLAUDE_CODE_PERMISSION_MODE", "bypassPermissions"
        ).strip()
        cmd += ["--permission-mode", perm_mode]

        env = os.environ.copy()
        env.pop("ANTHROPIC_API_KEY", None)
        local_bin = str(pathlib.Path.home() / ".local" / "bin")
        if local_bin not in env.get("PATH", ""):
            env["PATH"] = f"{local_bin}:{env.get('PATH', '')}"

        log.info(
            "Claude Code CLI: executing task (%d files, timeout=%ds)",
            len(files), timeout,
        )

        try:
            res = subprocess.run(
                cmd,
                cwd=str(self.repo_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )

            stdout = (res.stdout or "").strip()
            stderr = (res.stderr or "").strip()

            if res.returncode != 0:
                combined = (stdout + "\n" + stderr).lower()
                if "--permission-mode" in combined and any(
                    m in combined
                    for m in ("unknown option", "unknown argument", "unrecognized option")
                ):
                    fallback_cmd = [
                        claude_bin, "-p", prompt,
                        "--output-format", "json",
                        "--max-turns", "12",
                        "--tools", "Read,Edit,Grep,Glob",
                        "--dangerously-skip-permissions",
                    ]
                    res = subprocess.run(
                        fallback_cmd,
                        cwd=str(self.repo_dir),
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                        env=env,
                    )
                    stdout = (res.stdout or "").strip()
                    stderr = (res.stderr or "").strip()

            if res.returncode != 0:
                log.error("Claude Code CLI failed (exit=%d): %s", res.returncode, stderr[:500])
                return {
                    "success": False,
                    "output": f"exit={res.returncode}\nSTDOUT:\n{stdout[:2000]}\nSTDERR:\n{stderr[:2000]}",
                    "files_changed": [],
                    "fallback": True,
                }

            # Detect which files were actually changed via git status
            changed = self._detect_changed_files()

            # Parse cost from JSON output
            cost = 0.0
            try:
                payload = json.loads(stdout)
                result_text = payload.get("result", stdout)
                if isinstance(payload.get("total_cost_usd"), (int, float)):
                    cost = float(payload["total_cost_usd"])
            except (json.JSONDecodeError, TypeError):
                result_text = stdout

            log.info(
                "Claude Code CLI: success — %d files changed, cost=$%.4f",
                len(changed), cost,
            )
            return {
                "success": True,
                "output": result_text[:5000] if isinstance(result_text, str) else str(result_text)[:5000],
                "files_changed": changed,
                "fallback": False,
                "cost_usd": cost,
            }

        except subprocess.TimeoutExpired:
            log.error("Claude Code CLI timed out after %ds", timeout)
            return {
                "success": False,
                "output": f"Claude Code CLI timed out after {timeout}s",
                "files_changed": [],
                "fallback": True,
            }
        except Exception as e:
            log.error("Claude Code CLI error: %s", e)
            return {
                "success": False,
                "output": f"Claude Code CLI error: {type(e).__name__}: {e}",
                "files_changed": [],
                "fallback": True,
            }

    def _detect_changed_files(self) -> List[str]:
        """Return list of files with uncommitted changes (relative to repo root)."""
        try:
            result = self._git("diff", "--name-only")
            staged = self._git("diff", "--name-only", "--cached")
            files = set(result.stdout.strip().splitlines() + staged.stdout.strip().splitlines())
            return [f for f in files if f]
        except Exception:
            return []

    def mark_stable(self, sha: Optional[str] = None) -> str:
        """Mark a commit as stable (tag it).

        Args:
            sha: Commit SHA to tag (default: HEAD)

        Returns:
            Status message
        """
        if sha is None:
            result = self._git("rev-parse", "HEAD")
            sha = result.stdout.strip()

        tag_name = f"stable-{sha[:8]}-{int(time.time())}"
        try:
            self._git("tag", tag_name, sha)
            log.info("Self-evolution: marked %s as stable (%s)", sha[:8], tag_name)
            return f"Marked {sha[:8]} as stable: {tag_name}"
        except subprocess.CalledProcessError as e:
            return f"Failed to tag: {e.stderr}"


# ═══════════════════════════════════════════════════════════════════
# Self-Modification Cooldown (Session 2)
# ═══════════════════════════════════════════════════════════════════

class SelfModCooldown:
    """Enforce N normal tasks between self-modifications.

    Prevents the agent from entering a self-improvement loop by requiring
    REQUIRED_TASKS productive (non-self-mod) tasks between each self-modification.

    State persisted to ~/ouroboros-data/state/self_mod_cooldown.json.
    """

    REQUIRED_TASKS = 3

    def __init__(self, drive_root: Optional[pathlib.Path] = None):
        self._drive_root = drive_root or DATA_DIR
        self._state_path = self._drive_root / "state" / "self_mod_cooldown.json"

    def _load(self) -> Dict[str, Any]:
        if self._state_path.exists():
            try:
                return json.loads(self._state_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {"normal_tasks_since_last_mod": 0, "last_self_mod_ts": None, "total_self_mods": 0}

    def _save(self, state: Dict[str, Any]) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def can_self_modify(self) -> bool:
        """True if enough normal tasks have run since last self-modification."""
        state = self._load()
        return state["normal_tasks_since_last_mod"] >= self.REQUIRED_TASKS

    def record_self_mod(self) -> None:
        """Record that a self-modification was performed."""
        state = self._load()
        state["normal_tasks_since_last_mod"] = 0
        state["last_self_mod_ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        state["total_self_mods"] = state.get("total_self_mods", 0) + 1
        self._save(state)
        log.info("Self-mod cooldown: recorded self-modification (total: %d)", state["total_self_mods"])

    def record_normal_task(self) -> None:
        """Record that a normal (non-self-mod) task completed."""
        state = self._load()
        state["normal_tasks_since_last_mod"] = state.get("normal_tasks_since_last_mod", 0) + 1
        self._save(state)
        log.info("Self-mod cooldown: normal task recorded (%d/%d)",
                 state["normal_tasks_since_last_mod"], self.REQUIRED_TASKS)

    def status(self) -> Dict[str, Any]:
        """Return cooldown status."""
        state = self._load()
        return {
            "can_self_modify": self.can_self_modify(),
            "normal_tasks_since_last_mod": state["normal_tasks_since_last_mod"],
            "required_tasks": self.REQUIRED_TASKS,
            "last_self_mod_ts": state.get("last_self_mod_ts"),
            "total_self_mods": state.get("total_self_mods", 0),
        }
