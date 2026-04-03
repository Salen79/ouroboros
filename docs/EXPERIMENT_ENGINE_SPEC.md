# Behavioral experiment engine — meta-cognition spec

## Problem

THAI's consciousness.py reflects after tasks but produces only "insights" — vague observations that don't change behavior. 72 episodes recorded, 0 led to autonomous behavioral improvements. All real improvements (memory protocol, stuck detector, dedup) were done manually by Shareholder + Claude Code.

Meta-cognition score: 2/10. THAI observes but doesn't hypothesize, experiment, or measure.

## Dependency

Requires working **skill lifecycle system** (SKILL_LIFECYCLE_SPEC.md). The experiment engine creates/modifies skills and uses skill validation scores to measure outcomes.

## Solution

Four-component engine implementing the scientific method for self-improvement:

```
Pattern Detector → Hypothesis Generator → Experiment Runner → Measurement Engine
      ↑                                                              |
      └──────────── failed experiments feed new patterns ────────────┘
```

All steps code-enforced. LLM used only for hypothesis formulation (structured JSON output).

---

## Component 1: Pattern Detector

**File:** `ouroboros/pattern_detector.py` (~120 lines)
**Zone:** Green (new file)
**LLM:** None — pure Python statistics

### What it does

Scans `~/ouroboros-data/task_results/` and `events.jsonl`, groups tasks by type, computes statistics, identifies improvement opportunities.

### When it runs

- Triggered by consciousness.py during background cycle
- Maximum once per 7 days (tracked in `state/experiments.json`)
- Can be triggered manually via `/analyze` Telegram command

### Algorithm

```python
class PatternDetector:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

    def analyze(self, lookback_days: int = 30) -> list[dict]:
        """Analyze task history and return actionable patterns."""
        tasks = self._load_task_results(lookback_days)
        if len(tasks) < 10:
            return []  # Not enough data

        # Group tasks by similarity
        groups = self._group_by_type(tasks)

        patterns = []
        for group_name, group_tasks in groups.items():
            if len(group_tasks) < 3:
                continue  # Need at least 3 instances

            stats = self._compute_stats(group_tasks)

            # Pattern 1: Expensive repeated tasks (opportunity for skill)
            if stats["avg_rounds"] > 5 and stats["count"] >= 3:
                patterns.append({
                    "type": "expensive_repeat",
                    "group": group_name,
                    "count": stats["count"],
                    "avg_rounds": stats["avg_rounds"],
                    "avg_cost": stats["avg_cost"],
                    "total_cost": stats["total_cost"],
                    "sample_task_ids": stats["sample_ids"][:3],
                    "potential_savings": f"${stats['total_cost'] * 0.7:.2f}",
                })

            # Pattern 2: Recurring errors
            if stats["error_rate"] > 0.3:
                patterns.append({
                    "type": "recurring_error",
                    "group": group_name,
                    "count": stats["count"],
                    "error_rate": stats["error_rate"],
                    "common_errors": stats["common_errors"][:3],
                    "sample_task_ids": stats["sample_ids"][:3],
                })

            # Pattern 3: Getting worse over time
            if stats["trend"] == "degrading":
                patterns.append({
                    "type": "degrading_performance",
                    "group": group_name,
                    "recent_avg_rounds": stats["recent_avg"],
                    "older_avg_rounds": stats["older_avg"],
                    "sample_task_ids": stats["sample_ids"][:3],
                })

        # Sort by potential impact (total_cost for expensive, error_rate for errors)
        patterns.sort(key=lambda p: p.get("total_cost", 0) + p.get("error_rate", 0), reverse=True)
        return patterns[:3]  # Top 3 patterns only

    def _group_by_type(self, tasks: list[dict]) -> dict:
        """Group tasks by semantic similarity.

        Uses simple keyword extraction, not LLM.
        Groups by: primary tool used + action verb in task description.
        Example groups: 'shell_exec:deploy', 'shell_exec:check', 'git:commit'
        """
        groups = defaultdict(list)
        for task in tasks:
            # Extract primary tool from tool_calls
            tools = [tc.get("tool", "") for tc in task.get("tool_calls", [])]
            primary_tool = Counter(tools).most_common(1)[0][0] if tools else "unknown"

            # Extract action keywords from task description
            desc = task.get("task", "").lower()
            action = "other"
            for keyword in ["deploy", "check", "fix", "create", "update", "analyze", "test", "search", "review"]:
                if keyword in desc:
                    action = keyword
                    break

            group_key = f"{primary_tool}:{action}"
            groups[group_key].append(task)

        return dict(groups)

    def _compute_stats(self, tasks: list[dict]) -> dict:
        """Compute statistics for a task group."""
        rounds = [t.get("rounds", 0) for t in tasks]
        costs = [t.get("cost", 0) for t in tasks]
        successes = [t.get("success", False) for t in tasks]

        # Split into recent (last 7 days) vs older for trend detection
        now = datetime.utcnow()
        recent = [t for t in tasks if (now - parse_ts(t)).days <= 7]
        older = [t for t in tasks if (now - parse_ts(t)).days > 7]

        recent_avg = mean([t.get("rounds", 0) for t in recent]) if recent else 0
        older_avg = mean([t.get("rounds", 0) for t in older]) if older else 0

        trend = "stable"
        if recent_avg > older_avg * 1.3 and len(recent) >= 2 and len(older) >= 2:
            trend = "degrading"
        elif recent_avg < older_avg * 0.7 and len(recent) >= 2 and len(older) >= 2:
            trend = "improving"

        return {
            "count": len(tasks),
            "avg_rounds": round(mean(rounds), 1),
            "avg_cost": round(mean(costs), 3),
            "total_cost": round(sum(costs), 2),
            "error_rate": round(1 - mean(successes), 2),
            "common_errors": self._extract_common_errors(tasks),
            "trend": trend,
            "recent_avg": round(recent_avg, 1),
            "older_avg": round(older_avg, 1),
            "sample_ids": [t.get("task_id", "") for t in tasks[:5]],
        }
```

