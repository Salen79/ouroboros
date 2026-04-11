"""Unit tests for strategic plan budget guard (D) at 95% threshold."""

import json
import os
import queue
from pathlib import Path
from unittest.mock import MagicMock, patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from ouroboros.consciousness import BackgroundConsciousness as Consciousness


# ── Helpers ────────────────────────────────────────────────────────────

def _make_consciousness(tmpdir: Path, env_overrides: dict = None):
    """Create a Consciousness instance with mocked dependencies."""
    drive_root = tmpdir / "ouroboros-data"
    drive_root.mkdir(exist_ok=True)
    (drive_root / "logs").mkdir(exist_ok=True)
    (drive_root / "state").mkdir(exist_ok=True)
    (drive_root / "memory").mkdir(exist_ok=True)

    (drive_root / "state" / "state.json").write_text(json.dumps({"spent_usd": 100.0}))
    (drive_root / "memory" / "scratchpad.md").write_text("test")

    repo_dir = tmpdir / "repo"
    repo_dir.mkdir(exist_ok=True)

    env = {"TOTAL_BUDGET": "500", "STRATEGIC_PLANNER_ENABLED": "true", **(env_overrides or {})}

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


def _write_state(drive_root: Path, spent_usd: float):
    """Write state.json with given spent amount — same type as production (float)."""
    (drive_root / "state" / "state.json").write_text(
        json.dumps({"spent_usd": spent_usd})
    )


def _read_events(drive_root: Path) -> list:
    """Read events from events.jsonl."""
    path = drive_root / "logs" / "events.jsonl"
    if not path.exists():
        return []
    events = []
    for line in path.read_text().strip().split("\n"):
        if line.strip():
            events.append(json.loads(line))
    return events


def _plan_was_generated(drive_root: Path) -> bool:
    """Check if strategic_plan_generated event was written."""
    return any(e.get("type") == "strategic_plan_generated" for e in _read_events(drive_root))


def _plan_was_blocked(drive_root: Path) -> bool:
    """Check if strategic_plan_blocked_budget event was written."""
    return any(e.get("type") == "strategic_plan_blocked_budget" for e in _read_events(drive_root))


class FakePlan:
    def __init__(self, tasks):
        self.tasks = tasks

class FakeTask:
    def __init__(self, title, description="test", category="maintenance",
                 est_cost=1.0, requires_gate=False, gate_reason=""):
        self.title = title
        self.description = description
        self.category = category
        self.est_cost = est_cost
        self.requires_gate = requires_gate
        self.gate_reason = gate_reason


# ── Tests ─────────────────────────────────────────────────────────────

