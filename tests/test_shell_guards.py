"""D16 — static pattern guard layer for run_shell.

Closes the gap exposed on 2026-04-20 when THAI invoked
``chromadb.PersistentClient(path=...)`` through run_shell, silently
created an empty SQLite, and reported the production ChromaDB as
"empty" to the Shareholder. See
``~/ouroboros-data/CHROMADB_MISMATCH_2026-04-21.md``.

The guard layer is *not* a sandbox — it is a static matcher against a
small, named list of known failure modes. Each pattern listed in
``ouroboros.tools.shell_guards.PATTERNS`` should:

  1. block its dangerous form,
  2. allow at least one nearby legitimate command,
  3. emit a ``run_shell_blocked`` event with the pattern id.

Both unit-level (``check_command``) and integration-level
(``_run_shell`` end-to-end with a real tmp drive_root) coverage live
here so the layer cannot silently regress at either tier.
"""

from __future__ import annotations

import json
import pathlib
import tempfile

import pytest

from ouroboros.tools.registry import ToolContext
from ouroboros.tools.shell import _run_shell
from ouroboros.tools.shell_guards import (
    PATTERNS,
    check_command,
    pattern_ids,
)


# ---------------------------------------------------------------------------
# Pattern table sanity
# ---------------------------------------------------------------------------

def test_pattern_table_is_non_empty_and_unique():
    ids = pattern_ids()
    assert len(ids) >= 4, "expected at least the 4 D16 patterns"
    assert len(set(ids)) == len(ids), f"duplicate pattern ids: {ids}"


def test_every_pattern_has_a_reason():
    for p in PATTERNS:
        assert p.reason.strip(), f"{p.pattern_id} has no reason text"
        assert len(p.reason) >= 40, (
            f"{p.pattern_id} reason looks too terse to help the model "
            f"recover (got {len(p.reason)} chars)"
        )


# ---------------------------------------------------------------------------
# Pattern 1: chromadb.PersistentClient — the 04-20 root cause
# ---------------------------------------------------------------------------

class TestPersistentClientPattern:
    def test_blocks_inline_python_dash_c(self):
        cmd = [
            "python", "-c",
            "import chromadb; chromadb.PersistentClient(path='/tmp/x')",
        ]
        hit = check_command(cmd)
        assert hit is not None
        assert hit[0] == "chromadb_persistent_client"

    def test_blocks_python3_invocation(self):
        cmd = [
            "python3", "-c",
            "from chromadb import PersistentClient; PersistentClient('/x')",
        ]
        hit = check_command(cmd)
        assert hit is not None
        assert hit[0] == "chromadb_persistent_client"

    def test_blocks_when_hidden_in_bash_dash_c(self):
        cmd = [
            "bash", "-c",
            "python -c 'import chromadb; chromadb.PersistentClient(path=\"/x\")'",
        ]
        hit = check_command(cmd)
        assert hit is not None
        assert hit[0] == "chromadb_persistent_client"

    def test_allows_grep_for_persistent_client_string(self):
        # grep is read-only and a legitimate way to audit code for the bug.
        cmd = ["grep", "-rn", "chromadb.PersistentClient", "."]
        assert check_command(cmd) is None

    def test_allows_pytest_running_tests_named_chromadb(self):
        cmd = ["pytest", "tests/test_chromadb_stats.py", "-v"]
        assert check_command(cmd) is None

    def test_allows_python_without_persistent_client(self):
        cmd = ["python", "-c", "print('hello')"]
        assert check_command(cmd) is None

    def test_allows_chromadb_http_client_default_host(self):
        cmd = [
            "python", "-c",
            "import chromadb; chromadb.HttpClient(port=8000)",
        ]
        assert check_command(cmd) is None


# ---------------------------------------------------------------------------
# Pattern 2: chromadb.HttpClient with non-localhost host
# ---------------------------------------------------------------------------

class TestHttpClientRemoteHostPattern:
    def test_blocks_explicit_remote_host(self):
        cmd = [
            "python", "-c",
            "from chromadb import HttpClient; HttpClient(host='evil.example', port=8000)",
        ]
        hit = check_command(cmd)
        assert hit is not None
        assert hit[0] == "chromadb_remote_http_client"

    @pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "::1", "0.0.0.0"])
    def test_allows_localhost_variants(self, host):
        cmd = [
            "python", "-c",
            f"import chromadb; chromadb.HttpClient(host='{host}', port=8000)",
        ]
        assert check_command(cmd) is None

    def test_allows_default_no_host_arg(self):
        cmd = [
            "python", "-c",
            "import chromadb; chromadb.HttpClient(port=8000)",
        ]
        assert check_command(cmd) is None


# ---------------------------------------------------------------------------
# Pattern 3: rm -rf on critical paths
# ---------------------------------------------------------------------------

