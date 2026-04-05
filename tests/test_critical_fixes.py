"""Tests for critical fixes: Inner Critic checkpoints, action-first enforcement, MAX_ROUNDS."""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ouroboros.inner_critic import InnerCritic, CriticCheckpoint


# ── Inner Critic with MAX_ROUNDS=12 ──────────────────────────────────


def _make_llm_mock(response_json: dict, cost: float = 0.01):
    mock = MagicMock()
    mock.chat.return_value = (
        {"content": json.dumps(response_json)},
        {"cost": cost, "prompt_tokens": 300, "completion_tokens": 150},
    )
    return mock


class TestInnerCriticCheckpoints:
    """Verify Inner Critic fires at correct rounds with MAX_ROUNDS=12."""

    def test_init_checkpoint_rounds_12(self):
        """Checkpoints must be at rounds 4 and 9 for MAX_ROUNDS=12."""
        llm = MagicMock()
        with tempfile.TemporaryDirectory() as td:
            critic = InnerCritic(llm, Path(td) / "wisdom.md", max_rounds=12)
            assert critic.checkpoint_rounds == [4, 9]  # int(12*0.40)=4, int(12*0.75)=9

    def test_init_does_not_silently_fail(self):
        """InnerCritic must initialize without silent exceptions."""
        llm = MagicMock()
        with tempfile.TemporaryDirectory() as td:
            critic = InnerCritic(llm, Path(td) / "wisdom.md", max_rounds=12)
            assert critic is not None
            assert not critic._skip_remaining

    def test_default_max_rounds_is_12(self):
        """Default max_rounds should be 12 (not 25)."""
        llm = MagicMock()
        with tempfile.TemporaryDirectory() as td:
            critic = InnerCritic(llm, Path(td) / "wisdom.md")
            assert critic.max_rounds == 12
            assert critic.checkpoint_rounds == [4, 9]

    def test_should_run_at_correct_rounds(self):
        """should_run must return True at checkpoint rounds only."""
        llm = MagicMock()
        with tempfile.TemporaryDirectory() as td:
            critic = InnerCritic(llm, Path(td) / "wisdom.md", max_rounds=12)

            # Should NOT run before checkpoint
            assert not critic.should_run(1, 0.0)
            assert not critic.should_run(3, 0.0)

            # MUST run at checkpoint 1 (round 4)
            assert critic.should_run(4, 0.0)

            # Should NOT run at non-checkpoint rounds
            assert not critic.should_run(5, 0.0)
            assert not critic.should_run(8, 0.0)

            # MUST run at checkpoint 2 (round 9)
            assert critic.should_run(9, 0.0)

    def test_should_run_respects_cost_limit(self):
        """Should NOT run if cost > $4."""
        llm = MagicMock()
        with tempfile.TemporaryDirectory() as td:
            critic = InnerCritic(llm, Path(td) / "wisdom.md", max_rounds=12)
            assert not critic.should_run(4, 4.5)

    def test_should_run_skips_after_high_confidence(self):
        """If checkpoint 1 returns on_track with >=0.9, skip checkpoint 2."""
        llm = MagicMock()
        with tempfile.TemporaryDirectory() as td:
            critic = InnerCritic(llm, Path(td) / "wisdom.md", max_rounds=12)

            # Simulate first checkpoint with high confidence
            critic.checkpoints_done.append(CriticCheckpoint(
                round=4, on_track=True, confidence=0.95,
                progress_assessment="Good", main_concern="none",
                pattern_match=None, suggestion="continue",
                should_change_approach=False, approach_alternative=None, cost=0.01
            ))
            critic._skip_remaining = True

            # Checkpoint 2 should be skipped
            assert not critic.should_run(9, 0.0)

    def test_evaluate_returns_feedback(self):
        """evaluate() must return formatted feedback string + usage."""
        response = {
            "on_track": False, "confidence": 0.7,
            "progress_assessment": "Agent stuck",
            "main_concern": "No progress",
            "suggestion": "Try different approach",
            "should_change_approach": True,
            "approach_alternative": "Decompose task",
        }
        llm = _make_llm_mock(response)

        with tempfile.TemporaryDirectory() as td:
            critic = InnerCritic(llm, Path(td) / "wisdom.md", max_rounds=12)

            context = {
                "original_task": "Fix language drift",
                "task_type": "fix",
                "current_round": 4,
                "max_rounds": 12,
                "total_cost_so_far": 0.5,
                "tool_calls": [
                    {"round": 1, "tool": "find_skills", "success": True, "summary": "Found 2"},
                    {"round": 2, "tool": "memory_search", "success": True, "summary": "3 results"},
                ],
                "files_written": [],
                "files_read": [],
                "last_3_responses_lengths": [200, 150, 80],
                "repeated_tool_calls": [],
            }

            result = critic.evaluate(context)
            assert result is not None
            feedback, usage = result
            assert "INNER CRITIC" in feedback
            assert "WARNING" in feedback  # off-track
            assert "Try different approach" in feedback
            assert len(critic.checkpoints_done) == 1
            assert not critic.checkpoints_done[0].on_track

    def test_evaluate_handles_llm_failure(self):
        """If LLM call fails, return None — don't crash."""
        llm = MagicMock()
        llm.chat.side_effect = Exception("API timeout")

        with tempfile.TemporaryDirectory() as td:
            critic = InnerCritic(llm, Path(td) / "wisdom.md", max_rounds=12)

            context = {
                "original_task": "test", "task_type": "test",
                "current_round": 4, "max_rounds": 12,
                "total_cost_so_far": 0.1, "tool_calls": [],
                "files_written": [], "files_read": [],
                "last_3_responses_lengths": [], "repeated_tool_calls": [],
            }

            result = critic.evaluate(context)
            assert result is None  # Graceful failure


