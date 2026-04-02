"""
Unit tests for ouroboros.skill_manager — closed-loop skill lifecycle.

Mocks ChromaDB and LLM to test detection, dedup, extraction, save, and validation.
"""

import json
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_task_result(**overrides):
    """Helper to create a task_result dict with sensible defaults."""
    base = {
        "task": "check caddy status and report",
        "result": "Caddy is running on port 443, all routes healthy.",
        "rounds": 5,
        "success": True,
        "task_type": "task",
        "tool_calls": [
            {"tool": "run_shell", "args": {"command": "systemctl status caddy"}},
            {"tool": "run_shell", "args": {"command": "curl -s localhost:443"}},
            {"tool": "send_owner_message", "args": {"text": "Caddy healthy"}},
        ],
        "timestamp": "2026-04-02T10:00:00Z",
    }
    base.update(overrides)
    return base


def _mock_chromadb_collection():
    """Return a mock ChromaDB collection with basic query/add/update/get/count."""
    col = MagicMock()
    col.count.return_value = 0
    col.query.return_value = {
        "ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]],
    }
    col.get.return_value = {"ids": [], "metadatas": [], "documents": []}
    return col


def _mock_llm_client(response_json=None):
    """Return a mock LLMClient that returns a valid skill extraction response."""
    llm = MagicMock()
    if response_json is None:
        response_json = {
            "name": "check-caddy-status",
            "description": "Check Caddy reverse proxy status and report health.",
            "steps": [
                "Run systemctl status caddy",
                "Check HTTP response on port 443",
                "Report results to owner",
            ],
            "tools_used": ["run_shell", "send_owner_message"],
        }
    llm.chat.return_value = (
        {"content": json.dumps(response_json)},
        {"prompt_tokens": 200, "completion_tokens": 100, "cost": 0.001},
    )
    return llm


@pytest.fixture
def skill_manager():
    from ouroboros.skill_manager import SkillManager
    client = MagicMock()
    col = _mock_chromadb_collection()
    client.get_or_create_collection.return_value = col
    llm = _mock_llm_client()
    sm = SkillManager(chromadb_client=client, llm_client=llm)
    sm._skills_col = col  # ensure it's our mock
    return sm, col, llm


# ---------------------------------------------------------------------------
# Step 1: should_extract
# ---------------------------------------------------------------------------

class TestShouldExtract:

    def test_extracts_successful_task_over_3_rounds(self, skill_manager):
        sm, _, _ = skill_manager
        result = _make_task_result(rounds=5, success=True, task_type="task")
        assert sm.should_extract(result) is True

    def test_skips_short_task(self, skill_manager):
        sm, _, _ = skill_manager
        result = _make_task_result(rounds=2, success=True)
        assert sm.should_extract(result) is False

    def test_skips_3_rounds_exactly(self, skill_manager):
        sm, _, _ = skill_manager
        result = _make_task_result(rounds=3, success=True)
        assert sm.should_extract(result) is False

    def test_skips_failed_task(self, skill_manager):
        sm, _, _ = skill_manager
        result = _make_task_result(rounds=10, success=False)
        assert sm.should_extract(result) is False

    def test_skips_consciousness_task(self, skill_manager):
        sm, _, _ = skill_manager
        result = _make_task_result(rounds=10, success=True, task_type="consciousness")
        assert sm.should_extract(result) is False

    def test_skips_system_task(self, skill_manager):
        sm, _, _ = skill_manager
        result = _make_task_result(rounds=10, success=True, task_type="system")
        assert sm.should_extract(result) is False

    def test_accepts_direct_chat(self, skill_manager):
        sm, _, _ = skill_manager
        result = _make_task_result(rounds=5, success=True, task_type="direct_chat")
        assert sm.should_extract(result) is True


# ---------------------------------------------------------------------------
# Step 2: find_duplicate
# ---------------------------------------------------------------------------

class TestFindDuplicate:

    def test_no_duplicate_when_empty(self, skill_manager):
        sm, col, _ = skill_manager
        col.count.return_value = 0
        assert sm.find_duplicate("some task") is None

    def test_no_duplicate_when_low_similarity(self, skill_manager):
        sm, col, _ = skill_manager
        col.count.return_value = 5
        col.query.return_value = {
            "ids": [["id1"]], "documents": [["different skill"]],
            "metadatas": [[{"name": "other"}]], "distances": [[0.9]],
        }
        assert sm.find_duplicate("some task", threshold=0.8) is None

    def test_finds_duplicate_when_high_similarity(self, skill_manager):
        sm, col, _ = skill_manager
        col.count.return_value = 5
        col.query.return_value = {
            "ids": [["id1"]], "documents": [["check caddy status"]],
            "metadatas": [[{"name": "check-caddy", "times_matched": 0}]],
            "distances": [[0.1]],
        }
        dup = sm.find_duplicate("check caddy status")
        assert dup is not None
        assert dup["id"] == "id1"
        assert dup["similarity"] == pytest.approx(0.9)

    def test_handles_chromadb_unavailable(self):
        from ouroboros.skill_manager import SkillManager
        sm = SkillManager(chromadb_client=None, llm_client=MagicMock())
        assert sm.find_duplicate("anything") is None


# ---------------------------------------------------------------------------
# Step 3: extract_skill
# ---------------------------------------------------------------------------

