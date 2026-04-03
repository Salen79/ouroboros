# Inner Critic — Mid-Task Quality Checkpoint

## Problem

THAI has 6 mechanical correction mechanisms (stuck detector, circuit breaker, scope boundary, model escalation, experiment engine, consciousness reflection). All catch **symptoms** — none evaluate **semantic quality**.

Concrete failure modes this doesn't catch:
- THAI writes a prompt but the prompt is bad → scope boundary says "stop, you wrote a file" → bad prompt ships
- THAI answers a Shareholder question with boilerplate instead of substance → no mechanism notices
- THAI spends 15 rounds on an approach that was wrong from round 3 → stuck detector only catches identical thoughts, not wrong-direction progress
- THAI repeats a mistake documented in wisdom.md 2 weeks ago → nothing cross-references current approach against known failures
- THAI's tool calls succeed individually but don't compose into a solution → each round "works" but the task doesn't converge

**Common thread:** THAI lacks a reflective capacity that evaluates *"am I doing this well?"* during execution — not after.

## Design Principle

The Inner Critic is **advisory, not executive**. It injects observations into THAI's context. THAI makes all decisions — continue, change approach, stop, escalate. The critic never stops a task, never reverts an action, never sends a message to the Shareholder.

This aligns with BIBLE.md P6 (Responsible Freedom): clear information within clear boundaries, autonomy to act on it.

## Dependency

Requires working **loop.py** tool loop (exists). Uses **wisdom.md** and **episodic memory** for known failure patterns (exists). No new dependencies.

## Solution

Single-component system: a checkpoint function called at defined intervals during the tool loop. Uses the primary model (Sonnet) to evaluate progress and inject structured feedback.

```
Round 1 ──── Round 10 ──── [CRITIC CHECKPOINT] ──── Round 11 ... ──── Round 19 ──── [CRITIC CHECKPOINT] ──── Round 20 ...
                                    │                                                        │
                                    ▼                                                        ▼
                           Feedback injected                                        Feedback injected
                           into next round's                                        into next round's
                           context as system                                        context as system
                           message                                                  message
```

No separate agent. No personality. One LLM call per checkpoint — structured prompt, structured output, injected as context.

---

## Component: InnerCritic

**File:** `ouroboros/inner_critic.py` (~180 lines)
**Zone:** Green (new file)
**LLM:** Sonnet (same tier as primary agent) — ~$0.01-0.02 per checkpoint

### When it runs

Two checkpoints per task:
- **Checkpoint 1:** At 40% of MAX_ROUNDS (round 10 with MAX_ROUNDS=25)
- **Checkpoint 2:** At 75% of MAX_ROUNDS (round 19 with MAX_ROUNDS=25)

Checkpoints are **skipped** if:
- Task has completed before the checkpoint round
- Task total cost already exceeds $4.00 (save remaining budget for actual work)
- Previous checkpoint returned `on_track: true` with high confidence (≥0.9) — skip second checkpoint

### What it receives

```python
critic_context = {
    # The task
    "original_task": str,           # What THAI was asked to do
    "task_type": str,               # classify: write, fix, deploy, analyze, answer, etc.

    # Progress so far
    "current_round": int,
    "max_rounds": int,
    "total_rounds_used": int,
    "total_cost_so_far": float,
    "tool_calls": [                 # Summarized, not full payloads
        {"round": 1, "tool": "find_skills", "success": True, "summary": "Found 2 skills"},
        {"round": 2, "tool": "memory_search", "success": True, "summary": "3 relevant memories"},
        {"round": 3, "tool": "shell_exec", "success": False, "error": "permission denied"},
        # ...
    ],

    # Quality signals
    "files_written": ["path/to/file.py"],
    "files_read": ["path/to/other.py"],
    "last_3_responses_lengths": [450, 38, 42],  # Token counts — shrinking = stuck
    "unique_tools_used": ["find_skills", "memory_search", "shell_exec", "repo_write"],
    "repeated_tool_calls": [        # Same tool+args called multiple times
        {"tool": "shell_exec", "count": 4, "pattern": "systemctl status..."}
    ],

    # Historical context
    "known_failure_patterns": [     # From wisdom.md, matched to task type
        "scope creep after write_file on write tasks",
        "flash-lite loops on deploy tasks",
    ],
    "similar_past_tasks": [         # From episodic memory, top 3
        {"task": "rewrite analyze_text prompt", "rounds": 25, "outcome": "scope creep"},
        {"task": "write deployment script", "rounds": 5, "outcome": "success"},
    ],
}
```

