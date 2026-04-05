"""Inner Critic — mid-task quality checkpoint.

Advisory only — injects observations into THAI's context.
THAI makes all decisions. The critic never stops a task,
never reverts an action, never sends a message to the Shareholder.

See INNER_CRITIC_SPEC.md for full design.
"""

import json
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

CRITIC_PROMPT = """You are an internal quality checkpoint for an AI agent mid-task.
Your role: observe, assess, advise. You do NOT control the agent — you provide honest feedback that the agent will consider.

TASK: {original_task}
TASK TYPE: {task_type}
PROGRESS: Round {current_round} of {max_rounds} ({pct_complete}%)
COST SO FAR: ${total_cost_so_far:.3f}

TOOL CALL HISTORY:
{tool_calls_formatted}

FILES WRITTEN: {files_written}
FILES READ: {files_read}

RESPONSE SIZE TREND (last 3 rounds, tokens): {last_3_responses_lengths}
REPEATED TOOL CALLS: {repeated_tool_calls_formatted}

KNOWN FAILURE PATTERNS FOR THIS TASK TYPE:
{known_failure_patterns_formatted}

SIMILAR PAST TASKS AND THEIR OUTCOMES:
{similar_past_tasks_formatted}

Assess the agent's progress honestly. Respond in JSON only, no markdown:
{{
  "on_track": true | false,
  "confidence": 0.0-1.0,
  "progress_assessment": "one sentence: what has been accomplished so far",
  "main_concern": "one sentence: the biggest risk or problem right now, or 'none' if on track",
  "pattern_match": "name of matched known failure pattern, or null",
  "suggestion": "one concrete, actionable sentence: what to do next. Be specific — name the tool, the file, the approach. Or 'continue current approach' if on track",
  "should_change_approach": true | false,
  "approach_alternative": "if should_change_approach=true: one sentence describing the alternative approach. null otherwise"
}}

Rules:
- Be honest, not encouraging. If the agent is stuck, say so.
- Be specific. "Try harder" is useless. "Run the test before deploying" is useful.
- If a known failure pattern matches, flag it explicitly.
- If response sizes are shrinking, this usually means the model is stuck or confused.
- If the same tool is called 3+ times with similar args, the agent is likely looping.
- You are advisory only. The agent decides what to do with your feedback."""


@dataclass
class CriticCheckpoint:
    round: int
    on_track: bool
    confidence: float
    progress_assessment: str
    main_concern: str
    pattern_match: Optional[str]
    suggestion: str
    should_change_approach: bool
    approach_alternative: Optional[str]
    cost: float