class TestExtractSkill:

    def test_extracts_skill_from_task(self, skill_manager):
        sm, _, llm = skill_manager
        result = _make_task_result()
        skill = sm.extract_skill(result)
        assert skill is not None
        assert skill["name"] == "check-caddy-status"
        assert "run_shell" in skill["tools_used"]
        # Verify LLM was called with correct model
        llm.chat.assert_called_once()
        call_kwargs = llm.chat.call_args
        assert call_kwargs.kwargs.get("model") or call_kwargs[1].get("model") == "google/gemini-2.5-flash-lite"

    def test_handles_malformed_llm_response(self, skill_manager):
        sm, _, llm = skill_manager
        llm.chat.return_value = ({"content": "not json at all"}, {})
        result = _make_task_result()
        assert sm.extract_skill(result) is None

    def test_handles_llm_exception(self, skill_manager):
        sm, _, llm = skill_manager
        llm.chat.side_effect = Exception("API timeout")
        result = _make_task_result()
        assert sm.extract_skill(result) is None

    def test_strips_markdown_fences(self, skill_manager):
        sm, _, llm = skill_manager
        json_str = json.dumps({"name": "test", "description": "d", "steps": [], "tools_used": []})
        llm.chat.return_value = ({"content": f"```json\n{json_str}\n```"}, {})
        result = _make_task_result()
        skill = sm.extract_skill(result)
        assert skill is not None
        assert skill["name"] == "test"


# ---------------------------------------------------------------------------
# Step 4: Full pipeline — process_completed_task
# ---------------------------------------------------------------------------

class TestProcessCompletedTask:

    def test_saves_new_skill(self, skill_manager):
        sm, col, _ = skill_manager
        col.count.return_value = 0  # no existing skills
        result = _make_task_result(rounds=5, success=True)
        outcome = sm.process_completed_task(result)
        assert outcome is not None
        assert outcome.startswith("new:")
        col.add.assert_called_once()

    def test_skips_short_task(self, skill_manager):
        sm, col, _ = skill_manager
        result = _make_task_result(rounds=2, success=True)
        assert sm.process_completed_task(result) is None
        col.add.assert_not_called()

    def test_updates_existing_when_better(self, skill_manager):
        sm, col, _ = skill_manager
        col.count.return_value = 3
        col.query.return_value = {
            "ids": [["existing-id"]], "documents": [["old skill"]],
            "metadatas": [[{"name": "check-caddy", "times_matched": 2, "avg_rounds": 8}]],
            "distances": [[0.05]],
        }
        # Current task took 4 rounds, less than avg 8 — should update
        result = _make_task_result(rounds=4, success=True)
        outcome = sm.process_completed_task(result)
        assert outcome is not None
        assert outcome.startswith("updated:")
        col.update.assert_called()

    def test_skips_when_existing_is_better(self, skill_manager):
        sm, col, _ = skill_manager
        col.count.return_value = 3
        col.query.return_value = {
            "ids": [["existing-id"]], "documents": [["old skill"]],
            "metadatas": [[{"name": "check-caddy", "times_matched": 2, "avg_rounds": 3}]],
            "distances": [[0.05]],
        }
        # Current task took 5 rounds, more than avg 3 — skip
        result = _make_task_result(rounds=5, success=True)
        outcome = sm.process_completed_task(result)
        assert outcome is None

    def test_writes_to_jsonl(self):
        from ouroboros.skill_manager import SkillManager
        client = MagicMock()
        col = _mock_chromadb_collection()
        col.count.return_value = 0
        client.get_or_create_collection.return_value = col
        llm = _mock_llm_client()

        written = []
        sm = SkillManager(chromadb_client=client, llm_client=llm, episodic_write_fn=written.append)
        sm._skills_col = col

        result = _make_task_result(rounds=5, success=True)
        outcome = sm.process_completed_task(result)
        assert outcome is not None
        assert len(written) == 1
        assert written[0]["type"] == "skill"
        assert "auto-extracted" in written[0]["tags"]


# ---------------------------------------------------------------------------
# Skill validation — record_skill_usage
# ---------------------------------------------------------------------------

class TestRecordSkillUsage:

    def test_records_helpful_usage(self, skill_manager):
        sm, col, _ = skill_manager
        col.get.return_value = {
            "metadatas": [{"times_used": 0, "times_helped": 0, "avg_rounds": 8, "rounds_at_creation": 8, "score": 0}],
        }
        stats = sm.record_skill_usage("skill-123", rounds_with_skill=3)
        assert stats is not None
        assert stats["helped"] is True
        assert stats["score"] == 1
        assert stats["retired"] is False
        col.update.assert_called_once()

    def test_records_unhelpful_usage(self, skill_manager):
        sm, col, _ = skill_manager
        col.get.return_value = {
            "metadatas": [{"times_used": 0, "times_helped": 0, "avg_rounds": 5, "rounds_at_creation": 5, "score": 0}],
        }
        stats = sm.record_skill_usage("skill-123", rounds_with_skill=10)
        assert stats is not None
        assert stats["helped"] is False
        assert stats["score"] == -1

    def test_auto_retires_bad_skill(self, skill_manager):
        sm, col, _ = skill_manager
        col.get.return_value = {
            "metadatas": [{
                "times_used": 5, "times_helped": 0,
                "avg_rounds": 10, "rounds_at_creation": 5, "score": -4,
            }],
        }
        stats = sm.record_skill_usage("skill-bad", rounds_with_skill=12)
        assert stats is not None
        assert stats["retired"] is True

    def test_handles_chromadb_unavailable(self):
        from ouroboros.skill_manager import SkillManager
        sm = SkillManager(chromadb_client=None, llm_client=MagicMock())
        assert sm.record_skill_usage("id", 5) is None

    def test_handles_missing_skill(self, skill_manager):
        sm, col, _ = skill_manager
        col.get.return_value = {"metadatas": []}
        assert sm.record_skill_usage("nonexistent", 5) is None


# ---------------------------------------------------------------------------
# Import test (for smoke_test compatibility)
# ---------------------------------------------------------------------------

def test_import():
    """skill_manager imports cleanly."""
    import ouroboros.skill_manager
    assert hasattr(ouroboros.skill_manager, "SkillManager")
