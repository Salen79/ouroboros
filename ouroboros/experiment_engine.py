"""
Ouroboros — Behavioral experiment engine.

Implements the scientific method for self-improvement:
  Pattern Detector → Hypothesis Generator → Experiment Runner → Measurement Engine

All steps code-enforced. LLM used only for hypothesis formulation (Gemini Flash Lite).
Only GREEN ZONE actions: save_skill, update_skill, add_knowledge.

Called from consciousness.py during background cycle.
Experiment tracking called from loop.py after each task.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional

from ouroboros.pattern_detector import PatternDetector

log = logging.getLogger(__name__)

# Timing constraints (from spec)
_ANALYSIS_COOLDOWN_DAYS = 1       # Daily analysis max
_NEW_EXPERIMENT_COOLDOWN_DAYS = 1 # Max 1 experiment/day
_POST_CONCLUSION_COOLDOWN_HOURS = 4  # 4h cooldown after conclusion
_MAX_CONCURRENT = 2               # Max active experiments
_MAX_EXPERIMENT_DAYS = 3          # Max experiment duration
_MIN_TASKS_FOR_CONCLUSION = 3     # Need at least 3 matching tasks

HYPOTHESIS_PROMPT = """You are analyzing an AI agent's behavioral pattern.

PATTERN:
{pattern_json}

SAMPLE TASK RESULTS (showing what the agent produced):
{task_summaries}

EXISTING SKILLS:
{existing_skills}

Generate a testable hypothesis to improve this pattern.
You may ONLY propose these actions:
- save_skill: create a reusable step-by-step procedure
- update_skill: improve an existing skill with better steps
- add_knowledge: save a fact or rule to knowledge base

Respond in JSON only, no markdown:
{{
  "hypothesis": "one sentence: if we do X, then Y will improve because Z",
  "action_type": "save_skill" | "update_skill" | "add_knowledge",
  "action_content": "the actual skill/knowledge content to save",
  "action_name": "short-kebab-name",
  "metric": "avg_rounds" | "error_rate" | "avg_cost",
  "baseline": <current value from pattern>,
  "target": <target value, must be at least 30% better>,
  "max_tasks": <how many matching tasks before we evaluate, 3-10>,
  "max_days": 3
}}