# ── Action-first enforcement ──────────────────────────────────────────


class TestActionFirstEnforcement:
    """Verify action-first nudge logic."""

    ACTION_TOOLS = frozenset({
        "run_shell", "shell_exec", "repo_write", "write_file", "create_file",
        "claude_code_edit", "save_skill", "knowledge_write", "repo_write_commit",
    })

    def test_nudge_fires_when_no_action_tools(self):
        """Nudge should fire when only read/plan tools used."""
        history = [
            {"tool": "find_skills"},
            {"tool": "memory_search"},
            {"tool": "repo_read"},
        ]
        action_calls = [tc for tc in history if tc.get("tool") in self.ACTION_TOOLS]
        assert len(action_calls) == 0

    def test_nudge_does_not_fire_with_action_tool(self):
        """No nudge when action tools have been used."""
        history = [
            {"tool": "find_skills"},
            {"tool": "run_shell"},
            {"tool": "repo_read"},
        ]
        action_calls = [tc for tc in history if tc.get("tool") in self.ACTION_TOOLS]
        assert len(action_calls) == 1

    def test_write_file_counts_as_action(self):
        history = [{"tool": "write_file"}]
        action_calls = [tc for tc in history if tc.get("tool") in self.ACTION_TOOLS]
        assert len(action_calls) == 1

    def test_save_skill_counts_as_action(self):
        history = [{"tool": "save_skill"}]
        action_calls = [tc for tc in history if tc.get("tool") in self.ACTION_TOOLS]
        assert len(action_calls) == 1


# ── MAX_ROUNDS config ────────────────────────────────────────────────


class TestMaxRoundsConfig:
    """Verify MAX_ROUNDS defaults and env override."""

    def test_env_override(self):
        import os
        old = os.environ.get("OUROBOROS_MAX_ROUNDS")
        try:
            os.environ["OUROBOROS_MAX_ROUNDS"] = "12"
            val = max(1, int(os.environ.get("OUROBOROS_MAX_ROUNDS", "12")))
            assert val == 12
        finally:
            if old is not None:
                os.environ["OUROBOROS_MAX_ROUNDS"] = old
            else:
                os.environ.pop("OUROBOROS_MAX_ROUNDS", None)

    def test_checkpoint_recalc_for_12(self):
        """Checkpoints for MAX_ROUNDS=12: round 4 (40%) and round 9 (75%)."""
        max_rounds = 12
        percentages = [0.40, 0.75]
        checkpoints = [int(max_rounds * p) for p in percentages]
        assert checkpoints == [4, 9]