class TestCriticalRmPattern:
    @pytest.mark.parametrize("target", [
        "/home/deploy/ouroboros-data/memory",
        "/home/deploy/ouroboros-data",
        "ouroboros-data",
        "ouroboros-data/state",
        ".git",
        "./.git",
        "chroma_data",
        "chromadb",
        "memory",
        "task_results",
    ])
    def test_blocks_direct_rm_rf_critical(self, target):
        cmd = ["rm", "-rf", target]
        hit = check_command(cmd)
        assert hit is not None, f"expected block for {target!r}"
        assert hit[0] == "rm_rf_critical_path"

    def test_blocks_rm_rf_via_bash_c(self):
        cmd = ["bash", "-c", "rm -rf /home/deploy/ouroboros-data/memory"]
        hit = check_command(cmd)
        assert hit is not None
        assert hit[0] == "rm_rf_critical_path"

    def test_blocks_rm_fr_alternate_flag_order(self):
        cmd = ["rm", "-fr", ".git"]
        hit = check_command(cmd)
        assert hit is not None
        assert hit[0] == "rm_rf_critical_path"

    def test_allows_rm_rf_node_modules(self):
        cmd = ["rm", "-rf", "node_modules"]
        assert check_command(cmd) is None

    def test_allows_rm_rf_build_dir(self):
        cmd = ["rm", "-rf", "company/vendor-lens/frontend/.next"]
        assert check_command(cmd) is None

    def test_allows_rm_single_file(self):
        # Not recursive — guard does not fire.
        cmd = ["rm", ".env.example"]
        assert check_command(cmd) is None

    def test_does_not_match_substring_inside_filename(self):
        # `memory_handler.py` should NOT trigger the bare-`memory` token.
        cmd = ["rm", "-rf", "src/memory_handler.py.bak"]
        assert check_command(cmd) is None


# ---------------------------------------------------------------------------
# Pattern 4: .env mutations via shell
# ---------------------------------------------------------------------------

class TestEnvMutationPattern:
    def test_blocks_sed_inplace(self):
        cmd = ["sed", "-i", "s/FOO=1/FOO=2/", ".env"]
        hit = check_command(cmd)
        assert hit is not None
        assert hit[0] == "env_shell_mutation"

    def test_blocks_redirect_via_bash_c(self):
        cmd = ["bash", "-c", "echo NEW_KEY=value >> .env"]
        hit = check_command(cmd)
        assert hit is not None
        assert hit[0] == "env_shell_mutation"

    def test_blocks_tee(self):
        cmd = ["tee", ".env"]
        hit = check_command(cmd)
        assert hit is not None
        assert hit[0] == "env_shell_mutation"

    def test_blocks_mv_overwriting(self):
        cmd = ["mv", "/tmp/new.env", ".env"]
        hit = check_command(cmd)
        assert hit is not None
        assert hit[0] == "env_shell_mutation"

    def test_blocks_rm_against_env(self):
        cmd = ["rm", ".env"]
        hit = check_command(cmd)
        assert hit is not None
        assert hit[0] == "env_shell_mutation"

    def test_allows_reading_env(self):
        cmd = ["cat", ".env"]
        assert check_command(cmd) is None

    def test_allows_grep_against_env(self):
        cmd = ["grep", "OPENROUTER", ".env"]
        assert check_command(cmd) is None

    def test_allows_unrelated_dotfile(self):
        cmd = ["sed", "-i", "s/x/y/", ".gitignore"]
        assert check_command(cmd) is None


# ---------------------------------------------------------------------------
# Negative cases — common legitimate commands must pass.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cmd", [
    ["echo", "hello"],
    ["git", "status"],
    ["git", "log", "-1", "--oneline"],
    ["pytest", "-x"],
    ["pytest", "tests/test_smoke.py"],
    ["python", "-c", "print(1+1)"],
    ["python", "-V"],
    ["systemctl", "status", "caddy"],
    ["docker", "compose", "ps"],
    ["ls", "-la"],
    ["curl", "-s", "http://localhost:8000/api/v1/heartbeat"],
])
def test_legitimate_commands_pass(cmd):
    assert check_command(cmd) is None, f"false positive on legitimate cmd: {cmd}"


# ---------------------------------------------------------------------------
# E2E — _run_shell refuses + writes run_shell_blocked event
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_ctx():
    tmp = pathlib.Path(tempfile.mkdtemp())
    (tmp / "logs").mkdir()
    return ToolContext(repo_dir=tmp, drive_root=tmp)


def _read_events(ctx: ToolContext):
    path = ctx.drive_logs() / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_run_shell_refuses_persistent_client_and_logs_event(tmp_ctx):
    """The 04-20 incident, replayed end-to-end against the live _run_shell."""
    out = _run_shell(
        tmp_ctx,
        cmd=[
            "python", "-c",
            "import chromadb; chromadb.PersistentClient(path='/tmp/x')",
        ],
    )
    assert out.startswith("⚠️ SHELL_BLOCKED:")
    assert "chromadb_persistent_client" in out

    events = _read_events(tmp_ctx)
    blocked = [e for e in events if e.get("type") == "run_shell_blocked"]
    assert len(blocked) == 1, f"expected exactly 1 block event, got {events}"
    ev = blocked[0]
    assert ev["pattern_id"] == "chromadb_persistent_client"
    assert ev["tool"] == "run_shell"
    assert "PersistentClient" in ev["cmd_preview"]
    assert "ts" in ev


def test_run_shell_refuses_rm_rf_ouroboros_data(tmp_ctx):
    out = _run_shell(tmp_ctx, cmd=["rm", "-rf", "/home/deploy/ouroboros-data"])
    assert out.startswith("⚠️ SHELL_BLOCKED:")
    assert "rm_rf_critical_path" in out

    blocked = [e for e in _read_events(tmp_ctx) if e.get("type") == "run_shell_blocked"]
    assert len(blocked) == 1
    assert blocked[0]["pattern_id"] == "rm_rf_critical_path"


def test_run_shell_executes_legitimate_command(tmp_ctx):
    """Sanity: the guard does not break baseline run_shell behavior."""
    out = _run_shell(tmp_ctx, cmd=["echo", "ouroboros"])
    assert "ouroboros" in out
    assert "SHELL_BLOCKED" not in out

    blocked = [e for e in _read_events(tmp_ctx) if e.get("type") == "run_shell_blocked"]
    assert blocked == []