### Prompt

```python
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
```

### Output example

```json
{
  "on_track": false,
  "confidence": 0.8,
  "progress_assessment": "Agent wrote the prompt file at round 7 but has spent rounds 8-10 trying to deploy and test it, which was not part of the original task",
  "main_concern": "Scope creep: task was 'rewrite prompt', agent is now doing deployment — matches known failure pattern",
  "pattern_match": "scope creep after write_file on write tasks",
  "suggestion": "Stop deployment attempts. Report the written file as task output and suggest deployment as a follow-up task",
  "should_change_approach": true,
  "approach_alternative": "Mark task complete with the written prompt file. Create a separate task for deployment and testing."
}
```

### How feedback is injected

The critic's output is formatted as a context message inserted before the next round's prompt:

```
━━━ INNER CRITIC — Checkpoint at round {round}/{max_rounds} ━━━

Progress: {progress_assessment}
On track: {"Yes" if on_track else "⚠️ NO"} (confidence: {confidence})
⚠️ Known pattern detected: {pattern_match}   ← only if matched
Main concern: {main_concern}
Suggestion: {suggestion}
Alternative approach: {approach_alternative}  ← only if should_change_approach

This is advisory feedback. You decide how to proceed.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Injected as a system-role message in the conversation, same as memory protocol injection — the agent sees it as part of its context, not as an external command.

---

## Implementation

```python
"""Inner Critic — mid-task quality checkpoint."""

import json
import logging
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class CriticCheckpoint:
    round: int
    on_track: bool
    confidence: float
    progress_assessment: str
    main_concern: str
    pattern_match: str | None
    suggestion: str
    should_change_approach: bool
    approach_alternative: str | None
    cost: float


