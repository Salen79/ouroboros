"""Unit tests for InnerCritic — mid-task quality checkpoint."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ouroboros.inner_critic import InnerCritic, CriticCheckpoint


# ── Fixtures ────────────────────────────────────────────────────────

def _make_llm_mock(response_json: dict, cost: float = 0.01):
    """Create a mock LLM client that returns a JSON response."""
    mock = MagicMock()
    mock.chat.return_value = (
        {"content": json.dumps(response_json)},
        {"cost": cost, "prompt_tokens": 300, "completion_tokens": 150},
    )
    return mock


def _on_track_response():
    return {
        "on_track": True,
        "confidence": 0.95,
        "progress_assessment": "Agent found skills and started implementation",
        "main_concern": "none",
        "pattern_match": None,
        "suggestion": "continue current approach",
        "should_change_approach": False,
        "approach_alternative": None,
    }


def _off_track_response():
    return {
        "on_track": False,
        "confidence": 0.8,
        "progress_assessment": "Agent wrote prompt but is now deploying",
        "main_concern": "Scope creep: task was rewrite prompt, now deploying",
        "pattern_match": "scope creep after write_file on write tasks",
        "suggestion": "Stop deployment. Report written file and suggest deploy as follow-up",
        "should_change_approach": True,
        "approach_alternative": "Mark task complete with written prompt file",
    }


def _make_context(current_round=10, max_rounds=25, cost=0.5):
    return {
        "original_task": "Rewrite the analyze_text prompt for better gray zone detection",
        "task_type": "write",
        "current_round": current_round,
        "max_rounds": max_rounds,
        "total_cost_so_far": cost,
        "tool_calls": [
            {"round": 1, "tool": "find_skills", "success": True, "summary": "Found 2 skills"},
            {"round": 2, "tool": "memory_search", "success": True, "summary": "3 relevant memories"},
            {"round": 5, "tool": "drive_write", "success": True, "summary": "Wrote prompt file"},
        ],
        "files_written": ["prompts/analyze_text.md"],
        "files_read": ["prompts/analyze_text.md", "wisdom.md"],
        "last_3_responses_lengths": [450, 38, 42],
        "repeated_tool_calls": [
            {"tool": "shell_exec", "count": 4, "pattern": "systemctl status..."},
        ],
    }


def _make_critic(llm_mock=None, wisdom_content="", max_rounds=25, episodic_fn=None):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(wisdom_content)
        wisdom_path = Path(f.name)
    if llm_mock is None:
        llm_mock = _make_llm_mock(_on_track_response())
    return InnerCritic(
        llm_client=llm_mock,
        wisdom_path=wisdom_path,
        episodic_search_fn=episodic_fn,
        max_rounds=max_rounds,
    )


# ── should_run() tests ─────────────────────────────────────────────

class TestShouldRun:
    def test_runs_at_checkpoint_rounds(self):
        critic = _make_critic(max_rounds=25)
        # 40% of 25 = 10, 75% of 25 = 18 (int truncation)
        assert critic.should_run(10, 0.5) is True
        assert critic.should_run(18, 0.5) is True

    def test_skips_non_checkpoint_rounds(self):
        critic = _make_critic(max_rounds=25)
        assert critic.should_run(1, 0.5) is False
        assert critic.should_run(5, 0.5) is False
        assert critic.should_run(15, 0.5) is False
        assert critic.should_run(25, 0.5) is False

    def test_skips_when_cost_exceeds_4(self):
        critic = _make_critic(max_rounds=25)
        assert critic.should_run(10, 4.01) is False
        assert critic.should_run(10, 5.0) is False

    def test_skips_at_cost_boundary(self):
        critic = _make_critic(max_rounds=25)
        assert critic.should_run(10, 4.0) is True  # exactly 4.0 is OK
        assert critic.should_run(10, 4.001) is False

    def test_skips_after_high_confidence_on_track(self):
        llm_mock = _make_llm_mock(_on_track_response())  # confidence 0.95
        critic = _make_critic(llm_mock=llm_mock)

        # First checkpoint: on_track with 0.95 confidence
        ctx = _make_context(current_round=10)
        critic.evaluate(ctx)

        # Second checkpoint should be skipped
        assert critic.should_run(18, 0.5) is False
        assert critic._skip_remaining is True

    def test_does_not_skip_after_low_confidence_on_track(self):
        resp = _on_track_response()
        resp["confidence"] = 0.7
        llm_mock = _make_llm_mock(resp)
        critic = _make_critic(llm_mock=llm_mock)

        ctx = _make_context(current_round=10)
        critic.evaluate(ctx)

        # Second checkpoint should still run
        assert critic.should_run(18, 0.5) is True
        assert critic._skip_remaining is False

    def test_does_not_skip_after_off_track(self):
        llm_mock = _make_llm_mock(_off_track_response())  # on_track=False
        critic = _make_critic(llm_mock=llm_mock)

        ctx = _make_context(current_round=10)
        critic.evaluate(ctx)

        assert critic.should_run(18, 0.5) is True
        assert critic._skip_remaining is False

    def test_no_repeat_checkpoint(self):
        llm_mock = _make_llm_mock(_off_track_response())
        critic = _make_critic(llm_mock=llm_mock)

        ctx = _make_context(current_round=10)
        critic.evaluate(ctx)

        # Same round again — should not run
        assert critic.should_run(10, 0.5) is False

    def test_different_max_rounds(self):
        critic = _make_critic(max_rounds=50)
        # 40% of 50 = 20, 75% of 50 = 37
        assert critic.checkpoint_rounds == [20, 37]
        assert critic.should_run(20, 0.5) is True
        assert critic.should_run(37, 0.5) is True
        assert critic.should_run(10, 0.5) is False


# ── _parse_response() tests ────────────────────────────────────────

class TestParseResponse:
    def test_valid_json(self):
        critic = _make_critic()
        result = critic._parse_response(json.dumps(_on_track_response()))
        assert result is not None
        assert result["on_track"] is True
        assert result["confidence"] == 0.95

    def test_json_with_code_fences(self):
        critic = _make_critic()
        wrapped = f"```json\n{json.dumps(_on_track_response())}\n```"
        result = critic._parse_response(wrapped)
        assert result is not None
        assert result["on_track"] is True

    def test_missing_required_field(self):
        critic = _make_critic()
        incomplete = {"on_track": True, "confidence": 0.5}
        result = critic._parse_response(json.dumps(incomplete))
        assert result is None

    def test_malformed_json(self):
        critic = _make_critic()
        result = critic._parse_response("not valid json {{{")
        assert result is None

    def test_empty_string(self):
        critic = _make_critic()
        result = critic._parse_response("")
        assert result is None


# ── _format_feedback() tests ───────────────────────────────────────

class TestFormatFeedback:
    def test_on_track_format(self):
        critic = _make_critic()
        cp = CriticCheckpoint(
            round=10, on_track=True, confidence=0.9,
            progress_assessment="Good progress so far",
            main_concern="none",
            pattern_match=None,
            suggestion="continue current approach",
            should_change_approach=False,
            approach_alternative=None,
            cost=0.01,
        )
        feedback = critic._format_feedback(cp, 10, 25)
        assert "INNER CRITIC" in feedback
        assert "round 10/25" in feedback
        assert "On track: Yes" in feedback
        assert "Known pattern detected" not in feedback
        assert "Alternative approach" not in feedback

    def test_off_track_format(self):
        critic = _make_critic()
        cp = CriticCheckpoint(
            round=10, on_track=False, confidence=0.8,
            progress_assessment="Agent stuck on deployment",
            main_concern="Scope creep",
            pattern_match="scope creep after write_file",
            suggestion="Stop deployment and report completion",
            should_change_approach=True,
            approach_alternative="Mark task complete",
            cost=0.01,
        )
        feedback = critic._format_feedback(cp, 10, 25)
        assert "WARNING" in feedback
        assert "NO" in feedback
        assert "Known pattern detected: scope creep" in feedback
        assert "Alternative approach: Mark task complete" in feedback
        assert "advisory feedback" in feedback


# ── _load_relevant_patterns() tests ────────────────────────────────

class TestLoadPatterns:
    def test_extracts_from_wisdom(self):
        wisdom = """# Key Lessons