If the pattern doesn't suggest a clear improvement, respond: {{"skip": true, "reason": "..."}}
"""


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


class ExperimentEngine:
    """Behavioral experiment lifecycle: detect → hypothesize → run → measure."""

    def __init__(
        self,
        data_dir: Path,
        skill_manager,
        llm_client,
        event_emit_fn=None,
    ):
        """
        Args:
            data_dir: Path to ~/ouroboros-data/
            skill_manager: ouroboros.skill_manager.SkillManager instance
            llm_client: ouroboros.llm.LLMClient instance
            event_emit_fn: Optional callable(event: dict) emitting structured
                           events to events.jsonl. Used for experiment_started,
                           experiment_concluded, experiment_reverted (D2).
        """
        self.data_dir = data_dir
        self.skill_manager = skill_manager
        self.llm = llm_client
        self.state_path = data_dir / "state" / "experiments.json"
        self.state = self._load_state()
        self._event_emit_fn = event_emit_fn

    def _emit(self, event: dict) -> None:
        """Best-effort write to events.jsonl via injected callback."""
        if self._event_emit_fn is None:
            return
        try:
            self._event_emit_fn(event)
        except Exception:
            log.debug("event_emit_fn failed", exc_info=True)

    def _load_state(self) -> dict:
        state = _load_json(self.state_path)
        state.setdefault("last_analysis", None)
        state.setdefault("last_experiment_started", None)
        state.setdefault("experiments", [])
        state.setdefault("completed", [])
        return state

    def _save_state(self) -> None:
        _save_json(self.state_path, self.state)

    # ------------------------------------------------------------------
    # Safety constraints
    # ------------------------------------------------------------------

    def can_start_new(self) -> bool:
        """Check all safety constraints before starting a new experiment."""
        active = [e for e in self.state["experiments"] if e["status"] == "active"]
        if len(active) >= _MAX_CONCURRENT:
            return False

        last_started = self.state.get("last_experiment_started")
        if last_started:
            try:
                days_since = (_utcnow() - datetime.fromisoformat(last_started)).days
                if days_since < _NEW_EXPERIMENT_COOLDOWN_DAYS:
                    return False
            except (ValueError, TypeError):
                pass

        # Post-conclusion cooldown
        if self.state.get("completed"):
            last_concluded = self.state["completed"][-1].get("concluded")
            if last_concluded:
                try:
                    hours_since = (_utcnow() - datetime.fromisoformat(last_concluded)).total_seconds() / 3600
                    if hours_since < _POST_CONCLUSION_COOLDOWN_HOURS:
                        return False
                except (ValueError, TypeError):
                    pass

        return True

    # ------------------------------------------------------------------
    # Full cycle: detect → hypothesize → start
    # ------------------------------------------------------------------

    def run_full_cycle(self) -> Optional[str]:
        """Main entry: detect patterns → hypothesize → start experiment.

        Returns experiment ID if started, None otherwise.
        """
        # Check analysis cooldown
        last_analysis = self.state.get("last_analysis")
        if last_analysis:
            try:
                days_since = (_utcnow() - datetime.fromisoformat(last_analysis)).days
                if days_since < _ANALYSIS_COOLDOWN_DAYS:
                    return None
            except (ValueError, TypeError):
                pass

        if not self.can_start_new():
            return None

        # Step 1: Detect patterns
        detector = PatternDetector(self.data_dir)
        patterns = detector.analyze(lookback_days=30)
        self.state["last_analysis"] = _utcnow().isoformat()
        self._save_state()

        if not patterns:
            return None

        # Step 2: Generate hypothesis for top pattern
        pattern = patterns[0]
        hypothesis = self._generate_hypothesis(pattern)
        if not hypothesis or hypothesis.get("skip"):
            return None

        # Step 3: Execute action
        action_id = self._execute_action(hypothesis)
        if not action_id:
            return None

        # Step 4: Record experiment
        exp_id = f"exp_{len(self.state['experiments']) + len(self.state['completed']):03d}"
        experiment = {
            "id": exp_id,
            "status": "active",
            "hypothesis": hypothesis["hypothesis"],
            "action_type": hypothesis["action_type"],
            "action_name": hypothesis["action_name"],
            "action_id": action_id,
            "metric": hypothesis["metric"],
            "baseline": hypothesis["baseline"],
            "target": hypothesis["target"],
            "group": pattern.get("group", ""),
            "max_tasks": min(hypothesis.get("max_tasks", 5), 10),
            "max_days": _MAX_EXPERIMENT_DAYS,
            "started": _utcnow().isoformat(),
            "expires": (_utcnow() + timedelta(days=_MAX_EXPERIMENT_DAYS)).isoformat(),
            "matching_tasks": [],
            "verdict": None,
        }

        self.state["experiments"].append(experiment)
        self.state["last_experiment_started"] = _utcnow().isoformat()
        self._save_state()

        log.info("Started experiment %s: %s", exp_id, hypothesis["hypothesis"][:100])
        # D2: surface experiment start to events.jsonl for the dashboard.
        self._emit({
            "ts": _utcnow().isoformat(),
            "type": "experiment_started",
            "experiment_id": exp_id,
            "hypothesis": hypothesis["hypothesis"][:200],
            "action_type": hypothesis["action_type"],
            "action_name": hypothesis["action_name"],
            "metric": hypothesis["metric"],
            "baseline": hypothesis["baseline"],
            "target": hypothesis["target"],
            "max_days": _MAX_EXPERIMENT_DAYS,
        })
        return exp_id

    # ------------------------------------------------------------------
    # Hypothesis generation (single cheap LLM call)
    # ------------------------------------------------------------------

    def _generate_hypothesis(self, pattern: dict) -> Optional[dict]:
        """Generate a testable hypothesis from a pattern via LLM."""
        # Load sample task summaries
        sample_ids = pattern.get("sample_task_ids", [])
        summaries = []
        for tid in sample_ids[:3]:
            path = self.data_dir / "task_results" / f"{tid}.json"
            data = _load_json(path)
            if data:
                summaries.append(
                    f"- Task {tid}: rounds={data.get('total_rounds', '?')}, "
                    f"cost=${data.get('cost_usd', 0):.3f}, "
                    f"status={data.get('status', '?')}, "
                    f"result={str(data.get('result', ''))[:150]}"
                )

        # Load existing skills for context
        existing_skills = "None"
        if self.skill_manager._skills_col is not None:
            try:
                count = self.skill_manager._skills_col.count()
                if count > 0:
                    results = self.skill_manager._skills_col.peek(limit=min(count, 5))
                    existing_skills = "\n".join(
                        f"- {doc[:150]}" for doc in (results.get("documents") or [])
                    )
            except Exception:
                pass

        prompt = HYPOTHESIS_PROMPT.format(
            pattern_json=json.dumps(pattern, indent=2),
            task_summaries="\n".join(summaries) if summaries else "No samples available",
            existing_skills=existing_skills,
        )

        try:
            msg, usage = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                model="google/gemini-2.5-flash-lite",
                reasoning_effort="low",
                max_tokens=600,
            )

            text = msg.get("content", "")
            text = text.replace("```json", "").replace("```", "").strip()
            result = json.loads(text)

            # Validate required fields
            if result.get("skip"):
                log.info("Hypothesis skipped: %s", result.get("reason", ""))
                return result

            required = ["hypothesis", "action_type", "action_content", "action_name", "metric", "baseline", "target"]
            if not all(k in result for k in required):
                log.warning("Hypothesis missing required fields: %s", result.keys())
                return None

            if result["action_type"] not in ("save_skill", "update_skill", "add_knowledge"):
                log.warning("Hypothesis proposed forbidden action: %s", result["action_type"])
                return None

            return result
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            log.debug("Hypothesis parse failed: %s", e)
            return None
        except Exception as e:
            log.warning("Hypothesis LLM call failed: %s", e)
            return None

    # ------------------------------------------------------------------
    # Action execution (green zone only)
    # ------------------------------------------------------------------

    def _execute_action(self, hypothesis: dict) -> Optional[str]:
        """Execute the proposed action. Returns action ID for tracking."""
        action_type = hypothesis["action_type"]
        content = hypothesis["action_content"]
        name = hypothesis["action_name"]

        if action_type == "save_skill":
            if self.skill_manager._skills_col is None:
                log.warning("Cannot save skill: ChromaDB unavailable")
                return None
            skill_id = str(uuid.uuid4())
            try:
                self.skill_manager._skills_col.add(
                    ids=[skill_id],
                    documents=[content],
                    metadatas=[{
                        "type": "skill",
                        "name": name,
                        "source": "experiment",
                        "times_used": 0,
                        "times_helped": 0,
                        "score": 0,
                    }],
                )
                return skill_id
            except Exception as e:
                log.warning("Failed to save experiment skill: %s", e)
                return None

        elif action_type == "update_skill":
            existing = self.skill_manager.find_duplicate(name)
            if existing:
                try:
                    self.skill_manager._skills_col.update(
                        ids=[existing["id"]],
                        documents=[content],
                    )
                    return existing["id"]
                except Exception as e:
                    log.warning("Failed to update skill: %s", e)
            return None

        elif action_type == "add_knowledge":
            knowledge_dir = self.data_dir / "memory" / "knowledge"
            knowledge_dir.mkdir(parents=True, exist_ok=True)
            filepath = knowledge_dir / f"{name}.md"
            try:
                filepath.write_text(content, encoding="utf-8")
                return str(filepath)
            except OSError as e:
                log.warning("Failed to write knowledge: %s", e)
                return None

        return None

    # ------------------------------------------------------------------
    # Measurement: record matching tasks + conclude experiments
    # ------------------------------------------------------------------

    def record_task_for_experiments(self, task_result: dict) -> None:
        """Check if completed task matches any active experiment."""
        changed = False
        for exp in list(self.state["experiments"]):
            if exp["status"] != "active":
                continue

            # Check if expired
            try:
                if _utcnow() > datetime.fromisoformat(exp["expires"]):
                    self._conclude_experiment(exp, reason="expired")
                    changed = True
                    continue
            except (ValueError, TypeError):
                pass

            if self._task_matches_experiment(task_result, exp):
                exp["matching_tasks"].append({
                    "task_id": task_result.get("task_id", ""),
                    "rounds": task_result.get("rounds", 0),
                    "cost": task_result.get("cost", 0),
                    "success": task_result.get("success", False),
                    "date": _utcnow().isoformat(),
                })
                changed = True

                if len(exp["matching_tasks"]) >= exp.get("max_tasks", 5):
                    self._conclude_experiment(exp, reason="enough_data")

        if changed:
            self._save_state()

    def _task_matches_experiment(self, task_result: dict, exp: dict) -> bool:
        """Check if a task matches an experiment's target group."""
        group = exp.get("group", "")
        action_name = exp.get("action_name", "")

        task_text = (
            task_result.get("task", "")
            or task_result.get("result", "")
        ).lower()

        # Match by group action keyword
        if ":" in group:
            _, action_keyword = group.rsplit(":", 1)
            if action_keyword != "other" and action_keyword in task_text:
                return True

        # Match by action_name keywords
        name_words = set(action_name.replace("-", " ").split())
        if name_words and len(name_words & set(task_text.split())) >= max(1, len(name_words) // 2):
            return True

        return False

    def _conclude_experiment(self, exp: dict, reason: str) -> None:
        """Evaluate experiment results and issue verdict."""
        tasks = exp["matching_tasks"]

        if not tasks or len(tasks) < _MIN_TASKS_FOR_CONCLUSION and reason == "expired":
            exp["status"] = "inconclusive"
            exp["verdict"] = f"Insufficient data: {len(tasks)} matching tasks (need {_MIN_TASKS_FOR_CONCLUSION})"
            exp["concluded"] = _utcnow().isoformat()
            exp["conclusion_reason"] = reason
            self._move_to_completed(exp)
            self._emit({
                "ts": _utcnow().isoformat(),
                "type": "experiment_concluded",
                "experiment_id": exp["id"],
                "status": "inconclusive",
                "verdict": exp["verdict"],
                "conclusion_reason": reason,
                "matching_tasks": len(tasks),
            })
            return

        metric = exp["metric"]
        if metric == "avg_rounds":
            result = mean([t["rounds"] for t in tasks])
        elif metric == "avg_cost":
            result = mean([t["cost"] for t in tasks])
        elif metric == "error_rate":
            result = 1 - mean([1 if t["success"] else 0 for t in tasks])
        else:
            result = mean([t["rounds"] for t in tasks])

        baseline = exp["baseline"]
        target = exp["target"]
        improvement = (baseline - result) / baseline if baseline > 0 else 0

        if result <= target:
            exp["status"] = "confirmed"
            exp["verdict"] = f"Target met: {result:.1f} (target: {target}, baseline: {baseline})"
            self._record_in_wisdom(exp, result, improvement)
        elif result < baseline:
            exp["status"] = "partial"
            exp["verdict"] = f"Improved but missed target: {result:.1f} (target: {target}, baseline: {baseline})"
        else:
            exp["status"] = "failed"
            exp["verdict"] = f"No improvement: {result:.1f} (baseline: {baseline})"
            self._revert_action(exp)

        exp["result_value"] = round(result, 2)
        exp["improvement_pct"] = f"{improvement * 100:.1f}%"
        exp["concluded"] = _utcnow().isoformat()
        exp["conclusion_reason"] = reason

        self._move_to_completed(exp)
        log.info("Experiment %s concluded: %s — %s", exp["id"], exp["status"], exp["verdict"])
        # D2: surface conclusion (status + verdict) to events.jsonl.
        self._emit({
            "ts": _utcnow().isoformat(),
            "type": "experiment_concluded",
            "experiment_id": exp["id"],
            "status": exp["status"],
            "verdict": exp.get("verdict", ""),
            "result_value": exp.get("result_value"),
            "improvement_pct": exp.get("improvement_pct"),
            "conclusion_reason": reason,
            "matching_tasks": len(exp.get("matching_tasks", [])),
        })

    def _move_to_completed(self, exp: dict) -> None:
        """Move experiment from active to completed list."""
        self.state["experiments"] = [
            e for e in self.state["experiments"] if e["id"] != exp["id"]
        ]
        self.state["completed"].append(exp)

    def _revert_action(self, exp: dict) -> None:
        """Undo the experiment's action on failure."""
        action_id = exp.get("action_id")
        if not action_id:
            return

        if exp["action_type"] in ("save_skill", "update_skill"):
            if self.skill_manager._skills_col is not None:
                try:
                    self.skill_manager._skills_col.delete(ids=[action_id])
                    log.info("Reverted experiment skill: %s", action_id)
                except Exception as e:
                    log.debug("Skill revert failed: %s", e)
        elif exp["action_type"] == "add_knowledge":
            try:
                Path(action_id).unlink(missing_ok=True)
                log.info("Reverted experiment knowledge: %s", action_id)
            except Exception as e:
                log.debug("Knowledge revert failed: %s", e)

    def _record_in_wisdom(self, exp: dict, result: float, improvement: float) -> None:
        """Record confirmed experiment in wisdom.md."""
        entry = (
            f"\n## Experiment {exp['id']} — CONFIRMED\n"
            f"Hypothesis: {exp['hypothesis']}\n"
            f"Result: {exp['metric']} improved from {exp['baseline']} to {result:.1f} "
            f"({improvement * 100:.1f}% improvement)\n"
            f"Action: {exp['action_type']} '{exp['action_name']}'\n"
            f"Date: {_utcnow().isoformat()[:10]}\n"
        )
        wisdom_path = self.data_dir / "memory" / "wisdom.md"
        try:
            with open(wisdom_path, "a", encoding="utf-8") as f:
                f.write(entry)
        except OSError as e:
            log.warning("Failed to write to wisdom.md: %s", e)

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_experiment(self, exp_id: str) -> Optional[dict]:
        """Get experiment by ID from active or completed."""
        for exp in self.state["experiments"] + self.state["completed"]:
            if exp["id"] == exp_id:
                return exp
        return None

    def get_recently_concluded(self, hours: int = 24) -> List[dict]:
        """Get experiments concluded within the last N hours."""
        cutoff = _utcnow() - timedelta(hours=hours)
        result = []
        for exp in self.state.get("completed", []):
            concluded = exp.get("concluded")
            if concluded:
                try:
                    if datetime.fromisoformat(concluded) >= cutoff:
                        result.append(exp)
                except (ValueError, TypeError):
                    pass
        return result

    def get_active_experiments(self) -> List[dict]:
        """Get all active experiments."""
        return [e for e in self.state["experiments"] if e["status"] == "active"]
