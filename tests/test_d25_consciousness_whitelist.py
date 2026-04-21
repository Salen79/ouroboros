"""D25 regression: consciousness thread must not be able to overwrite identity.md.

Fix reference: ARCHITECTURE_MAP_2026-04-21.md §7 D25 and §5.2.
Incident: identity.md corruption on 2026-04-12 via the light-model
background cycle. update_identity was in _BG_TOOL_WHITELIST at
consciousness.py:1281 — removed in this commit.

Main task loop retains update_identity via normal ToolRegistry dispatch;
these tests only cover the consciousness path.
"""

import hashlib
import json
import os
import queue
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ouroboros.consciousness import BackgroundConsciousness as Consciousness


IDENTITY_FIXTURE = "# Identity\n\nI am THAI.\nI do not get rewritten by a background thread.\n"


def _make_consciousness(tmpdir: Path):
    drive_root = tmpdir / "ouroboros-data"
    drive_root.mkdir(exist_ok=True)
    (drive_root / "logs").mkdir(exist_ok=True)
    (drive_root / "state").mkdir(exist_ok=True)
    (drive_root / "memory").mkdir(exist_ok=True)

    (drive_root / "state" / "state.json").write_text(json.dumps({"spent_usd": 0.0}))
    (drive_root / "memory" / "scratchpad.md").write_text("scratch")
    (drive_root / "memory" / "identity.md").write_text(IDENTITY_FIXTURE)

    repo_dir = tmpdir / "repo"
    repo_dir.mkdir(exist_ok=True)

    env = {"TOTAL_BUDGET": "500", "STRATEGIC_PLANNER_ENABLED": "true"}
    with patch.dict(os.environ, env), \
         patch("ouroboros.consciousness.LLMClient"), \
         patch.object(Consciousness, "_build_registry", return_value=MagicMock()):
        c = Consciousness(
            drive_root=drive_root,
            repo_dir=repo_dir,
            event_queue=queue.Queue(),
            owner_chat_id_fn=lambda: 12345,
        )
    return c, drive_root


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ── Unit tests ─────────────────────────────────────────────────────────

def test_update_identity_not_in_whitelist():
    """The constant is the single source of truth — assert directly."""
    assert "update_identity" not in Consciousness._BG_TOOL_WHITELIST
    # Sanity: sibling tools we DO want are still present.
    assert "update_scratchpad" in Consciousness._BG_TOOL_WHITELIST
    assert "send_owner_message" in Consciousness._BG_TOOL_WHITELIST


def test_update_identity_call_returns_deny_and_preserves_file(tmp_path):
    """
    E2E on the enforcement point: _execute_tool must reject update_identity
    without touching identity.md. Mirrors a real tool call shape from the
    LLM: {"function": {"name": ..., "arguments": <json-str>}}.
    """
    c, drive_root = _make_consciousness(tmp_path)
    identity_path = drive_root / "memory" / "identity.md"

    before_hash = _hash(identity_path)
    before_content = identity_path.read_text()

    tc = {
        "function": {
            "name": "update_identity",
            "arguments": json.dumps({"content": "# Pwned\nI am something else now.\n"}),
        },
    }
    result = c._execute_tool(tc, [])

    assert "not available" in result.lower()
    assert "update_identity" in result

    assert _hash(identity_path) == before_hash
    assert identity_path.read_text() == before_content


def test_tool_schemas_excludes_update_identity(tmp_path):
    """The schemas the LLM sees must not advertise update_identity."""
    c, _ = _make_consciousness(tmp_path)

    # _build_registry was mocked in the helper; supply a registry with a
    # schema for update_identity so the filter is what actually excludes it.
    fake_schemas = [
        {"type": "function", "function": {"name": "update_identity"}},
        {"type": "function", "function": {"name": "update_scratchpad"}},
        {"type": "function", "function": {"name": "send_owner_message"}},
    ]
    fake_registry = MagicMock()
    fake_registry.schemas.return_value = fake_schemas
    c._registry = fake_registry

    names = {s["function"]["name"] for s in c._tool_schemas()}
    assert "update_identity" not in names
    assert "update_scratchpad" in names
    assert "send_owner_message" in names


def test_identity_read_path_unaffected(tmp_path):
    """Consciousness reads identity.md by direct file read, not via a tool.
    That path must continue to work after the whitelist change."""
    c, drive_root = _make_consciousness(tmp_path)

    # Minimal dependencies for _build_context. We only care that the method
    # completes and includes the identity content.
    ctx = c._build_context()
    assert "I am THAI." in ctx