class InnerCritic:
    """Mid-task quality checkpoint. Advisory only — never controls execution."""

    # Checkpoint at 40% and 75% of max_rounds
    CHECKPOINT_PERCENTAGES = [0.40, 0.75]

    def __init__(
        self,
        llm_client,
        wisdom_path: Path,
        episodic_search_fn: Optional[Callable] = None,
        max_rounds: int = 12,
    ):
        self.llm = llm_client
        self.wisdom_path = wisdom_path
        self.episodic_search = episodic_search_fn  # fn(query, k) -> list[dict]
        self.max_rounds = max_rounds
        self.checkpoint_rounds = [
            int(max_rounds * pct) for pct in self.CHECKPOINT_PERCENTAGES
        ]
        self.checkpoints_done: List[CriticCheckpoint] = []
        self._skip_remaining = False

    def should_run(self, current_round: int, task_cost: float) -> bool:
        """Check if critic should run at this round."""
        if self._skip_remaining:
            return False

        if task_cost > 4.0:
            return False  # Save budget for actual work

        if current_round not in self.checkpoint_rounds:
            return False

        # Don't repeat a checkpoint
        done_rounds = {cp.round for cp in self.checkpoints_done}
        if current_round in done_rounds:
            return False

        return True

    def evaluate(self, context: Dict[str, Any]) -> Optional[str]:
        """Run critic checkpoint. Returns formatted feedback string or None.

        Args:
            context: dict with keys matching critic_context spec

        Returns:
            Formatted feedback string to inject into agent context, or None on failure
        """
        try:
            # Load known failure patterns relevant to this task type
            known_patterns = self._load_relevant_patterns(context.get("task_type", ""))

            # Load similar past tasks from episodic memory
            similar_tasks = []
            if self.episodic_search:
                try:
                    similar_tasks = self.episodic_search(
                        context.get("original_task", ""), k=3
                    )
                    if not isinstance(similar_tasks, list):
                        similar_tasks = []
                except Exception as e:
                    log.warning("Episodic search for critic failed: %s", e)

            # Build prompt
            prompt = self._build_prompt(context, known_patterns, similar_tasks)

            # Call LLM (Sonnet — same tier as primary)
            msg, usage = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                model="anthropic/claude-sonnet-4.6",
                max_tokens=2048,
                reasoning_effort="low",
            )

            # Extract text from response — handle multiple possible formats
            response_text = ""
            if isinstance(msg, dict):
                response_text = (msg.get("content") or msg.get("text") or "")
                # Some models return content as list of dicts [{type: "text", text: "..."}]
                if isinstance(response_text, list):
                    response_text = " ".join(
                        part.get("text", "") for part in response_text
                        if isinstance(part, dict)
                    )
            elif isinstance(msg, str):
                response_text = msg
            response_text = response_text.strip()

            checkpoint_cost = float(usage.get("cost") or 0)

            # Hard cap: abort if checkpoint cost exceeds $0.03
            if checkpoint_cost > 0.03:
                log.warning("Inner critic checkpoint cost $%.4f exceeds $0.03 cap", checkpoint_cost)

            if not response_text:
                log.warning("Inner critic got empty response from LLM (msg keys: %s)",
                            list(msg.keys()) if isinstance(msg, dict) else type(msg).__name__)
                return None

            # Parse response
            result = self._parse_response(response_text)
            if not result:
                return None

            # Record checkpoint
            checkpoint = CriticCheckpoint(
                round=context["current_round"],
                on_track=result["on_track"],
                confidence=float(result["confidence"]),
                progress_assessment=result["progress_assessment"],
                main_concern=result["main_concern"],
                pattern_match=result.get("pattern_match"),
                suggestion=result["suggestion"],
                should_change_approach=result.get("should_change_approach", False),
                approach_alternative=result.get("approach_alternative"),
                cost=checkpoint_cost,
            )
            self.checkpoints_done.append(checkpoint)

            # If first checkpoint says on_track with high confidence, skip second
            if (
                len(self.checkpoints_done) == 1
                and checkpoint.on_track
                and checkpoint.confidence >= 0.9
            ):
                self._skip_remaining = True

            # Format feedback for injection
            return self._format_feedback(checkpoint, context["current_round"], self.max_rounds), usage

        except Exception as e:
            log.warning("Inner critic checkpoint failed (non-fatal): %s", e)
            return None

    def get_summary(self) -> Dict[str, Any]:
        """Return summary of all checkpoints for task result logging."""
        return {
            "checkpoints": [
                {
                    "round": cp.round,
                    "on_track": cp.on_track,
                    "confidence": cp.confidence,
                    "main_concern": cp.main_concern,
                    "pattern_match": cp.pattern_match,
                    "suggestion": cp.suggestion,
                    "cost": cp.cost,
                }
                for cp in self.checkpoints_done
            ],
            "total_cost": sum(cp.cost for cp in self.checkpoints_done),
            "any_off_track": any(not cp.on_track for cp in self.checkpoints_done),
        }

    def _load_relevant_patterns(self, task_type: str) -> List[str]:
        """Extract failure patterns from wisdom.md relevant to task type."""
        patterns = []
        if self.wisdom_path.exists():
            try:
                content = self.wisdom_path.read_text(encoding="utf-8")
                lines = content.split("\n")
                for line in lines:
                    lower = line.lower()
                    if any(kw in lower for kw in ["failure", "lesson", "mistake", "avoid", "don't", "never"]):
                        pattern = line.strip("- #*").strip()
                        if pattern and len(pattern) > 10:
                            patterns.append(pattern)
            except Exception as e:
                log.warning("Failed to load wisdom patterns: %s", e)

        # Hardcoded patterns from key lessons
        hardcoded = [
            "Scope creep after write_file: task 'rewrite prompt' spent 14 extra rounds on deploy/test",
            "Flash-lite returns tiny responses but not empty — loops without progress",
            "Announcement without execution: plans get stated but work doesn't start",
            "Same shell command repeated 3+ times usually means wrong approach, not bad luck",
            "Deploy tasks waste rounds figuring out current state — check status first",
        ]
        patterns.extend(hardcoded)

        return patterns[:10]  # Cap at 10 to keep prompt manageable

    def _build_prompt(
        self,
        context: Dict[str, Any],
        known_patterns: List[str],
        similar_tasks: List[Dict],
    ) -> str:
        """Build the critic evaluation prompt."""
        tool_calls_fmt = "\n".join(
            f"  Round {tc['round']}: {tc['tool']} -> {'OK' if tc.get('success') else 'FAIL'} {tc.get('summary', '')}"
            for tc in context.get("tool_calls", [])
        ) or "  (no tool calls yet)"

        repeated_fmt = "\n".join(
            f"  {r['tool']}: called {r['count']}x — {r.get('pattern', '')}"
            for r in context.get("repeated_tool_calls", [])
        ) or "  (none)"

        patterns_fmt = "\n".join(f"  - {p}" for p in known_patterns) or "  (none known)"

        similar_fmt = "\n".join(
            f"  - \"{t.get('task', '?')}\" -> {t.get('rounds', '?')} rounds, outcome: {t.get('outcome', '?')}"
            for t in similar_tasks
        ) or "  (no similar tasks found)"

        pct = int(context["current_round"] / context["max_rounds"] * 100)

        return CRITIC_PROMPT.format(
            original_task=context.get("original_task", "unknown"),
            task_type=context.get("task_type", "unknown"),
            current_round=context["current_round"],
            max_rounds=context["max_rounds"],
            pct_complete=pct,
            total_cost_so_far=context.get("total_cost_so_far", 0),
            tool_calls_formatted=tool_calls_fmt,
            files_written=", ".join(context.get("files_written", [])) or "(none)",
            files_read=", ".join(context.get("files_read", [])) or "(none)",
            last_3_responses_lengths=context.get("last_3_responses_lengths", []),
            repeated_tool_calls_formatted=repeated_fmt,
            known_failure_patterns_formatted=patterns_fmt,
            similar_past_tasks_formatted=similar_fmt,
        )

    def _parse_response(self, response: str) -> Optional[Dict]:
        """Parse JSON response from critic LLM call."""
        try:
            text = response.strip()
            # Strip markdown code fences if present (```json ... ```)
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

            # Try to extract JSON object if surrounded by non-JSON text
            if not text.startswith("{"):
                start = text.find("{")
                end = text.rfind("}")
                if start != -1 and end != -1 and end > start:
                    text = text[start:end + 1]

            result = json.loads(text)

            required = ["on_track", "confidence", "progress_assessment", "main_concern", "suggestion"]
            for field_name in required:
                if field_name not in result:
                    log.warning("Critic response missing field: %s", field_name)
                    return None

            return result
        except (json.JSONDecodeError, ValueError) as e:
            log.warning("Failed to parse critic response: %s | raw (first 200 chars): %s",
                        e, repr(response[:200]))
            return None

    def _format_feedback(self, cp: CriticCheckpoint, current_round: int, max_rounds: int) -> str:
        """Format checkpoint into injectable feedback string."""
        lines = [
            "",
            f"\u2501\u2501\u2501 INNER CRITIC \u2014 Checkpoint at round {current_round}/{max_rounds} \u2501\u2501\u2501",
            "",
            f"Progress: {cp.progress_assessment}",
            f"On track: {'Yes' if cp.on_track else 'WARNING \u2014 NO'} (confidence: {cp.confidence})",
        ]

        if cp.pattern_match:
            lines.append(f"Known pattern detected: {cp.pattern_match}")

        lines.append(f"Main concern: {cp.main_concern}")
        lines.append(f"Suggestion: {cp.suggestion}")

        if cp.should_change_approach and cp.approach_alternative:
            lines.append(f"Alternative approach: {cp.approach_alternative}")

        lines.extend([
            "",
            "This is advisory feedback. You decide how to proceed.",
            "\u2501" * 58,
            "",
        ])

        return "\n".join(lines)
