"""
Unit tests for ouroboros.experiment_engine — behavioral experiment lifecycle.

Mocks ChromaDB, LLM, and file system to test full cycle, safety constraints,
measurement, revert, and verdict logic.
"""

import json
import pytest
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from ouroboros.experiment_engine import ExperimentEngine, _utcnow, _save_json


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_data_dir(tmpdir: Path) -> Path:
    """Create data directory structure with sample task results."""
    data_dir = tmpdir / "ouroboros-data"
    (data_dir / "task_results").mkdir(parents=True)
    (data_dir / "state").mkdir(parents=True)
    (data_dir / "memory" / "knowledge").mkdir(parents=True)
    (data_dir / "memory").mkdir(parents=True, exist_ok=True)
    # Create wisdom.md
    (data_dir / "memory" / "wisdom.md").write_text("# Wisdom\n", encoding="utf-8")
    return data_dir


def _seed_task_results(data_dir: Path, count: int = 15, **overrides):
    """Seed task result files."""
    results_dir = data_dir / "task_results"
    for i in range(count):
        data = {
            "task_id": f"task_{i:03d}",
            "status": "completed",
            "result": "deploy the application to production server",
            "cost_usd": 0.50,
            "total_rounds": 10,
            "ts": datetime.now(tz=timezone.utc).isoformat(),
        }
        data.update(overrides)
        (results_dir / f"task_{i:03d}.json").write_text(
            json.dumps(data), encoding="utf-8"
        )


def _mock_skill_manager():
    """Create a mock SkillManager with mock ChromaDB collection."""
    sm = MagicMock()
    col = MagicMock()
    col.count.return_value = 0
    col.peek.return_value = {"documents": []}
    sm._skills_col = col
    sm.find_duplicate.return_value = None
    return sm, col


def _mock_llm_client(hypothesis=None):
    """Create a mock LLMClient that returns a hypothesis."""
    llm = MagicMock()
    if hypothesis is None:
        hypothesis = {
            "hypothesis": "If deploy tasks start with status check, avg_rounds will drop from 10 to 4",
            "action_type": "save_skill",
            "action_content": "SKILL: deploy-with-precheck\n1. Check service status\n2. Deploy\n3. Verify",
            "action_name": "deploy-with-precheck",
            "metric": "avg_rounds",
            "baseline": 10.0,
            "target": 4.0,
            "max_tasks": 5,
            "max_days": 3,
        }
    llm.chat.return_value = (
        {"content": json.dumps(hypothesis)},
        {"prompt_tokens": 300, "completion_tokens": 150, "cost": 0.001},
    )
    return llm


# ---------------------------------------------------------------------------
# Tests: Safety constraints
# ---------------------------------------------------------------------------

