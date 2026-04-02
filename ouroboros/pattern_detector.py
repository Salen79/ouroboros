"""
Ouroboros — Behavioral pattern detector.

Scans ~/ouroboros-data/task_results/ and events.jsonl, groups tasks,
computes statistics, identifies improvement opportunities.

Pure Python — no LLM calls, no external dependencies beyond stdlib.
Called from experiment_engine.py during background consciousness cycle.
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


def _parse_ts(task: dict) -> datetime:
    """Parse timestamp from task result, with fallback to epoch."""
    ts = task.get("ts", "")
    if not ts:
        return datetime(2000, 1, 1, tzinfo=timezone.utc)
    try:
        # Handle both ISO formats: with/without timezone
        ts = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return datetime(2000, 1, 1, tzinfo=timezone.utc)


def _extract_action_keyword(text: str) -> str:
    """Extract primary action keyword from task result text."""
    text = text.lower()
    for keyword in [
        "deploy", "check", "fix", "create", "update", "analyze",
        "test", "search", "review", "build", "install", "restart",
        "configure", "migrate", "monitor",
    ]:
        if keyword in text:
            return keyword
    return "other"


class PatternDetector:
    """Detects behavioral patterns from task history — pure statistics."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

    def analyze(self, lookback_days: int = 30) -> List[Dict[str, Any]]:
        """Analyze task history and return actionable patterns.

        Returns up to 3 patterns sorted by potential impact.
        """
        tasks = self._load_task_results(lookback_days)
        if len(tasks) < 10:
            return []

        groups = self._group_by_type(tasks)

        patterns = []
        for group_name, group_tasks in groups.items():
            if len(group_tasks) < 3:
                continue

            stats = self._compute_stats(group_tasks)

            # Pattern 1: Expensive repeated tasks
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

        patterns.sort(
            key=lambda p: p.get("total_cost", 0) + p.get("error_rate", 0),
            reverse=True,
        )
        return patterns[:3]

    def _load_task_results(self, lookback_days: int) -> List[Dict[str, Any]]:
        """Load task results from JSON files within lookback window."""
        results_dir = self.data_dir / "task_results"
        if not results_dir.is_dir():
            return []

        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=lookback_days)
        tasks = []

        for path in results_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                ts = _parse_ts(data)
                if ts >= cutoff:
                    # Normalize field names to match spec expectations
                    data.setdefault("rounds", data.get("total_rounds", 0))
                    data.setdefault("cost", data.get("cost_usd", 0))
                    data.setdefault("success", data.get("status") == "completed")
                    data.setdefault("task", data.get("result", "")[:200])
                    data.setdefault("task_id", path.stem)
                    tasks.append(data)
            except (json.JSONDecodeError, OSError) as e:
                log.debug("Skipping %s: %s", path.name, e)

        return tasks

    def _group_by_type(self, tasks: List[Dict[str, Any]]) -> Dict[str, List[Dict]]:
        """Group tasks by action keyword extracted from result text."""
        groups: Dict[str, List[Dict]] = defaultdict(list)
        for task in tasks:
            desc = task.get("task", "") or task.get("result", "")
            action = _extract_action_keyword(desc)
            group_key = f"task:{action}"
            groups[group_key].append(task)
        return dict(groups)

    def _compute_stats(self, tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Compute statistics for a task group."""
        rounds = [t.get("rounds", 0) for t in tasks]
        costs = [t.get("cost", 0) for t in tasks]
        successes = [1 if t.get("success", False) else 0 for t in tasks]

        now = datetime.now(tz=timezone.utc)
        recent = [t for t in tasks if (now - _parse_ts(t)).days <= 7]
        older = [t for t in tasks if (now - _parse_ts(t)).days > 7]

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
            "error_rate": round(1 - mean(successes), 2) if successes else 1.0,
            "common_errors": self._extract_common_errors(tasks),
            "trend": trend,
            "recent_avg": round(recent_avg, 1),
            "older_avg": round(older_avg, 1),
            "sample_ids": [t.get("task_id", "") for t in tasks[:5]],
        }

    def _extract_common_errors(self, tasks: List[Dict[str, Any]]) -> List[str]:
        """Extract common error snippets from failed tasks."""
        errors = []
        for t in tasks:
            if not t.get("success", True):
                result = t.get("result", "")
                if result:
                    # Take first line as error summary
                    first_line = result.strip().split("\n")[0][:100]
                    errors.append(first_line)
        return [err for err, _ in Counter(errors).most_common(3)]
