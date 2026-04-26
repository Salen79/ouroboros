"""D2 — SkillManager + ExperimentEngine emit lifecycle events to events.jsonl.

Before this fix neither class wrote to the events stream, so consciousness
metrics (`meta_cognition.skills_created_today`, experiment counters) sat at
zero even when the underlying state files showed activity.

Tests inject a list-backed ``event_emit_fn`` and assert the right event types
are produced for each lifecycle transition.
"""
from __future__ import annotations

import pathlib
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# SkillManager
# ---------------------------------------------------------------------------

def _mock_collection():
    col = MagicMock()
    col.count.return_value = 0
    col.query.return_value = {
        "ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]],
    }
    col.get.return_value = {"ids": [], "metadatas": [], "documents": []}
    return col


def _mock_llm(name="my-skill"):
    llm = MagicMock()
    llm.chat.return_value = (
        {"content":
            '{"name": "' + name + '", '
            '"description": "do thing", '
            '"steps": ["a", "b"], '
            '"tools_used": ["run_shell"]}'},
        {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.001},
    )
    return llm


def _task_result(**overrides):
    base = {
        "task": "do the thing",
        "result": "done",
        "rounds": 5,
        "success": True,
        "task_type": "task",
        "tool_calls": [{"tool": "run_shell", "args": {"command": "ls"}}],
        "timestamp": "2026-04-26T10:00:00Z",
    }
    base.update(overrides)
    return base


def test_skill_manager_emits_skill_extracted_on_new_skill():
    from ouroboros.skill_manager import SkillManager

    client = MagicMock()
    col = _mock_collection()
    client.get_or_create_collection.return_value = col

    events: list[dict] = []
    sm = SkillManager(
        chromadb_client=client,
        llm_client=_mock_llm("brand-new-skill"),
        event_emit_fn=events.append,
    )
    sm._skills_col = col

    out = sm.process_completed_task(_task_result(rounds=5))

    assert out and out.startswith("new:")
    extracted = [e for e in events if e["type"] == "skill_extracted"]
    assert len(extracted) == 1
    assert extracted[0]["skill_name"] == "brand-new-skill"
    assert extracted[0]["updated"] is False
    assert extracted[0]["rounds"] == 5
    assert "ts" in extracted[0]


def test_skill_manager_emits_skill_dedup_match():
    from ouroboros.skill_manager import SkillManager

    client = MagicMock()
    col = _mock_collection()
    col.count.return_value = 5
    col.query.return_value = {
        "ids": [["existing-id"]],
        "documents": [["existing skill"]],
        "metadatas": [[{
            "name": "existing", "times_matched": 0, "avg_rounds": 3,
        }]],
        "distances": [[0.05]],  # similarity 0.95 — strong match
    }
    client.get_or_create_collection.return_value = col

    events: list[dict] = []
    sm = SkillManager(
        chromadb_client=client,
        llm_client=_mock_llm(),
        event_emit_fn=events.append,
    )
    sm._skills_col = col

    # current rounds (10) >= avg_rounds (3) → existing skill is kept,
    # process_completed_task returns None, but dedup emit still fires
    out = sm.process_completed_task(_task_result(rounds=10))
    assert out is None

    dedup = [e for e in events if e["type"] == "skill_dedup_match"]
    assert len(dedup) == 1
    assert dedup[0]["skill_id"] == "existing-id"
    assert dedup[0]["similarity"] == pytest.approx(0.95, abs=1e-6)


def test_skill_manager_emits_skill_retired():
    from ouroboros.skill_manager import SkillManager

    client = MagicMock()
    col = _mock_collection()
    # record_skill_usage path: skill exists, score will go below -3 after 5 uses
    col.get.return_value = {
        "ids": ["bad-skill"],
        "metadatas": [{
            "times_used": 4, "times_helped": 0, "avg_rounds": 10.0,
            "rounds_at_creation": 10,
        }],
        "documents": ["bad skill content"],
    }
    client.get_or_create_collection.return_value = col

    events: list[dict] = []
    sm = SkillManager(
        chromadb_client=client,
        llm_client=_mock_llm(),
        event_emit_fn=events.append,
    )
    sm._skills_col = col

    # 5th use, didn't help — score = 0 - 5 = -5, retire triggered
    sm.record_skill_usage("bad-skill", rounds_with_skill=15)

    retired = [e for e in events if e["type"] == "skill_retired"]
    assert len(retired) == 1
    assert retired[0]["skill_id"] == "bad-skill"
    assert retired[0]["score"] < -3
    assert retired[0]["times_used"] == 5


def test_skill_manager_no_emit_when_callback_absent():
    """Backwards-compat: omitting event_emit_fn must not crash."""
    from ouroboros.skill_manager import SkillManager

    client = MagicMock()
    col = _mock_collection()
    client.get_or_create_collection.return_value = col
    sm = SkillManager(chromadb_client=client, llm_client=_mock_llm())
    sm._skills_col = col

    # Just verify no crash through the full path
    sm.process_completed_task(_task_result())