- Failure: scope creep after write causes budget waste
- Never deploy without testing first
- Some random line that should not match
- Avoid running shell commands blindly
"""
        critic = _make_critic(wisdom_content=wisdom)
        patterns = critic._load_relevant_patterns("write")
        # Should include wisdom patterns + hardcoded
        assert len(patterns) <= 10
        assert any("scope creep" in p.lower() for p in patterns)
        assert any("deploy" in p.lower() for p in patterns)

    def test_includes_hardcoded_patterns(self):
        critic = _make_critic(wisdom_content="")
        patterns = critic._load_relevant_patterns("deploy")
        assert len(patterns) == 5  # only hardcoded
        assert any("Scope creep" in p for p in patterns)
        assert any("Flash-lite" in p for p in patterns)

    def test_missing_wisdom_file(self):
        critic = _make_critic()
        critic.wisdom_path = Path("/nonexistent/wisdom.md")
        patterns = critic._load_relevant_patterns("task")
        assert len(patterns) == 5  # only hardcoded, no crash

    def test_caps_at_10(self):
        wisdom = "\n".join(f"- Failure pattern {i}: some lesson learned" for i in range(20))
        critic = _make_critic(wisdom_content=wisdom)
        patterns = critic._load_relevant_patterns("task")
        assert len(patterns) <= 10


# ── _build_prompt() tests ──────────────────────────────────────────

class TestBuildPrompt:
    def test_all_fields_populated(self):
        critic = _make_critic()
        ctx = _make_context()
        prompt = critic._build_prompt(ctx, ["pattern1"], [{"task": "similar", "rounds": 5, "outcome": "success"}])
        assert "Rewrite the analyze_text" in prompt
        assert "write" in prompt
        assert "Round 10 of 25" in prompt
        assert "find_skills" in prompt
        assert "pattern1" in prompt
        assert "similar" in prompt

    def test_empty_lists(self):
        critic = _make_critic()
        ctx = _make_context()
        ctx["tool_calls"] = []
        ctx["files_written"] = []
        ctx["files_read"] = []
        ctx["repeated_tool_calls"] = []
        prompt = critic._build_prompt(ctx, [], [])
        assert "(no tool calls yet)" in prompt
        assert "(none)" in prompt
        assert "(none known)" in prompt
        assert "(no similar tasks found)" in prompt


# ── evaluate() integration tests ───────────────────────────────────

class TestEvaluate:
    def test_on_track_returns_feedback_and_usage(self):
        llm_mock = _make_llm_mock(_on_track_response(), cost=0.015)
        critic = _make_critic(llm_mock=llm_mock)
        ctx = _make_context(current_round=10)

        result = critic.evaluate(ctx)
        assert result is not None
        feedback, usage = result
        assert "INNER CRITIC" in feedback
        assert "Yes" in feedback
        assert usage["cost"] == 0.015
        assert len(critic.checkpoints_done) == 1
        assert critic.checkpoints_done[0].on_track is True

    def test_off_track_returns_feedback(self):
        llm_mock = _make_llm_mock(_off_track_response(), cost=0.02)
        critic = _make_critic(llm_mock=llm_mock)
        ctx = _make_context(current_round=10)

        result = critic.evaluate(ctx)
        assert result is not None
        feedback, _ = result
        assert "WARNING" in feedback
        assert "scope creep" in feedback.lower()

    def test_llm_failure_returns_none(self):
        llm_mock = MagicMock()
        llm_mock.chat.side_effect = Exception("API timeout")
        critic = _make_critic(llm_mock=llm_mock)
        ctx = _make_context(current_round=10)

        result = critic.evaluate(ctx)
        assert result is None

    def test_malformed_llm_response_returns_none(self):
        llm_mock = MagicMock()
        llm_mock.chat.return_value = (
            {"content": "Sorry, I cannot help with that"},
            {"cost": 0.01},
        )
        critic = _make_critic(llm_mock=llm_mock)
        ctx = _make_context(current_round=10)

        result = critic.evaluate(ctx)
        assert result is None

    def test_episodic_search_failure_nonfatal(self):
        def bad_search(query, k=3):
            raise RuntimeError("ChromaDB down")

        llm_mock = _make_llm_mock(_on_track_response())
        critic = _make_critic(llm_mock=llm_mock, episodic_fn=bad_search)
        ctx = _make_context(current_round=10)

        result = critic.evaluate(ctx)
        assert result is not None  # Should still work despite search failure

    def test_episodic_search_results_used(self):
        def mock_search(query, k=3):
            return [{"task": "similar task", "rounds": 8, "outcome": "success"}]

        llm_mock = _make_llm_mock(_on_track_response())
        critic = _make_critic(llm_mock=llm_mock, episodic_fn=mock_search)
        ctx = _make_context(current_round=10)

        critic.evaluate(ctx)
        # Verify LLM was called with prompt containing similar task info
        call_args = llm_mock.chat.call_args
        prompt = call_args[1]["messages"][0]["content"] if "messages" in call_args[1] else call_args[0][0][0]["content"]
        assert "similar task" in prompt


# ── get_summary() tests ────────────────────────────────────────────

class TestGetSummary:
    def test_empty_summary(self):
        critic = _make_critic()
        summary = critic.get_summary()
        assert summary["checkpoints"] == []
        assert summary["total_cost"] == 0
        assert summary["any_off_track"] is False

    def test_summary_after_checkpoints(self):
        llm_mock = _make_llm_mock(_off_track_response(), cost=0.02)
        critic = _make_critic(llm_mock=llm_mock)

        ctx = _make_context(current_round=10)
        critic.evaluate(ctx)

        summary = critic.get_summary()
        assert len(summary["checkpoints"]) == 1
        assert summary["any_off_track"] is True
        assert summary["total_cost"] == 0.02
        assert summary["checkpoints"][0]["round"] == 10
        assert summary["checkpoints"][0]["on_track"] is False

    def test_summary_multiple_checkpoints(self):
        # First: off-track
        off_mock = _make_llm_mock(_off_track_response(), cost=0.02)
        critic = _make_critic(llm_mock=off_mock, max_rounds=25)
        ctx1 = _make_context(current_round=10)
        critic.evaluate(ctx1)

        # Switch to on-track for second checkpoint
        on_resp = _on_track_response()
        on_resp["confidence"] = 0.7  # below skip threshold
        off_mock.chat.return_value = (
            {"content": json.dumps(on_resp)},
            {"cost": 0.015},
        )
        ctx2 = _make_context(current_round=18)
        critic.evaluate(ctx2)

        summary = critic.get_summary()
        assert len(summary["checkpoints"]) == 2
        assert summary["any_off_track"] is True
        assert summary["total_cost"] == pytest.approx(0.035)


# ── Loop integration: critic fires at round 10 with production trace format ──

class TestLoopIntegration:
    """Simulate the exact production flow: llm_trace format → _build_critic_context → evaluate."""

    def test_critic_fires_at_round_10_with_production_trace(self):
        """End-to-end: InnerCritic fires at round 10 using real llm_trace format."""
        from ouroboros.loop import _build_critic_context

        llm_mock = _make_llm_mock(_off_track_response(), cost=0.015)
        critic = _make_critic(llm_mock=llm_mock, max_rounds=25)

        # Simulate 10 rounds of production llm_trace tool_calls
        production_trace_calls = [
            {"tool": "find_skills", "args": {"query": "prism"}, "result": "Found 2 skills", "is_error": False},
            {"tool": "memory_search", "args": {"query": "prism"}, "result": "3 memories", "is_error": False},
            {"tool": "shell_exec", "args": {"cmd": "systemctl status prism"}, "result": "active", "is_error": False},
            {"tool": "drive_read", "args": {"path": "prompts/analyze.md"}, "result": "content...", "is_error": False},
            {"tool": "drive_write", "args": {"path": "prompts/analyze.md"}, "result": "Written", "is_error": False},
            {"tool": "shell_exec", "args": {"cmd": "systemctl restart prism"}, "result": "ok", "is_error": False},
            {"tool": "shell_exec", "args": {"cmd": "curl localhost:8001"}, "result": "ok", "is_error": False},
            {"tool": "shell_exec", "args": {"cmd": "curl localhost:8001"}, "result": "timeout", "is_error": True},
            {"tool": "shell_exec", "args": {"cmd": "curl localhost:8001"}, "result": "timeout", "is_error": True},
            {"tool": "shell_exec", "args": {"cmd": "journalctl -u prism"}, "result": "logs...", "is_error": False},
        ]

        # Step 1: Verify should_run at round 10
        assert critic.should_run(10, 0.5) is True

        # Step 2: Build context using production trace format
        ctx = _build_critic_context(
            original_task="Rewrite the analyze_text prompt",
            task_type="write",
            current_round=10,
            max_rounds=25,
            total_cost_so_far=0.5,
            tool_call_history=production_trace_calls,
            response_lengths=[200, 150, 80],
        )

        # Step 3: Verify context was built correctly from production trace
        assert ctx["current_round"] == 10
        assert ctx["max_rounds"] == 25
        assert len(ctx["tool_calls"]) == 10
        # Verify is_error → success mapping works
        assert ctx["tool_calls"][0]["success"] is True  # find_skills, is_error=False → success=True
        assert ctx["tool_calls"][7]["success"] is False  # curl timeout, is_error=True → success=False
        # Verify files detected correctly from args
        assert "prompts/analyze.md" in ctx["files_written"]
        assert "prompts/analyze.md" in ctx["files_read"]
        # Verify repeated calls detected (curl localhost:8001 x3)
        assert any(r["tool"] == "shell_exec" and r["count"] >= 3 for r in ctx["repeated_tool_calls"])

        # Step 4: Evaluate fires and returns feedback
        result = critic.evaluate(ctx)
        assert result is not None, "Critic must fire at round 10 — returned None instead"
        feedback, usage = result
        assert "INNER CRITIC" in feedback
        assert "round 10/25" in feedback
        assert usage["cost"] == 0.015

        # Step 5: Verify checkpoint was recorded
        assert len(critic.checkpoints_done) == 1
        assert critic.checkpoints_done[0].round == 10
        assert critic.checkpoints_done[0].on_track is False

    def test_critic_does_not_fire_before_round_10(self):
        """Verify no checkpoint at rounds 1-9."""
        critic = _make_critic(max_rounds=25)
        for r in range(1, 10):
            assert critic.should_run(r, 0.5) is False, f"should_run({r}) must be False"

    def test_critic_fires_at_both_checkpoints_when_off_track(self):
        """Both checkpoints fire when first is off-track (confidence < 0.9)."""
        llm_mock = _make_llm_mock(_off_track_response(), cost=0.02)
        critic = _make_critic(llm_mock=llm_mock, max_rounds=25)

        # Checkpoint 1 at round 10
        ctx1 = _make_context(current_round=10)
        result1 = critic.evaluate(ctx1)
        assert result1 is not None

        # Should still run at round 18 (off-track doesn't skip)
        assert critic.should_run(18, 0.5) is True

        ctx2 = _make_context(current_round=18)
        result2 = critic.evaluate(ctx2)
        assert result2 is not None
        assert len(critic.checkpoints_done) == 2

    def test_full_25_round_simulation(self):
        """Simulate all 25 rounds — verify exactly 2 checkpoints fire."""
        llm_mock = _make_llm_mock(_off_track_response(), cost=0.01)
        critic = _make_critic(llm_mock=llm_mock, max_rounds=25)

        checkpoints_fired = []
        for round_idx in range(1, 26):
            if critic.should_run(round_idx, 0.5):
                ctx = _make_context(current_round=round_idx)
                result = critic.evaluate(ctx)
                if result is not None:
                    checkpoints_fired.append(round_idx)

        assert checkpoints_fired == [10, 18], f"Expected checkpoints at [10, 18], got {checkpoints_fired}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