class InnerCritic:
    """Mid-task quality checkpoint. Advisory only — never controls execution."""

    # Checkpoint at 40% and 75% of max_rounds
    CHECKPOINT_PERCENTAGES = [0.40, 0.75]

    def __init__(self, llm_client, wisdom_path: Path, episodic_search_fn, max_rounds: int = 25):
        self.llm = llm_client
        self.wisdom_path = wisdom_path
        self.episodic_search = episodic_search_fn  # async fn(query, k) -> list[dict]
        self.max_rounds = max_rounds
        self.checkpoint_rounds = [
            int(max_rounds * pct) for pct in self.CHECKPOINT_PERCENTAGES
        ]
        self.checkpoints_done: list[CriticCheckpoint] = []
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

    async def evaluate(self, context: dict) -> str | None:
        """Run critic checkpoint. Returns formatted feedback string or None.

        Args:
            context: dict with keys matching critic_context spec above

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
                    similar_tasks = await self.episodic_search(
                        context.get("original_task", ""), k=3
                    )
                except Exception as e:
                    logger.warning(f"Episodic search for critic failed: {e}")

            # Build prompt
            prompt = self._build_prompt(context, known_patterns, similar_tasks)

            # Call LLM (Sonnet — same tier as primary)
            response = await self.llm.chat(
                model="anthropic/claude-sonnet-4.6",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                temperature=0.1,  # Low temp for consistent evaluation
            )

            # Parse response
            result = self._parse_response(response)
            if not result:
                return None

            # Record checkpoint
            checkpoint = CriticCheckpoint(
                round=context["current_round"],
                on_track=result["on_track"],
                confidence=result["confidence"],
                progress_assessment=result["progress_assessment"],
                main_concern=result["main_concern"],
                pattern_match=result.get("pattern_match"),
                suggestion=result["suggestion"],
                should_change_approach=result.get("should_change_approach", False),
                approach_alternative=result.get("approach_alternative"),
                cost=0.0,  # Filled by caller from LLM response metadata
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
            return self._format_feedback(checkpoint, context["current_round"], self.max_rounds)

        except Exception as e:
            logger.warning(f"Inner critic checkpoint failed (non-fatal): {e}")
            return None

    def get_summary(self) -> dict:
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

    def _load_relevant_patterns(self, task_type: str) -> list[str]:
        """Extract failure patterns from wisdom.md relevant to task type."""
        patterns = []
        if not self.wisdom_path.exists():
            return patterns

        try:
            content = self.wisdom_path.read_text()
            lines = content.split("\n")
            for line in lines:
                lower = line.lower()
                if any(kw in lower for kw in ["failure", "lesson", "mistake", "avoid", "don't", "never"]):
                    pattern = line.strip("- #*").strip()
                    if pattern and len(pattern) > 10:
                        patterns.append(pattern)

            # Hardcoded patterns from key lessons
            hardcoded = [
                "Scope creep after write_file: task 'rewrite prompt' spent 14 extra rounds on deploy/test",
                "Flash-lite returns tiny responses but not empty — loops without progress",
                "Announcement without execution: plans get stated but work doesn't start",
                "Same shell command repeated 3+ times usually means wrong approach, not bad luck",
                "Deploy tasks waste rounds figuring out current state — check status first",
            ]
            patterns.extend(hardcoded)

        except Exception as e:
            logger.warning(f"Failed to load wisdom patterns: {e}")

        return patterns[:10]  # Cap at 10 to keep prompt manageable

    def _build_prompt(self, context: dict, known_patterns: list[str], similar_tasks: list[dict]) -> str:
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
            original_task=context["original_task"],
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

    def _parse_response(self, response: str) -> dict | None:
        """Parse JSON response from critic LLM call."""
        try:
            text = response.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

            result = json.loads(text)

            required = ["on_track", "confidence", "progress_assessment", "main_concern", "suggestion"]
            for field in required:
                if field not in result:
                    logger.warning(f"Critic response missing field: {field}")
                    return None

            return result
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to parse critic response: {e}")
            return None

    def _format_feedback(self, cp: CriticCheckpoint, current_round: int, max_rounds: int) -> str:
        """Format checkpoint into injectable feedback string."""
        lines = [
            "",
            f"━━━ INNER CRITIC — Checkpoint at round {current_round}/{max_rounds} ━━━",
            "",
            f"Progress: {cp.progress_assessment}",
            f"On track: {'Yes' if cp.on_track else 'WARNING — NO'} (confidence: {cp.confidence})",
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
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
        ])

        return "\n".join(lines)
```

---

## Integration with loop.py

### Single integration point

In `run_llm_loop`, after each round completes and before the next round starts:

```python
# After round N completes, before round N+1:

# Inner Critic checkpoint
if inner_critic and inner_critic.should_run(round_count, total_cost):
    critic_context = _build_critic_context(
        original_task=task,
        task_type=task_type,
        current_round=round_count,
        max_rounds=MAX_ROUNDS,
        total_cost_so_far=total_cost,
        tool_call_history=tool_call_history,
        response_lengths=response_lengths[-3:],
    )
    feedback = await inner_critic.evaluate(critic_context)
    if feedback:
        # Inject as system message in conversation
        messages.append({
            "role": "system",
            "content": feedback,
        })
        # Log the checkpoint
        emit_event("inner_critic_checkpoint", {
            "round": round_count,
            "on_track": inner_critic.checkpoints_done[-1].on_track,
            "concern": inner_critic.checkpoints_done[-1].main_concern,
        })
```

### Context builder helper (in loop.py)

```python
def _build_critic_context(
    original_task: str,
    task_type: str,
    current_round: int,
    max_rounds: int,
    total_cost_so_far: float,
    tool_call_history: list[dict],
    response_lengths: list[int],
) -> dict:
    """Build context dict for inner critic evaluation."""

    # Summarize tool calls (don't send full payloads)
    summarized_tools = []
    for tc in tool_call_history:
        summarized_tools.append({
            "round": tc.get("round", 0),
            "tool": tc.get("tool", "unknown"),
            "success": tc.get("success", False),
            "summary": tc.get("result_summary", "")[:100],
        })

    # Detect repeated tool calls
    from collections import Counter
    tool_signatures = [
        f"{tc.get('tool', '')}:{tc.get('args_hash', '')}"
        for tc in tool_call_history
    ]
    repeated = [
        {"tool": sig.split(":")[0], "count": count, "pattern": sig}
        for sig, count in Counter(tool_signatures).items()
        if count >= 3
    ]

    # Collect files written and read
    files_written = list({
        tc.get("args", {}).get("path", "")
        for tc in tool_call_history
        if tc.get("tool") in ("repo_write", "write_file", "create_file")
        and tc.get("success")
    })
    files_read = list({
        tc.get("args", {}).get("path", "")
        for tc in tool_call_history
        if tc.get("tool") in ("repo_read", "read_file", "cat")
        and tc.get("success")
    })

    return {
        "original_task": original_task,
        "task_type": task_type,
        "current_round": current_round,
        "max_rounds": max_rounds,
        "total_cost_so_far": total_cost_so_far,
        "tool_calls": summarized_tools,
        "files_written": [f for f in files_written if f],
        "files_read": [f for f in files_read if f],
        "last_3_responses_lengths": response_lengths,
        "repeated_tool_calls": repeated,
    }
```

### Task result logging

After task completes, include critic summary in task result:

```python
# In task result dict:
if inner_critic:
    task_result["inner_critic"] = inner_critic.get_summary()
```

---

## Feedback → Skill Pipeline

When a critic checkpoint identifies a pattern match and the agent successfully course-corrects:

```python
# After task completes successfully AND critic flagged an issue AND agent changed approach:
if (
    inner_critic
    and inner_critic.get_summary()["any_off_track"]
    and task_result["success"]
):
    # The correction worked — save as skill
    for cp in inner_critic.checkpoints_done:
        if not cp.on_track and cp.suggestion:
            skill_content = (
                f"TASK TYPE: {task_type}\n"
                f"PATTERN: {cp.pattern_match or cp.main_concern}\n"
                f"CORRECTION: {cp.suggestion}\n"
                f"OUTCOME: Task succeeded after course correction at round {cp.round}\n"
            )
            await skill_manager.save_skill(
                name=f"critic-correction-{task_type}",
                content=skill_content,
                source="inner_critic",
            )
```

This creates a **closed learning loop**: critic observes → agent corrects → correction saved as skill → future tasks start with that knowledge via memory protocol → critic sees fewer issues.

---

## Interaction with Existing Systems

### What the critic does NOT replace

| Existing mechanism | Still needed? | Why |
|-------------------|---------------|-----|
| Stuck detector | Yes | Catches identical thoughts in consciousness cycle (between tasks) |
| Circuit breaker | Yes | Catches empty LLM responses (hard failure) |
| Scope boundary | Yes | Deterministic, free, catches write_file scope creep immediately |
| Model escalation | Yes | Catches flash-lite output degradation (token-level) |
| Experiment engine | Yes | Operates on statistical patterns across many tasks |

The critic operates **within a single task** at the semantic level. Everything above operates at the mechanical level or across tasks. No overlap.

### What the critic enhances

| System | Enhancement |
|--------|-------------|
| Skill lifecycle | Critic feedback saved as skill when task type repeats |
| Experiment engine | Critic data (`any_off_track`, checkpoint count) becomes a metric for pattern detector |
| Consciousness dashboard | New metric: `critic_interventions_today`, `critic_accuracy` (was it right?) |
| wisdom.md | Confirmed critic patterns added to known failures |

---

## Cost Analysis

| Component | Cost per task | Notes |
|-----------|--------------|-------|
| Checkpoint 1 (round 10) | ~$0.01-0.02 | Sonnet, ~500 input tokens context + 200 output |
| Checkpoint 2 (round 19) | ~$0.01-0.02 | Same, slightly larger context |
| Skip optimization | Saves ~$0.01-0.02 | When checkpoint 1 says on_track with >=0.9 confidence |
| **Expected average** | **~$0.015/task** | ~60% of tasks skip checkpoint 2 |

With ~10-15 tasks/day: **~$0.15-0.23/day** additional cost.

Net positive: catching bad tasks early saves $0.30-0.50 per caught task in wasted rounds.

---

## Safety Constraints

| Constraint | Value | Why |
|-----------|-------|-----|
| Advisory only | Never stops/reverts | THAI makes all decisions (BIBLE P6) |
| Same-tier model | Sonnet for critic | Critic must be >= agent intelligence |
| Max cost per checkpoint | $0.03 | Hard cap, abort if exceeded |
| Max checkpoints per task | 2 | Don't overwhelm agent with feedback |
| Skip on high confidence | >=0.9 on_track | Don't waste budget on healthy tasks |
| Skip on high task cost | >$4.00 | Preserve budget for completion |
| Non-fatal on error | try/except everything | Critic failure = no feedback, task continues normally |
| No Shareholder messages | Never | Critic is internal to THAI |
| Structured output only | JSON schema enforced | No freeform "advice" that could confuse agent |

---

## Observability

### Events emitted

```python
# On each checkpoint:
emit_event("inner_critic_checkpoint", {
    "task_id": task_id,
    "round": current_round,
    "on_track": result["on_track"],
    "confidence": result["confidence"],
    "main_concern": result["main_concern"],
    "pattern_match": result.get("pattern_match"),
    "suggestion": result["suggestion"],
    "cost": checkpoint_cost,
})

# On checkpoint skip (high confidence):
emit_event("inner_critic_skipped", {
    "task_id": task_id,
    "reason": "high_confidence_on_track",
    "first_checkpoint_confidence": 0.95,
})
```

### Consciousness Dashboard integration

New metrics for the dashboard:

```python
"inner_critic": {
    "checkpoints_today": int,           # Total checkpoint calls
    "off_track_alerts": int,            # Times critic said not on_track
    "course_corrections": int,          # Off-track followed by successful task
    "correction_success_rate": float,   # course_corrections / off_track_alerts
    "total_critic_cost": float,         # Sum of checkpoint costs
    "patterns_matched": list[str],      # Which known patterns were flagged
    "skills_created_from_corrections": int,  # Feedback -> skill pipeline output
}
```

---

## Testing Plan

1. **Unit test `inner_critic.py`:**
   - `should_run()` — correct rounds, skip after high confidence, skip on high cost
   - `_parse_response()` — valid JSON, missing fields, malformed response
   - `_format_feedback()` — correct formatting for on_track and off_track
   - `_load_relevant_patterns()` — extracts from wisdom.md, includes hardcoded
   - `_build_prompt()` — all fields populated, handles empty lists

2. **Mock LLM test:**
   - Simulate on_track response → verify skip logic
   - Simulate off_track response → verify feedback injection format
   - Simulate LLM failure → verify non-fatal handling

3. **Integration test with loop.py:**
   - Run mock task for 15 rounds → verify checkpoint triggers at round 10
   - Verify feedback appears in messages list
   - Verify task_result contains critic summary

4. **Feedback → Skill pipeline test:**
   - Mock off_track checkpoint + successful task → verify skill saved
   - Mock on_track checkpoint + successful task → verify no skill saved

5. **Smoke tests:**
   - Existing 5 smoke tests still pass
   - Inner critic import doesn't break tool registry

---

## File Zones

| File | Zone | Notes |
|------|------|-------|
| `ouroboros/inner_critic.py` | Green (new) | Self-contained, no external deps beyond LLM client |
| `ouroboros/loop.py` | Yellow | Add checkpoint call (~15 lines) + context builder (~40 lines) |
| `scripts/consciousness_metrics.py` | Green | Add inner_critic metrics section |
| `company/dashboard/consciousness-dashboard.html` | Green | Add inner_critic widget |

---

## Implementation Order

1. `inner_critic.py` — full class with prompt, parser, formatter
2. Unit tests (mock LLM, mock wisdom.md)
3. `loop.py` integration — checkpoint call + context builder
4. Feedback → Skill pipeline in loop.py
5. Events emission
6. Integration test
7. `consciousness_metrics.py` — add inner_critic metrics
8. Dashboard update
9. Smoke tests
10. Commit + push (single branch: `feat/inner-critic`)

---

## Expected Impact

| Metric | Before | After (2 weeks) |
|--------|--------|------------------|
| Tasks hitting MAX_ROUNDS on wrong approach | ~20% | ~5% |
| Average rounds for complex tasks | 12-15 | 8-10 |
| Known failure pattern repetition | Frequent | Rare (flagged at round 10) |
| Critic cost overhead | $0 | ~$0.15-0.23/day |
| Net cost savings (fewer wasted rounds) | — | ~$0.50-1.00/day |
| Meta-cognition score contribution | 0 | +1.0-1.5 (real-time self-awareness) |

---

## Relationship to Other Systems

```
                          ┌─────────────────┐
                          │   BIBLE.md P6   │
                          │   Responsible    │
                          │   Freedom        │
                          └────────┬────────┘
                                   │ advisory, not executive
                                   │
┌──────────────┐          ┌────────┴────────┐          ┌──────────────────┐
│ Skill        │◄─────────│  Inner Critic   │─────────►│ Experiment       │
│ Lifecycle    │ saves    │  (mid-task      │ feeds    │ Engine           │
│              │corrections│  checkpoints)  │ metrics  │ (cross-task      │
└──────────────┘          └────────┬────────┘          │  patterns)       │
                                   │                    └──────────────────┘
                                   │ injects feedback
                                   ▼
                          ┌─────────────────┐
                          │    loop.py      │
                          │  (tool loop     │
                          │   execution)    │
                          └─────────────────┘

Within-task quality:  Inner Critic (semantic, Sonnet, advisory)
Within-task safety:   Stuck detector, circuit breaker, scope boundary, model escalation (mechanical)
Cross-task learning:  Experiment Engine + Skill Lifecycle (statistical + knowledge)
```

Inner Critic fills the gap between mechanical within-task checks and statistical cross-task learning.
It is the only component that evaluates *semantic quality* of work in progress.