class TestCanStartNew:

    def test_allows_when_no_experiments(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(Path(tmpdir))
            sm, _ = _mock_skill_manager()
            engine = ExperimentEngine(data_dir, sm, _mock_llm_client())
            assert engine.can_start_new() is True

    def test_blocks_when_max_concurrent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(Path(tmpdir))
            sm, _ = _mock_skill_manager()
            engine = ExperimentEngine(data_dir, sm, _mock_llm_client())

            # Add 2 active experiments
            for i in range(2):
                engine.state["experiments"].append({
                    "id": f"exp_{i:03d}",
                    "status": "active",
                })
            assert engine.can_start_new() is False

    def test_blocks_during_cooldown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(Path(tmpdir))
            sm, _ = _mock_skill_manager()
            engine = ExperimentEngine(data_dir, sm, _mock_llm_client())

            # Set last experiment started recently
            engine.state["last_experiment_started"] = _utcnow().isoformat()
            assert engine.can_start_new() is False

    def test_blocks_post_conclusion_cooldown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(Path(tmpdir))
            sm, _ = _mock_skill_manager()
            engine = ExperimentEngine(data_dir, sm, _mock_llm_client())

            engine.state["completed"] = [{
                "concluded": _utcnow().isoformat(),
            }]
            assert engine.can_start_new() is False

    def test_allows_after_cooldown_expires(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(Path(tmpdir))
            sm, _ = _mock_skill_manager()
            engine = ExperimentEngine(data_dir, sm, _mock_llm_client())

            old_time = (_utcnow() - timedelta(days=2)).isoformat()
            engine.state["last_experiment_started"] = old_time
            engine.state["completed"] = [{
                "concluded": (_utcnow() - timedelta(hours=5)).isoformat(),
            }]
            assert engine.can_start_new() is True


# ---------------------------------------------------------------------------
# Tests: Full cycle
# ---------------------------------------------------------------------------

class TestRunFullCycle:

    def test_returns_none_with_few_tasks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(Path(tmpdir))
            _seed_task_results(data_dir, count=5)
            sm, _ = _mock_skill_manager()
            engine = ExperimentEngine(data_dir, sm, _mock_llm_client())

            result = engine.run_full_cycle()
            assert result is None

    def test_starts_experiment_with_enough_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(Path(tmpdir))
            _seed_task_results(data_dir, count=15)
            sm, col = _mock_skill_manager()
            engine = ExperimentEngine(data_dir, sm, _mock_llm_client())

            exp_id = engine.run_full_cycle()

            assert exp_id is not None
            assert exp_id.startswith("exp_")
            assert len(engine.state["experiments"]) == 1
            assert engine.state["experiments"][0]["status"] == "active"
            # Verify skill was saved
            col.add.assert_called_once()

    def test_respects_analysis_cooldown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(Path(tmpdir))
            _seed_task_results(data_dir, count=15)
            sm, _ = _mock_skill_manager()
            engine = ExperimentEngine(data_dir, sm, _mock_llm_client())

            # Set analysis as done recently
            engine.state["last_analysis"] = _utcnow().isoformat()
            engine._save_state()

            result = engine.run_full_cycle()
            assert result is None

    def test_skips_when_hypothesis_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(Path(tmpdir))
            _seed_task_results(data_dir, count=15)
            sm, _ = _mock_skill_manager()
            llm = _mock_llm_client({"skip": True, "reason": "No clear improvement"})
            engine = ExperimentEngine(data_dir, sm, llm)

            result = engine.run_full_cycle()
            assert result is None


# ---------------------------------------------------------------------------
# Tests: Hypothesis generation
# ---------------------------------------------------------------------------

class TestGenerateHypothesis:

    def test_validates_action_type(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(Path(tmpdir))
            sm, _ = _mock_skill_manager()
            bad_hypothesis = {
                "hypothesis": "Modify agent.py",
                "action_type": "modify_code",  # forbidden
                "action_content": "...",
                "action_name": "bad-action",
                "metric": "avg_rounds",
                "baseline": 10, "target": 5,
            }
            llm = _mock_llm_client(bad_hypothesis)
            engine = ExperimentEngine(data_dir, sm, llm)

            result = engine._generate_hypothesis({"sample_task_ids": [], "group": "test"})
            assert result is None

    def test_handles_llm_parse_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(Path(tmpdir))
            sm, _ = _mock_skill_manager()
            llm = MagicMock()
            llm.chat.return_value = (
                {"content": "not valid json at all"},
                {"cost": 0.001},
            )
            engine = ExperimentEngine(data_dir, sm, llm)

            result = engine._generate_hypothesis({"sample_task_ids": [], "group": "test"})
            assert result is None


# ---------------------------------------------------------------------------
# Tests: Action execution
# ---------------------------------------------------------------------------

class TestExecuteAction:

    def test_save_skill(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(Path(tmpdir))
            sm, col = _mock_skill_manager()
            engine = ExperimentEngine(data_dir, sm, _mock_llm_client())

            hypothesis = {
                "action_type": "save_skill",
                "action_content": "SKILL: test\n1. Do thing",
                "action_name": "test-skill",
            }
            action_id = engine._execute_action(hypothesis)
            assert action_id is not None
            col.add.assert_called_once()

    def test_add_knowledge(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(Path(tmpdir))
            sm, _ = _mock_skill_manager()
            engine = ExperimentEngine(data_dir, sm, _mock_llm_client())

            hypothesis = {
                "action_type": "add_knowledge",
                "action_content": "Always check service status before deploy.",
                "action_name": "deploy-rule",
            }
            action_id = engine._execute_action(hypothesis)
            assert action_id is not None
            assert Path(action_id).exists()
            assert "deploy-rule.md" in action_id

    def test_save_skill_fails_without_chromadb(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(Path(tmpdir))
            sm, _ = _mock_skill_manager()
            sm._skills_col = None
            engine = ExperimentEngine(data_dir, sm, _mock_llm_client())

            hypothesis = {
                "action_type": "save_skill",
                "action_content": "SKILL: test",
                "action_name": "test",
            }
            assert engine._execute_action(hypothesis) is None


# ---------------------------------------------------------------------------
# Tests: Measurement + conclusion
# ---------------------------------------------------------------------------

class TestMeasurement:

    def _make_engine_with_active_exp(self, tmpdir):
        data_dir = _make_data_dir(Path(tmpdir))
        sm, col = _mock_skill_manager()
        engine = ExperimentEngine(data_dir, sm, _mock_llm_client())

        exp = {
            "id": "exp_000",
            "status": "active",
            "hypothesis": "Deploy tasks should be faster",
            "action_type": "save_skill",
            "action_name": "deploy-with-precheck",
            "action_id": "skill-uuid-123",
            "metric": "avg_rounds",
            "baseline": 10.0,
            "target": 4.0,
            "group": "task:deploy",
            "max_tasks": 3,
            "max_days": 3,
            "started": _utcnow().isoformat(),
            "expires": (_utcnow() + timedelta(days=3)).isoformat(),
            "matching_tasks": [],
            "verdict": None,
        }
        engine.state["experiments"].append(exp)
        return engine, col

    def test_records_matching_task(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine, _ = self._make_engine_with_active_exp(tmpdir)

            task = {
                "task": "deploy the application",
                "rounds": 4,
                "cost": 0.10,
                "success": True,
                "task_id": "t1",
            }
            engine.record_task_for_experiments(task)

            exp = engine.state["experiments"][0]
            assert len(exp["matching_tasks"]) == 1
            assert exp["matching_tasks"][0]["rounds"] == 4

    def test_ignores_non_matching_task(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine, _ = self._make_engine_with_active_exp(tmpdir)

            task = {
                "task": "analyze some data",
                "rounds": 4,
                "cost": 0.10,
                "success": True,
                "task_id": "t1",
            }
            engine.record_task_for_experiments(task)

            exp = engine.state["experiments"][0]
            assert len(exp["matching_tasks"]) == 0

    def test_concludes_when_enough_data_confirmed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine, _ = self._make_engine_with_active_exp(tmpdir)

            # Record 3 tasks that beat the target
            for i in range(3):
                engine.record_task_for_experiments({
                    "task": "deploy the application",
                    "rounds": 3,  # below target of 4
                    "cost": 0.05,
                    "success": True,
                    "task_id": f"t{i}",
                })

            assert len(engine.state["experiments"]) == 0
            assert len(engine.state["completed"]) == 1
            assert engine.state["completed"][0]["status"] == "confirmed"

    def test_concludes_failed_and_reverts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine, col = self._make_engine_with_active_exp(tmpdir)

            # Record 3 tasks worse than baseline
            for i in range(3):
                engine.record_task_for_experiments({
                    "task": "deploy the application",
                    "rounds": 12,  # worse than baseline of 10
                    "cost": 0.60,
                    "success": True,
                    "task_id": f"t{i}",
                })

            assert engine.state["completed"][0]["status"] == "failed"
            # Should have tried to delete the skill
            col.delete.assert_called_once_with(ids=["skill-uuid-123"])

    def test_concludes_partial(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine, col = self._make_engine_with_active_exp(tmpdir)

            # Record tasks better than baseline but not meeting target
            for i in range(3):
                engine.record_task_for_experiments({
                    "task": "deploy the application",
                    "rounds": 7,  # better than 10 baseline, worse than 4 target
                    "cost": 0.30,
                    "success": True,
                    "task_id": f"t{i}",
                })

            assert engine.state["completed"][0]["status"] == "partial"
            col.delete.assert_not_called()

    def test_concludes_expired_inconclusive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine, _ = self._make_engine_with_active_exp(tmpdir)

            # Make experiment expired
            engine.state["experiments"][0]["expires"] = (
                _utcnow() - timedelta(hours=1)
            ).isoformat()

            # Any task triggers expiry check
            engine.record_task_for_experiments({
                "task": "deploy something",
                "rounds": 5,
                "cost": 0.10,
                "success": True,
                "task_id": "t1",
            })

            assert engine.state["completed"][0]["status"] == "inconclusive"

    def test_records_confirmed_in_wisdom(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine, _ = self._make_engine_with_active_exp(tmpdir)

            for i in range(3):
                engine.record_task_for_experiments({
                    "task": "deploy the application",
                    "rounds": 3,
                    "cost": 0.05,
                    "success": True,
                    "task_id": f"t{i}",
                })

            wisdom = (engine.data_dir / "memory" / "wisdom.md").read_text()
            assert "CONFIRMED" in wisdom
            assert "exp_000" in wisdom


# ---------------------------------------------------------------------------
# Tests: State persistence
# ---------------------------------------------------------------------------

class TestStatePersistence:

    def test_saves_and_loads_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(Path(tmpdir))
            sm, _ = _mock_skill_manager()
            engine1 = ExperimentEngine(data_dir, sm, _mock_llm_client())

            engine1.state["last_analysis"] = "2026-04-01T10:00:00+00:00"
            engine1._save_state()

            engine2 = ExperimentEngine(data_dir, sm, _mock_llm_client())
            assert engine2.state["last_analysis"] == "2026-04-01T10:00:00+00:00"


# ---------------------------------------------------------------------------
# Tests: Query helpers
# ---------------------------------------------------------------------------

class TestQueryHelpers:

    def test_get_experiment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(Path(tmpdir))
            sm, _ = _mock_skill_manager()
            engine = ExperimentEngine(data_dir, sm, _mock_llm_client())

            engine.state["experiments"].append({"id": "exp_001", "status": "active"})
            engine.state["completed"].append({"id": "exp_000", "status": "confirmed"})

            assert engine.get_experiment("exp_001")["status"] == "active"
            assert engine.get_experiment("exp_000")["status"] == "confirmed"
            assert engine.get_experiment("exp_999") is None

    def test_get_recently_concluded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(Path(tmpdir))
            sm, _ = _mock_skill_manager()
            engine = ExperimentEngine(data_dir, sm, _mock_llm_client())

            engine.state["completed"] = [
                {"id": "exp_old", "concluded": (_utcnow() - timedelta(hours=48)).isoformat()},
                {"id": "exp_new", "concluded": _utcnow().isoformat()},
            ]

            recent = engine.get_recently_concluded(hours=24)
            assert len(recent) == 1
            assert recent[0]["id"] == "exp_new"

    def test_get_active_experiments(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(Path(tmpdir))
            sm, _ = _mock_skill_manager()
            engine = ExperimentEngine(data_dir, sm, _mock_llm_client())

            engine.state["experiments"] = [
                {"id": "exp_001", "status": "active"},
                {"id": "exp_002", "status": "expired"},
            ]
            assert len(engine.get_active_experiments()) == 1


# ---------------------------------------------------------------------------
# Tests: Revert
# ---------------------------------------------------------------------------

class TestRevert:

    def test_revert_skill(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(Path(tmpdir))
            sm, col = _mock_skill_manager()
            engine = ExperimentEngine(data_dir, sm, _mock_llm_client())

            exp = {"action_type": "save_skill", "action_id": "skill-123"}
            engine._revert_action(exp)
            col.delete.assert_called_once_with(ids=["skill-123"])

    def test_revert_knowledge(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = _make_data_dir(Path(tmpdir))
            sm, _ = _mock_skill_manager()
            engine = ExperimentEngine(data_dir, sm, _mock_llm_client())

            # Create a knowledge file then revert it
            kpath = data_dir / "memory" / "knowledge" / "test-rule.md"
            kpath.write_text("test content")

            exp = {"action_type": "add_knowledge", "action_id": str(kpath)}
            engine._revert_action(exp)
            assert not kpath.exists()