def test_skill_manager_swallows_emit_callback_errors():
    """A broken event_emit_fn must not break skill extraction."""
    from ouroboros.skill_manager import SkillManager

    client = MagicMock()
    col = _mock_collection()
    client.get_or_create_collection.return_value = col

    def _broken(_):
        raise RuntimeError("boom")

    sm = SkillManager(
        chromadb_client=client,
        llm_client=_mock_llm(),
        event_emit_fn=_broken,
    )
    sm._skills_col = col
    out = sm.process_completed_task(_task_result())
    assert out and out.startswith("new:")


# ---------------------------------------------------------------------------
# ExperimentEngine
# ---------------------------------------------------------------------------

def _engine_with_emitter(tmp_path: pathlib.Path):
    from ouroboros.experiment_engine import ExperimentEngine

    # Minimal skill_manager mock; engine only touches `_skills_col`
    sm = MagicMock()
    sm._skills_col = MagicMock()
    sm._skills_col.add.return_value = None

    events: list[dict] = []
    engine = ExperimentEngine(
        data_dir=tmp_path,
        skill_manager=sm,
        llm_client=MagicMock(),
        event_emit_fn=events.append,
    )
    return engine, events, sm


def _seed_active_experiment(engine, action_id="skill-xyz"):
    """Insert a fully-populated active experiment so we can drive conclusion."""
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    exp = {
        "id": "exp_001",
        "status": "active",
        "hypothesis": "if X then Y",
        "action_type": "save_skill",
        "action_name": "test-skill",
        "action_id": action_id,
        "metric": "avg_rounds",
        "baseline": 10.0,
        "target": 5.0,
        "group": "task:do",
        "max_tasks": 3,
        "max_days": 3,
        "started": now.isoformat(),
        "expires": (now + timedelta(days=3)).isoformat(),
        "matching_tasks": [],
        "verdict": None,
    }
    engine.state["experiments"].append(exp)
    engine._save_state()
    return exp


def test_experiment_engine_emits_experiment_started(tmp_path):
    engine, events, _ = _engine_with_emitter(tmp_path)

    # Stub out detector + hypothesis path to drive run_full_cycle deterministically
    from unittest.mock import patch
    fake_pattern = {"group": "task:do", "sample_task_ids": []}
    fake_hypothesis = {
        "hypothesis": "test hypothesis",
        "action_type": "save_skill",
        "action_content": "skill content here",
        "action_name": "stub-skill",
        "metric": "avg_rounds",
        "baseline": 10.0,
        "target": 5.0,
        "max_tasks": 3,
        "max_days": 3,
    }

    with patch("ouroboros.experiment_engine.PatternDetector") as PD, \
         patch.object(engine, "_generate_hypothesis", return_value=fake_hypothesis):
        PD.return_value.analyze.return_value = [fake_pattern]
        # _execute_action needs the skill_manager mock to return an id
        engine.skill_manager._skills_col.add.side_effect = lambda **k: None
        exp_id = engine.run_full_cycle()

    assert exp_id is not None
    started = [e for e in events if e["type"] == "experiment_started"]
    assert len(started) == 1
    assert started[0]["experiment_id"] == exp_id
    assert started[0]["action_type"] == "save_skill"
    assert started[0]["metric"] == "avg_rounds"


def test_experiment_engine_emits_experiment_concluded_on_success(tmp_path):
    engine, events, _ = _engine_with_emitter(tmp_path)
    exp = _seed_active_experiment(engine)

    # Three matching tasks, all under target → confirmed
    for i in range(3):
        engine.record_task_for_experiments({
            "task": "do something",
            "rounds": 4,  # below target=5
            "cost": 0.01,
            "success": True,
            "task_id": f"t{i}",
        })

    concluded = [e for e in events if e["type"] == "experiment_concluded"]
    assert len(concluded) == 1
    assert concluded[0]["experiment_id"] == "exp_001"
    assert concluded[0]["status"] == "confirmed"
    assert concluded[0]["matching_tasks"] == 3


def test_experiment_engine_emits_experiment_concluded_on_failure(tmp_path):
    engine, events, sm = _engine_with_emitter(tmp_path)
    _seed_active_experiment(engine)

    # Three matching tasks, all worse than baseline → failed → revert
    for i in range(3):
        engine.record_task_for_experiments({
            "task": "do something",
            "rounds": 15,  # worse than baseline=10
            "cost": 0.01,
            "success": True,
            "task_id": f"t{i}",
        })

    concluded = [e for e in events if e["type"] == "experiment_concluded"]
    assert len(concluded) == 1
    assert concluded[0]["status"] == "failed"
    # _revert_action should have deleted the skill
    sm._skills_col.delete.assert_called_once()