class TestBudgetGuard:
    def test_blocks_above_95pct(self, tmp_path):
        """spent=476, total=500 → 95.2% → blocked."""
        c, drive_root = _make_consciousness(tmp_path)
        _write_state(drive_root, 476.0)

        c._last_plan_ts = 0
        with patch.dict(os.environ, {"TOTAL_BUDGET": "500", "STRATEGIC_PLANNER_ENABLED": "true"}):
            with patch("supervisor.workers.RUNNING", []), \
                 patch("supervisor.workers.PENDING", []):
                c._maybe_strategic_plan()

        assert not _plan_was_generated(drive_root)
        assert _plan_was_blocked(drive_root)

    def test_allows_below_95pct(self, tmp_path):
        """spent=470, total=500 → 94% → allowed."""
        c, drive_root = _make_consciousness(tmp_path)
        _write_state(drive_root, 470.0)

        c._last_plan_ts = 0
        fake_plan = FakePlan([FakeTask("Test task")])

        with patch.dict(os.environ, {"TOTAL_BUDGET": "500", "STRATEGIC_PLANNER_ENABLED": "true"}):
            with patch("supervisor.workers.RUNNING", []), \
                 patch("supervisor.workers.PENDING", []):
                with patch("ouroboros.strategic_planner.StrategicPlanner") as mock_sp:
                    mock_sp.return_value.generate_plan.return_value = fake_plan
                    mock_sp.return_value.format_telegram_summary.return_value = "plan"
                    c._maybe_strategic_plan()

        assert _plan_was_generated(drive_root)
        assert not _plan_was_blocked(drive_root)

    def test_blocks_at_exact_95pct(self, tmp_path):
        """spent=475, total=500 → exactly 95% → blocked (>= threshold)."""
        c, drive_root = _make_consciousness(tmp_path)
        _write_state(drive_root, 475.0)

        c._last_plan_ts = 0
        with patch.dict(os.environ, {"TOTAL_BUDGET": "500", "STRATEGIC_PLANNER_ENABLED": "true"}):
            with patch("supervisor.workers.RUNNING", []), \
                 patch("supervisor.workers.PENDING", []):
                c._maybe_strategic_plan()

        assert not _plan_was_generated(drive_root)
        assert _plan_was_blocked(drive_root)

    def test_logs_blocked_event_with_correct_values(self, tmp_path):
        """When blocked, event should contain spent and threshold values."""
        c, drive_root = _make_consciousness(tmp_path)
        _write_state(drive_root, 490.0)

        c._last_plan_ts = 0
        with patch.dict(os.environ, {"TOTAL_BUDGET": "500", "STRATEGIC_PLANNER_ENABLED": "true"}):
            with patch("supervisor.workers.RUNNING", []), \
                 patch("supervisor.workers.PENDING", []):
                c._maybe_strategic_plan()

        blocked = [e for e in _read_events(drive_root) if e.get("type") == "strategic_plan_blocked_budget"]
        assert len(blocked) == 1
        assert blocked[0]["spent"] == 490.0
        assert blocked[0]["threshold"] == 475.0  # 500 * 0.95

    def test_graceful_on_missing_state(self, tmp_path):
        """If state.json doesn't exist, guard should not block (fail-open)."""
        c, drive_root = _make_consciousness(tmp_path)
        (drive_root / "state" / "state.json").unlink()

        c._last_plan_ts = 0
        fake_plan = FakePlan([FakeTask("Test")])

        with patch.dict(os.environ, {"TOTAL_BUDGET": "500", "STRATEGIC_PLANNER_ENABLED": "true"}):
            with patch("supervisor.workers.RUNNING", []), \
                 patch("supervisor.workers.PENDING", []):
                with patch("ouroboros.strategic_planner.StrategicPlanner") as mock_sp:
                    mock_sp.return_value.generate_plan.return_value = fake_plan
                    mock_sp.return_value.format_telegram_summary.return_value = "p"
                    c._maybe_strategic_plan()

        assert _plan_was_generated(drive_root)

    def test_graceful_on_zero_budget(self, tmp_path):
        """If TOTAL_BUDGET=0, guard should not block (no budget configured)."""
        c, drive_root = _make_consciousness(tmp_path)
        _write_state(drive_root, 999.0)

        c._last_plan_ts = 0
        fake_plan = FakePlan([FakeTask("Test")])

        with patch.dict(os.environ, {"TOTAL_BUDGET": "0", "STRATEGIC_PLANNER_ENABLED": "true"}):
            with patch("supervisor.workers.RUNNING", []), \
                 patch("supervisor.workers.PENDING", []):
                with patch("ouroboros.strategic_planner.StrategicPlanner") as mock_sp:
                    mock_sp.return_value.generate_plan.return_value = fake_plan
                    mock_sp.return_value.format_telegram_summary.return_value = "p"
                    c._maybe_strategic_plan()

        assert _plan_was_generated(drive_root)


# ── Kill switch tests ─────────────────────────────────────────────────

class TestKillSwitch:
    def test_disabled_by_default(self, tmp_path):
        """When STRATEGIC_PLANNER_ENABLED is unset, planner should not run."""
        c, drive_root = _make_consciousness(tmp_path)

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("STRATEGIC_PLANNER_ENABLED", None)
            c._maybe_strategic_plan()

        assert not _plan_was_generated(drive_root)
        events = _read_events(drive_root)
        disabled = [e for e in events if e.get("type") == "strategic_planner_disabled"]
        assert len(disabled) == 1
        assert disabled[0]["reason"] == "env_guard"

    def test_explicitly_false(self, tmp_path):
        """When STRATEGIC_PLANNER_ENABLED=false, planner should not run."""
        c, drive_root = _make_consciousness(tmp_path)

        with patch.dict(os.environ, {"STRATEGIC_PLANNER_ENABLED": "false"}):
            c._maybe_strategic_plan()

        assert not _plan_was_generated(drive_root)
        events = _read_events(drive_root)
        disabled = [e for e in events if e.get("type") == "strategic_planner_disabled"]
        assert len(disabled) == 1

    def test_enabled_when_true(self, tmp_path):
        """When STRATEGIC_PLANNER_ENABLED=true, planner should proceed."""
        c, drive_root = _make_consciousness(tmp_path)
        _write_state(drive_root, 100.0)

        c._last_plan_ts = 0
        fake_plan = FakePlan([FakeTask("Test")])

        with patch.dict(os.environ, {"TOTAL_BUDGET": "500", "STRATEGIC_PLANNER_ENABLED": "true"}):
            with patch("supervisor.workers.RUNNING", []), \
                 patch("supervisor.workers.PENDING", []):
                with patch("ouroboros.strategic_planner.StrategicPlanner") as mock_sp:
                    mock_sp.return_value.generate_plan.return_value = fake_plan
                    mock_sp.return_value.format_telegram_summary.return_value = "p"
                    c._maybe_strategic_plan()

        assert _plan_was_generated(drive_root)
        events = _read_events(drive_root)
        disabled = [e for e in events if e.get("type") == "strategic_planner_disabled"]
        assert len(disabled) == 0