### Output example

```json
[
  {
    "type": "expensive_repeat",
    "group": "shell_exec:deploy",
    "count": 8,
    "avg_rounds": 9.2,
    "avg_cost": 0.38,
    "total_cost": 3.04,
    "potential_savings": "$2.13",
    "sample_task_ids": ["task_abc", "task_def", "task_ghi"]
  },
  {
    "type": "recurring_error",
    "group": "shell_exec:check",
    "count": 5,
    "error_rate": 0.4,
    "common_errors": ["service not found", "permission denied"]
  }
]
```

---

## Component 2: Hypothesis Generator

**File:** `ouroboros/experiment_engine.py` (part of class)
**Zone:** Green (new file)
**LLM:** One call per hypothesis, Gemini Flash Lite (~$0.001)

### What it does

Takes a pattern from detector + sample tool histories, produces a testable hypothesis with structured JSON output.

### Constraints

- Only proposes GREEN ZONE actions:
  - `save_skill` — create a new skill procedure
  - `update_skill` — modify existing skill
  - `add_knowledge` — add to knowledge base
- NEVER proposes code changes (that's self-evolution, yellow/red zone)
- NEVER proposes prompt changes to SYSTEM.md
- Max budget per hypothesis generation: $0.005

### Prompt template

```python
HYPOTHESIS_PROMPT = """You are analyzing an AI agent's behavioral pattern.

PATTERN:
{pattern_json}

SAMPLE TASK TOOL HISTORIES (showing what the agent actually did):
{tool_histories}

EXISTING SKILLS:
{existing_skills}

Generate a testable hypothesis to improve this pattern.
You may ONLY propose these actions:
- save_skill: create a reusable step-by-step procedure
- update_skill: improve an existing skill with better steps
- add_knowledge: save a fact or rule to knowledge base

Respond in JSON only, no markdown:
{
  "hypothesis": "one sentence: if we do X, then Y will improve because Z",
  "action_type": "save_skill" | "update_skill" | "add_knowledge",
  "action_content": "the actual skill/knowledge content to save",
  "action_name": "short-kebab-name",
  "metric": "avg_rounds" | "error_rate" | "avg_cost",
  "baseline": <current value from pattern>,
  "target": <target value, must be at least 30% better>,
  "max_tasks": <how many matching tasks before we evaluate, 3-10>,
  "max_days": 14
}

If the pattern doesn't suggest a clear improvement, respond: {"skip": true, "reason": "..."}
"""
```

### Output example

```json
{
  "hypothesis": "If deploy tasks start with systemctl status check, avg_rounds will drop from 9.2 to 4 because most time is spent figuring out current state",
  "action_type": "save_skill",
  "action_content": "SKILL: deploy-with-precheck\n1. Run systemctl status for target service\n2. Check current git branch and last commit\n3. Run deployment command\n4. Verify service restarted\n5. Run health check",
  "action_name": "deploy-with-precheck",
  "metric": "avg_rounds",
  "baseline": 9.2,
  "target": 4,
  "max_tasks": 5,
  "max_days": 14
}
```

---

## Component 3: Experiment Runner

**File:** `ouroboros/experiment_engine.py` (part of class)
**Zone:** Green
**LLM:** None — executes actions via existing tools

### What it does

Takes hypothesis JSON, executes the action, records the experiment in state file.

### Safety constraints

- Max 2 active experiments simultaneously (avoid confounding)
- Max 1 new experiment per week
- Cooldown: 3 days after experiment concludes before starting new one
- All actions are reversible (skills can be deleted, knowledge can be removed)
- No experiment modifies code, only data (skills, knowledge)

### State file: `~/ouroboros-data/state/experiments.json`

```json
{
  "last_analysis": "2026-04-03T10:00:00Z",
  "last_experiment_started": "2026-04-03T10:05:00Z",
  "experiments": [
    {
      "id": "exp_001",
      "status": "active",
      "hypothesis": "If deploy tasks start with status check...",
      "action_type": "save_skill",
      "action_name": "deploy-with-precheck",
      "action_id": "chromadb-skill-uuid-here",
      "metric": "avg_rounds",
      "baseline": 9.2,
      "target": 4.0,
      "max_tasks": 5,
      "max_days": 14,
      "started": "2026-04-03T10:05:00Z",
      "expires": "2026-04-17T10:05:00Z",
      "matching_tasks": [
        {"task_id": "t1", "rounds": 5, "cost": 0.12, "success": true, "date": "2026-04-05"},
        {"task_id": "t2", "rounds": 3, "cost": 0.08, "success": true, "date": "2026-04-07"}
      ],
      "verdict": null
    }
  ],
  "completed": [
    {
      "id": "exp_000",
      "status": "confirmed",
      "hypothesis": "...",
      "result_avg": 3.8,
      "baseline": 9.2,
      "improvement": "58.7%",
      "concluded": "2026-04-15T12:00:00Z"
    }
  ]
}
```

### Implementation

```python
class ExperimentEngine:
    def __init__(self, state_path, skill_manager, knowledge_tools, llm_client):
        self.state_path = state_path
        self.skill_manager = skill_manager
        self.knowledge = knowledge_tools
        self.llm = llm_client
        self.state = self._load_state()

    def can_start_new(self) -> bool:
        """Check all safety constraints."""
        active = [e for e in self.state["experiments"] if e["status"] == "active"]
        if len(active) >= 2:
            return False  # Max 2 concurrent

        last_started = self.state.get("last_experiment_started")
        if last_started:
            days_since = (utcnow() - parse(last_started)).days
            if days_since < 7:
                return False  # Max 1 per week

        # Cooldown after last completed experiment
        if self.state.get("completed"):
            last_concluded = self.state["completed"][-1].get("concluded")
            if last_concluded:
                days_since = (utcnow() - parse(last_concluded)).days
                if days_since < 3:
                    return False  # 3-day cooldown

        return True

    async def run_full_cycle(self) -> str | None:
        """Main entry: detect patterns → hypothesize → start experiment.

        Called from consciousness.py during background cycle.
        Returns experiment ID if started, None otherwise.
        """
        # Check timing
        last_analysis = self.state.get("last_analysis")
        if last_analysis:
            days_since = (utcnow() - parse(last_analysis)).days
            if days_since < 7:
                return None  # Already analyzed this week

        if not self.can_start_new():
            return None

        # Step 1: Detect patterns
        detector = PatternDetector(self.data_dir)
        patterns = detector.analyze(lookback_days=30)
        self.state["last_analysis"] = utcnow().isoformat()
        self._save_state()

        if not patterns:
            return None  # Nothing to improve

        # Step 2: Generate hypothesis for top pattern
        pattern = patterns[0]
        tool_histories = self._load_sample_histories(pattern["sample_task_ids"])
        existing_skills = self._load_existing_skills(pattern["group"])

        hypothesis = await self._generate_hypothesis(pattern, tool_histories, existing_skills)
        if not hypothesis or hypothesis.get("skip"):
            return None

        # Step 3: Execute action
        action_id = await self._execute_action(hypothesis)
        if not action_id:
            return None

        # Step 4: Record experiment
        experiment = {
            "id": f"exp_{len(self.state['experiments']):03d}",
            "status": "active",
            "hypothesis": hypothesis["hypothesis"],
            "action_type": hypothesis["action_type"],
            "action_name": hypothesis["action_name"],
            "action_id": action_id,
            "metric": hypothesis["metric"],
            "baseline": hypothesis["baseline"],
            "target": hypothesis["target"],
            "max_tasks": hypothesis.get("max_tasks", 5),
            "max_days": hypothesis.get("max_days", 14),
            "started": utcnow().isoformat(),
            "expires": (utcnow() + timedelta(days=hypothesis.get("max_days", 14))).isoformat(),
            "matching_tasks": [],
            "verdict": None,
        }

        self.state["experiments"].append(experiment)
        self.state["last_experiment_started"] = utcnow().isoformat()
        self._save_state()

        return experiment["id"]

    async def _execute_action(self, hypothesis: dict) -> str | None:
        """Execute the proposed action. Returns action ID for tracking."""
        action_type = hypothesis["action_type"]
        content = hypothesis["action_content"]
        name = hypothesis["action_name"]

        if action_type == "save_skill":
            # Use skill_manager to save
            import uuid
            skill_id = str(uuid.uuid4())
            self.skill_manager.skills_collection.add(
                ids=[skill_id],
                documents=[content],
                metadatas={
                    "type": "skill",
                    "name": name,
                    "source": "experiment",
                    "times_used": 0,
                    "score": 0,
                }
            )
            return skill_id

        elif action_type == "update_skill":
            existing = self.skill_manager.find_duplicate(name)
            if existing:
                self.skill_manager.skills_collection.update(
                    ids=[existing["id"]],
                    documents=[content]
                )
                return existing["id"]
            return None

        elif action_type == "add_knowledge":
            # Write to knowledge base
            filepath = self.knowledge.write(name, content)
            return filepath

        return None
```

---

## Component 4: Measurement Engine

**File:** `ouroboros/experiment_engine.py` (part of class)
**Zone:** Green
**LLM:** None — pure statistics

### Integration point in loop.py

After every task completes, check if it matches any active experiment:

```python
# At end of run_llm_loop, after skill_manager.process_completed_task:
try:
    engine = ExperimentEngine(state_path, skill_manager, knowledge, llm)
    engine.record_task_for_experiments({
        "task": original_task,
        "rounds": round_count,
        "cost": total_cost,
        "success": not error,
        "task_id": task_id,
        "tools_used": [tc["tool"] for tc in tool_call_history],
    })
except Exception as e:
    logger.warning(f"Experiment tracking failed (non-fatal): {e}")
```

### Matching logic

```python
def record_task_for_experiments(self, task_result: dict):
    """Check if completed task matches any active experiment."""
    for exp in self.state["experiments"]:
        if exp["status"] != "active":
            continue

        # Check if expired
        if utcnow() > parse(exp["expires"]):
            self._conclude_experiment(exp, reason="expired")
            continue

        # Match by action_name keyword overlap with task description
        if self._task_matches_experiment(task_result, exp):
            exp["matching_tasks"].append({
                "task_id": task_result["task_id"],
                "rounds": task_result["rounds"],
                "cost": task_result["cost"],
                "success": task_result["success"],
                "date": utcnow().isoformat(),
            })
            self._save_state()

            # Check if we have enough data
            if len(exp["matching_tasks"]) >= exp["max_tasks"]:
                self._conclude_experiment(exp, reason="enough_data")

def _conclude_experiment(self, exp: dict, reason: str):
    """Evaluate experiment results and issue verdict."""
    tasks = exp["matching_tasks"]

    if not tasks:
        exp["status"] = "inconclusive"
        exp["verdict"] = "No matching tasks during experiment window"
        self._move_to_completed(exp)
        return

    # Compute result metric
    metric = exp["metric"]
    if metric == "avg_rounds":
        result = mean([t["rounds"] for t in tasks])
    elif metric == "avg_cost":
        result = mean([t["cost"] for t in tasks])
    elif metric == "error_rate":
        result = 1 - mean([t["success"] for t in tasks])
    else:
        result = mean([t["rounds"] for t in tasks])

    baseline = exp["baseline"]
    target = exp["target"]

    # Verdict
    improvement = (baseline - result) / baseline if baseline > 0 else 0

    if result <= target:
        exp["status"] = "confirmed"
        exp["verdict"] = f"Target met: {result:.1f} (target: {target}, baseline: {baseline})"
        # Skill stays permanent, record in wisdom
        self._record_in_wisdom(exp, result, improvement)
    elif result < baseline:
        exp["status"] = "partial"
        exp["verdict"] = f"Improved but missed target: {result:.1f} (target: {target}, baseline: {baseline})"
        # Keep skill but don't celebrate
    else:
        exp["status"] = "failed"
        exp["verdict"] = f"No improvement: {result:.1f} (baseline: {baseline})"
        # REVERT: remove skill/knowledge
        self._revert_action(exp)

    exp["result_value"] = round(result, 2)
    exp["improvement_pct"] = f"{improvement*100:.1f}%"
    exp["concluded"] = utcnow().isoformat()
    exp["conclusion_reason"] = reason

    self._move_to_completed(exp)
    self._save_state()

def _revert_action(self, exp: dict):
    """Undo the experiment's action."""
    if exp["action_type"] in ("save_skill", "update_skill"):
        try:
            self.skill_manager.skills_collection.delete(ids=[exp["action_id"]])
        except Exception:
            pass
    elif exp["action_type"] == "add_knowledge":
        try:
            Path(exp["action_id"]).unlink(missing_ok=True)
        except Exception:
            pass

def _record_in_wisdom(self, exp: dict, result: float, improvement: float):
    """Record confirmed experiment in wisdom.md."""
    entry = (
        f"\n## Experiment {exp['id']} — CONFIRMED\n"
        f"Hypothesis: {exp['hypothesis']}\n"
        f"Result: {exp['metric']} improved from {exp['baseline']} to {result:.1f} "
        f"({improvement*100:.1f}% improvement)\n"
        f"Action: {exp['action_type']} '{exp['action_name']}'\n"
        f"Date: {exp['concluded']}\n"
    )
    wisdom_path = self.data_dir / "memory" / "wisdom.md"
    with open(wisdom_path, "a") as f:
        f.write(entry)
```

---

## Integration with consciousness.py

### Where it hooks in

In `BackgroundConsciousness`, after the existing reflection cycle:

```python
# Existing: reflection, stuck detection, commitment check
# NEW: experiment engine cycle
try:
    engine = ExperimentEngine(state_path, skill_manager, knowledge, llm)

    # Try to start new experiment (respects all cooldowns)
    new_exp = await engine.run_full_cycle()
    if new_exp:
        await self._notify_shareholder(
            f"Started experiment {new_exp}: {engine.get_experiment(new_exp)['hypothesis']}"
        )

    # Report on any just-concluded experiments
    recent = engine.get_recently_concluded(hours=24)
    for exp in recent:
        await self._notify_shareholder(
            f"Experiment {exp['id']} → {exp['status']}: {exp['verdict']}"
        )
except Exception as e:
    logger.warning(f"Experiment engine error (non-fatal): {e}")
```

---

## Shareholder visibility

THAI reports to Shareholder via Telegram at these moments:
- New experiment started: hypothesis + what will be measured
- Experiment concluded: verdict + numbers
- Weekly summary: active experiments + patterns detected

New Telegram command: `/experiments` — shows active + recent experiments.

---

## File zones

| File | Zone | Notes |
|------|------|-------|
| `ouroboros/pattern_detector.py` | Green (new) | Pure Python, no dependencies |
| `ouroboros/experiment_engine.py` | Green (new) | Main engine class |
| `ouroboros/loop.py` | Yellow | Add experiment tracking after task |
| `ouroboros/consciousness.py` | Yellow | Add experiment cycle to background loop |
| `ouroboros-data/state/experiments.json` | Data | Auto-created |

---

## Safety summary

| Constraint | Value | Why |
|-----------|-------|-----|
| Max concurrent experiments | 2 | Avoid confounding |
| Max new experiments per week | 1 | Don't overwhelm system |
| Cooldown after conclusion | 3 days | Let baseline stabilize |
| Allowed actions | save_skill, update_skill, add_knowledge | Green zone only |
| Forbidden actions | Code changes, prompt changes, config | Self-evolution territory |
| Auto-revert on failure | Yes | Delete skill/knowledge if metric worsened |
| Experiment max duration | 14 days | Don't let stale experiments linger |
| Min tasks for conclusion | 3 | Need statistical minimum |
| LLM budget per hypothesis | $0.005 max | Gemini Flash Lite |
| Shareholder notification | Always | Full transparency (P10) |

---

## Testing plan

1. Unit test `pattern_detector.py` — mock task_results, verify grouping and stats
2. Unit test `experiment_engine.py` — mock ChromaDB, mock LLM, verify full cycle
3. Smoke test — existing 5 tests still pass
4. Integration: seed 20 fake task_results, run pattern detector, verify it finds patterns
5. End-to-end: trigger full cycle, verify experiment created in state file
6. Revert test: create experiment, simulate failed tasks, verify skill deleted

---

## Implementation order

1. `pattern_detector.py` — pure Python, easy to test independently
2. `experiment_engine.py` — hypothesis generator + runner + measurement
3. Unit tests for both
4. `loop.py` — add experiment tracking (1 integration point)
5. `consciousness.py` — add experiment cycle (1 integration point)
6. Telegram `/experiments` command
7. Smoke tests + integration test
8. Commit + push

## Expected impact

| Metric | Before | After (2 months) |
|--------|--------|-------------------|
| Meta-cognition score | 2/10 | 6-7/10 |
| Self-initiated improvements | 0 | 4-8 confirmed experiments |
| Repeated task cost trend | Flat | Declining |
| Behavioral changes from reflection | 0% | 30-50% |
| Shareholder intervention needed | Always | For red-zone only |

## Relationship to other systems

```
                    ┌─────────────────┐
                    │   BIBLE.md P17  │
                    │ Self-Evolution  │
                    │ (code changes)  │
                    └────────┬────────┘
                             │ red/yellow zone
                             │
┌──────────────┐    ┌────────┴────────┐    ┌──────────────────┐
│ Skill        │◄───│   Experiment    │───►│ Pattern          │
│ Lifecycle    │    │   Engine        │    │ Detector         │
│ (creation,   │    │ (hypothesis,    │    │ (weekly scan,    │
│  validation) │    │  run, measure)  │    │  pure stats)     │
└──────────────┘    └─────────────────┘    └──────────────────┘
       │                    │
       │            green zone only
       │            (skills, knowledge)
       │
       ▼
┌──────────────────┐
│ consciousness.py │
│ (orchestrates    │
│  all cycles)     │
└──────────────────┘
```

Self-Evolution (P17) handles CODE changes through file zones.
Experiment Engine handles BEHAVIORAL changes through skills/knowledge.
They don't overlap — clear boundary.
