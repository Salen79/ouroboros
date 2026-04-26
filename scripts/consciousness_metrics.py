#!/usr/bin/env python3
"""Daily consciousness metrics aggregator.

Usage:
    python scripts/consciousness_metrics.py              # Today's snapshot
    python scripts/consciousness_metrics.py --date 2026-04-01  # Specific date
    python scripts/consciousness_metrics.py --backfill 30       # Last 30 days
"""

import json
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
from statistics import mean

DATA_DIR = Path(os.environ.get("OUROBOROS_DATA", Path.home() / "ouroboros-data"))
STATE_DIR = DATA_DIR / "state"
LOGS_DIR = DATA_DIR / "logs"
HISTORY_FILE = STATE_DIR / "consciousness_history.json"


class ConsciousnessMetrics:
    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir
        self.logs_dir = data_dir / "logs"
        self.state_dir = data_dir / "state"
        self.task_results_dir = data_dir / "task_results"
        self.memory_dir = data_dir / "memory"
        self.episodic_dir = data_dir / "memory" / "episodic"

    def compute_daily(self, date: str) -> dict:
        events = self._load_events_for_date(date)
        tasks = self._load_task_results_for_date(date)
        episodes = self._load_episodes_for_date(date)

        meta = self._compute_meta_cognition(date, events, tasks, episodes)
        eff = self._compute_efficiency(date, events, tasks)
        mem = self._compute_memory(date, events, tasks, episodes)
        beh = self._compute_behavior(date, events)
        ic = self._compute_inner_critic(date, events)

        # Efficiency score 0-10
        eff_score = self._efficiency_score(eff)
        # Memory score 0-10
        mem_score = self._memory_score(mem)

        overall = round(
            meta["score"] * 0.30
            + eff_score * 0.25
            + mem_score * 0.20
            + beh["score"] * 0.25,
            2,
        )

        budget = self._get_budget(date, events)

        return {
            "date": date,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "meta_cognition": meta,
            "efficiency": eff,
            "memory": mem,
            "behavior": beh,
            "inner_critic": ic,
            "summary": {
                "overall_consciousness_score": overall,
                "efficiency_score": round(eff_score, 1),
                "memory_score": round(mem_score, 1),
                "budget_remaining": budget["remaining"],
                "budget_total": budget["total"],
                "total_tasks_all_time": self._count_all_tasks(),
                "tasks_today": len(tasks),
            },
        }

    # ── Data loaders ────────────────────────────────────────────────

    # D1: events live in two parallel logs (events.jsonl + supervisor.jsonl),
    # disjoint writer sets. Aggregators must read both to avoid silently missing
    # ~40% of events. Files are merged and sorted by `ts`.
    EVENT_LOG_FILES = ("events.jsonl", "supervisor.jsonl")

    def _load_events_for_date(self, date: str) -> list[dict]:
        events = []
        for fname in self.EVENT_LOG_FILES:
            events_file = self.logs_dir / fname
            if not events_file.exists():
                continue
            with open(events_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                        if ev.get("ts", "").startswith(date):
                            events.append(ev)
                    except json.JSONDecodeError:
                        continue
        events.sort(key=lambda e: e.get("ts", ""))
        return events

    def _load_task_results_for_date(self, date: str) -> list[dict]:
        tasks = []
        if not self.task_results_dir.exists():
            return tasks
        for f in self.task_results_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                ts = data.get("ts", "")
                if ts.startswith(date):
                    tasks.append(data)
            except (json.JSONDecodeError, OSError):
                continue
        return tasks

    def _load_episodes_for_date(self, date: str) -> list[dict]:
        episodes = []
        ep_file = self.episodic_dir / f"{date}.jsonl"
        if not ep_file.exists():
            return episodes
        with open(ep_file, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    episodes.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return episodes

    # ── Meta-Cognition ──────────────────────────────────────────────

    def _compute_meta_cognition(self, date, events, tasks, episodes):
        # Experiments (file may not exist)
        experiments = self._load_experiments()
        exp_started = sum(
            1
            for e in experiments
            if e.get("status") == "active"
            and e.get("started_at", "").startswith(date)
        )
        exp_concluded = sum(
            1 for e in experiments if e.get("concluded_at", "").startswith(date)
        )
        exp_confirmed = sum(
            1
            for e in experiments
            if e.get("status") == "confirmed"
            and e.get("concluded_at", "").startswith(date)
        )

        # Self-evolution commits (strategic_plan_generated or auto_reflection events)
        self_evolution = sum(
            1
            for ev in events
            if ev.get("type") in ("strategic_plan_generated", "auto_reflection")
        )

        # Reflections with action: insights in episodic memory
        reflections = sum(1 for ep in episodes if ep.get("type") == "insight")

        # Skills created today
        skills_created = sum(
            1 for ep in episodes if ep.get("type") == "skill_saved"
        )

        # Patterns detected (consciousness thoughts)
        patterns = sum(
            1 for ev in events if ev.get("type") == "consciousness_thought"
        )

        # Reuse rate: find_skills calls / tasks
        find_skills_calls = sum(
            1
            for ev in events
            if ev.get("type") == "tool_call" and "find_skills" in str(ev)
        )
        # Also count from task_eval tool_calls as proxy
        reuse_rate = (
            min(1.0, find_skills_calls / max(1, len(tasks))) if tasks else 0.0
        )

        score = min(
            10,
            sum(
                [
                    2.0 if exp_started > 0 else 0,
                    2.0 if exp_confirmed > 0 else 0,
                    1.5 if self_evolution > 0 else 0,
                    1.5 if reflections > 0 else 0,
                    1.0 if skills_created > 0 else 0,
                    1.0 if patterns > 0 else 0,
                    1.0 * min(1, reuse_rate),
                ]
            ),
        )

        return {
            "score": round(score, 1),
            "experiments_started": exp_started,
            "experiments_concluded": exp_concluded,
            "experiments_confirmed": exp_confirmed,
            "self_evolution_events": self_evolution,
            "reflections_with_action": reflections,
            "skills_created_today": skills_created,
            "patterns_detected": patterns,
            "reuse_rate": round(reuse_rate, 2),
        }

    def _load_experiments(self):
        exp_file = self.state_dir / "experiments.json"
        if not exp_file.exists():
            return []
        try:
            data = json.loads(exp_file.read_text())
            if isinstance(data, list):
                return data
            return data.get("experiments", [])
        except (json.JSONDecodeError, OSError):
            return []

    # ── Efficiency ──────────────────────────────────────────────────

    def _compute_efficiency(self, date, events, tasks):
        completed = [t for t in tasks if t.get("status") == "completed"]
        n = len(completed)

        avg_rounds = round(mean([t["total_rounds"] for t in completed]), 1) if completed else 0
        avg_cost = round(mean([t["cost_usd"] for t in completed]), 4) if completed else 0

        # Total daily cost from llm_usage events
        total_cost = round(
            sum(ev.get("cost", 0) for ev in events if ev.get("type") == "llm_usage"),
            4,
        )
        consciousness_cost = round(
            sum(
                ev.get("cost", 0)
                for ev in events
                if ev.get("type") == "llm_usage"
                and ev.get("category") == "consciousness"
            ),
            4,
        )

        success_rate = round(n / max(1, len(tasks)), 2) if tasks else 0

        return {
            "tasks_completed": n,
            "avg_rounds": avg_rounds,
            "avg_cost": avg_cost,
            "total_daily_cost": total_cost,
            "consciousness_cost": consciousness_cost,
            "task_success_rate": success_rate,
        }

    def _efficiency_score(self, eff):
        # Normalize: fewer rounds = better, lower cost = better
        # Baseline: 10 rounds = 5/10, 1 round = 10/10, 25 rounds = 0/10
        if eff["tasks_completed"] == 0:
            return 5.0
        rounds_score = max(0, min(10, 10 - (eff["avg_rounds"] - 1) * (10 / 24)))
        success_score = eff["task_success_rate"] * 10
        return round((rounds_score * 0.6 + success_score * 0.4), 1)

    # ── Memory ──────────────────────────────────────────────────────

    def _compute_memory(self, date, events, tasks, episodes):
        # ChromaDB counts
        chroma = self._get_chromadb_counts()

        skills_created = sum(1 for ep in episodes if ep.get("type") == "skill_saved")
        skills_used = sum(
            1
            for ev in events
            if ev.get("type") == "tool_call" and "find_skills" in str(ev)
        )
        knowledge_created = sum(
            1
            for ev in events
            if ev.get("type") == "tool_call" and "knowledge_write" in str(ev)
        )

        # Knowledge files count
        knowledge_dir = self.memory_dir / "knowledge"
        knowledge_files = 0
        index_file = knowledge_dir / "_index.md"
        if index_file.exists():
            knowledge_files = sum(
                1
                for line in index_file.read_text().splitlines()
                if line.strip() and not line.startswith("#")
            )

        reuse_rate = round(skills_used / max(1, len(tasks)), 2) if tasks else 0
        search_rate = reuse_rate  # proxy: same metric

        return {
            "total_skills": chroma.get("thai_skills", 0),
            "skills_created_today": skills_created,
            "skills_used_today": skills_used,
            "skill_reuse_rate": reuse_rate,
            "total_episodes": chroma.get("thai_episodes", 0),
            "total_knowledge_files": knowledge_files,
            "knowledge_created_today": knowledge_created,
            "history_chunks": chroma.get("thai_history", 0),
            "memory_search_rate": search_rate,
        }

    def _memory_score(self, mem):
        score = 0.0
        score += min(3, mem["total_skills"] * 0.75)  # up to 3 for skills
        score += min(2, mem["total_episodes"] * 0.03)  # up to 2 for episodes
        score += min(2, mem["skill_reuse_rate"] * 2)  # up to 2 for reuse
        score += min(1.5, mem["history_chunks"] * 0.003)  # up to 1.5 for history
        score += min(1.5, mem["total_knowledge_files"] * 0.15)  # up to 1.5
        return round(min(10, score), 1)

    def _get_chromadb_counts(self):
        try:
            import chromadb

            client = chromadb.HttpClient("localhost", 8000)
            result = {}
            for col in client.list_collections():
                result[col.name] = col.count()
            return result
        except Exception:
            return {}

    # ── Behavior ────────────────────────────────────────────────────

    def _compute_behavior(self, date, events):
        stuck_events = sum(1 for ev in events if "stuck" in ev.get("type", ""))
        circuit_breakers = sum(
            1
            for ev in events
            if ev.get("type") in ("llm_empty_response", "circuit_breaker")
        )
        dedup_blocked = sum(
            1 for ev in events if ev.get("type") == "message_dedup_blocked"
        )
        proactive_skipped = sum(
            1
            for ev in events
            if ev.get("type") == "consciousness_proactive_skipped"
        )

        # Directive compliance
        directives_file = self.state_dir / "directives.json"
        directive_compliance = True
        if directives_file.exists():
            try:
                directives = json.loads(directives_file.read_text())
                directive_compliance = len(directives) > 0  # has active directives = aware
            except (json.JSONDecodeError, OSError):
                pass

        # Commitments
        commitments_met = 0
        commitments_overdue = 0
        commitments_file = self.state_dir / "commitments.json"
        if commitments_file.exists():
            try:
                raw = commitments_file.read_text().strip()
                if raw:
                    commits = json.loads(raw)
                    if isinstance(commits, list):
                        for c in commits:
                            due = c.get("due", c.get("deadline", ""))
                            if due and due[:10] <= date:
                                if c.get("status") == "completed":
                                    commitments_met += 1
                                else:
                                    commitments_overdue += 1
            except (json.JSONDecodeError, OSError):
                pass

        score = 10.0
        score -= min(3, stuck_events * 1.0)
        score -= min(2, circuit_breakers * 0.5)
        score -= min(2, commitments_overdue * 1.0)
        score += min(1, proactive_skipped * 0.2)
        score += 1.0 if directive_compliance else 0
        score = max(0, min(10, score))

        # Avg pause: time between task_received and first llm_round for same task
        pauses = []
        task_starts = {}
        for ev in events:
            if ev.get("type") == "task_received":
                tid = ev.get("task", {}).get("id", "")
                if tid:
                    task_starts[tid] = ev["ts"]
            elif ev.get("type") == "llm_round" and ev.get("round") == 1:
                tid = ev.get("task_id", "")
                if tid in task_starts:
                    try:
                        t0 = datetime.fromisoformat(task_starts[tid])
                        t1 = datetime.fromisoformat(ev["ts"])
                        pauses.append((t1 - t0).total_seconds())
                    except (ValueError, TypeError):
                        pass

        avg_pause = round(mean(pauses), 1) if pauses else 0

        return {
            "score": round(score, 1),
            "stuck_events": stuck_events,
            "circuit_breaker_triggers": circuit_breakers,
            "directive_compliance": directive_compliance,
            "commitments_met": commitments_met,
            "commitments_overdue": commitments_overdue,
            "message_dedup_blocked": dedup_blocked,
            "proactive_skipped": proactive_skipped,
            "avg_pause_before_action_sec": avg_pause,
        }

    # ── Inner Critic ─────────────────────────────────────────────────

    def _compute_inner_critic(self, date, events):
        """Inner critic metrics: checkpoint quality and course corrections."""
        checkpoints = [e for e in events if e.get("type") == "inner_critic_checkpoint"]
        skipped = [e for e in events if e.get("type") == "inner_critic_skipped"]
        skills_saved = [e for e in events if e.get("type") == "inner_critic_skill_saved"]
        summaries = [e for e in events if e.get("type") == "inner_critic_summary"]

        checkpoints_today = len(checkpoints)
        off_track_alerts = sum(1 for c in checkpoints if not c.get("on_track", True))

        # Course corrections: off-track alerts where the task still succeeded
        # (indicated by a summary with any_off_track=True existing for same task)
        corrected_tasks = set()
        for s in summaries:
            if s.get("any_off_track"):
                corrected_tasks.add(s.get("task_id", ""))
        course_corrections = len(corrected_tasks)

        correction_success_rate = round(
            course_corrections / max(1, off_track_alerts), 2
        ) if off_track_alerts else 0.0

        total_critic_cost = round(
            sum(c.get("cost", 0) for c in checkpoints), 4
        )

        patterns_matched = list({
            c.get("pattern_match", "")
            for c in checkpoints
            if c.get("pattern_match")
        })

        return {
            "checkpoints_today": checkpoints_today,
            "off_track_alerts": off_track_alerts,
            "course_corrections": course_corrections,
            "correction_success_rate": correction_success_rate,
            "total_critic_cost": total_critic_cost,
            "patterns_matched": patterns_matched,
            "skills_created_from_corrections": len(skills_saved),
            "skipped_high_confidence": len(skipped),
        }

    # ── Summary helpers ─────────────────────────────────────────────

    def _get_budget(self, date, events):
        # Get latest budget from startup_verification events
        remaining = 0
        total = 400
        for ev in reversed(events):
            if ev.get("type") == "startup_verification":
                b = ev.get("checks", {}).get("budget", {})
                if b:
                    remaining = b.get("remaining_usd", 0)
                    total = b.get("total_usd", 400)
                    break
        # If no events for this date, scan full events for latest before date
        if remaining == 0:
            events_file = self.logs_dir / "events.jsonl"
            if events_file.exists():
                with open(events_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            ev = json.loads(line)
                            if ev.get("ts", "")[:10] <= date and ev.get("type") == "startup_verification":
                                b = ev.get("checks", {}).get("budget", {})
                                if b:
                                    remaining = b.get("remaining_usd", 0)
                                    total = b.get("total_usd", 400)
                        except json.JSONDecodeError:
                            continue
        return {"remaining": round(remaining, 2), "total": total}

    def _count_all_tasks(self):
        if not self.task_results_dir.exists():
            return 0
        return len(list(self.task_results_dir.glob("*.json")))

    # ── Key events detection ────────────────────────────────────────

    def _detect_key_events(self, date, events, episodes):
        key_events = []
        # Strategic plans
        for ev in events:
            if ev.get("type") == "strategic_plan_generated":
                key_events.append("Strategic plan generated")
        # Auto reflections
        n_reflections = sum(1 for ev in events if ev.get("type") == "auto_reflection")
        if n_reflections:
            key_events.append(f"{n_reflections} auto-reflection(s)")
        # Insights
        insights = [ep for ep in episodes if ep.get("type") == "insight"]
        if insights:
            key_events.append(f"{len(insights)} insight(s): {insights[0].get('title', '')[:60]}")
        # Skills
        skills = [ep for ep in episodes if ep.get("type") == "skill_saved"]
        if skills:
            key_events.append(f"{len(skills)} skill(s) saved")
        # Errors
        errors = sum(1 for ev in events if ev.get("type") == "task_error")
        if errors:
            key_events.append(f"{errors} task error(s)")
        return key_events

    # ── Save ────────────────────────────────────────────────────────

    def save_snapshot(self, snapshot: dict):
        history = {"snapshots": []}
        if HISTORY_FILE.exists():
            try:
                history = json.loads(HISTORY_FILE.read_text())
            except json.JSONDecodeError:
                pass

        # Add key events
        date = snapshot["date"]
        events = self._load_events_for_date(date)
        episodes = self._load_episodes_for_date(date)
        snapshot["key_events"] = self._detect_key_events(date, events, episodes)

        snapshots = [s for s in history["snapshots"] if s["date"] != snapshot["date"]]
        snapshots.append(snapshot)
        snapshots.sort(key=lambda s: s["date"])

        history["snapshots"] = snapshots
        HISTORY_FILE.write_text(json.dumps(history, indent=2, ensure_ascii=False))
        print(f"  Saved snapshot for {snapshot['date']} (overall: {snapshot['summary']['overall_consciousness_score']})")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Consciousness metrics aggregator")
    parser.add_argument("--date", help="Compute for specific date (YYYY-MM-DD)")
    parser.add_argument(
        "--backfill", type=int, help="Backfill last N days"
    )
    args = parser.parse_args()

    metrics = ConsciousnessMetrics()

    if args.backfill:
        today = datetime.now(timezone.utc).date()
        for i in range(args.backfill, 0, -1):
            d = (today - timedelta(days=i)).isoformat()
            print(f"Computing {d}...")
            snapshot = metrics.compute_daily(d)
            metrics.save_snapshot(snapshot)
        # Also compute today
        d = today.isoformat()
        print(f"Computing {d}...")
        snapshot = metrics.compute_daily(d)
        metrics.save_snapshot(snapshot)
    elif args.date:
        snapshot = metrics.compute_daily(args.date)
        metrics.save_snapshot(snapshot)
    else:
        today = datetime.now(timezone.utc).date().isoformat()
        snapshot = metrics.compute_daily(today)
        metrics.save_snapshot(snapshot)

    print("Done.")


if __name__ == "__main__":
    main()
