# Consciousness Growth Dashboard — Specification

## Purpose

Daily-updating dashboard that tracks THAI's growth across four dimensions of consciousness: meta-cognition, efficiency, memory, and behavior. Lives on the server as part of the CEO Dashboard infrastructure. Reads directly from THAI's logs and state files — no manual data entry.

This is the Shareholder's window into THAI's evolution as a leader, not just an operator.

---

## Architecture

```
Data Sources (existing)          Aggregator (new)              Frontend (new)
─────────────────────          ──────────────────            ─────────────────
events.jsonl            ─┐
task_results/*.json      ├──→  consciousness_metrics.py  ──→  /consciousness page
experiments.json         │     (daily cron + on-demand)       (Next.js or standalone)
commitments.json         │              │
episodic/*.jsonl         │              ▼
ChromaDB collections     │     ~/ouroboros-data/state/
knowledge/_index.md     ─┘     consciousness_history.json
                               (daily snapshots)
```

### Why a snapshot file?

THAI's logs grow and rotate. Querying 30 days of events.jsonl on every dashboard load is expensive. Instead: a cron job runs `consciousness_metrics.py` once per day, computes all metrics for that day, and appends a snapshot to `consciousness_history.json`. Dashboard reads only this file — fast, lightweight, historical.

---

## Four Dimensions

### 1. Meta-Cognition (target: 2/10 → 7/10)

**What it measures:** Can THAI observe its own patterns, form hypotheses, experiment, and improve autonomously?

| Metric | Source | Calculation |
|--------|--------|-------------|
| `experiments_started` | `state/experiments.json` | Count where status=active, started today |
| `experiments_concluded` | `state/experiments.json` | Count where concluded today |
| `experiments_confirmed` | `state/experiments.json` | Count where status=confirmed |
| `self_evolution_commits` | `events.jsonl` type=`git_commit` + source=evolution | Commits from self-evolution system |
| `reflections_with_action` | `episodic/*.jsonl` | Episodes where type=insight AND a skill/knowledge was created within 1 hour |
| `meta_cognition_score` | Composite | Formula below |

**Composite score (0–10):**
```python
score = min(10, sum([
    2.0 if experiments_started > 0 else 0,           # Hypothesis formation
    2.0 if experiments_confirmed > 0 else 0,          # Confirmed improvement
    1.5 if self_evolution_commits > 0 else 0,          # Code self-improvement
    1.5 if reflections_with_action > 0 else 0,         # Reflection → action loop
    1.0 if skills_created_today > 0 else 0,            # Skill extraction
    1.0 if patterns_detected > 0 else 0,               # Pattern recognition
    1.0 * min(1, reuse_rate),                          # Learning from past
]))
```

Baseline (April 2, 2026): 2/10 (only reflects, never acts on reflections).

### 2. Efficiency

**What it measures:** Is THAI getting better at completing tasks with fewer rounds and less money?

| Metric | Source | Calculation |
|--------|--------|-------------|
| `tasks_completed` | `task_results/*.json` | Count with today's date |
| `avg_rounds` | `task_results/*.json` | Mean rounds for today's tasks |
| `avg_cost` | `task_results/*.json` | Mean cost_usd for today's tasks |
| `total_daily_cost` | `events.jsonl` type=`llm_usage` | Sum of cost_usd for today |
| `consciousness_cost` | `events.jsonl` type=`llm_usage` category=`consciousness` | Sum |
| `task_success_rate` | `task_results/*.json` | success=true / total |
| `rounds_trend` | Last 7 snapshots | Linear regression slope of avg_rounds |
| `cost_trend` | Last 7 snapshots | Linear regression slope of avg_cost |

**Key insight:** Trends matter more than absolute numbers. A flat line at 5 rounds is worse than a line dropping from 8 to 4.

### 3. Memory

**What it measures:** Is THAI's institutional knowledge growing? Does it reuse what it learned?

| Metric | Source | Calculation |
|--------|--------|-------------|
| `total_skills` | ChromaDB `thai_skills` | Collection count |
| `skills_created_today` | `episodic/*.jsonl` type=`skill_saved` | Count with today's date |
| `skills_used_today` | `events.jsonl` type=`tool_call` tool=`find_skills` | Count (proxy: find_skills was called) |
| `skill_reuse_rate` | skills_used / tasks_completed | Ratio |
| `total_episodes` | ChromaDB `thai_episodes` | Collection count |
| `total_knowledge_files` | `knowledge/_index.md` | Line count |
| `knowledge_created_today` | `events.jsonl` type=`tool_call` tool=`knowledge_write` | Count |
| `history_chunks` | ChromaDB `thai_history` | Collection count |
| `memory_search_rate` | memory_search calls / tasks | How often THAI checks memory before acting |

### 4. Behavior

**What it measures:** Is THAI behaving like a conscious leader or a reactive executor?

| Metric | Source | Calculation |
|--------|--------|-------------|
| `stuck_events` | `events.jsonl` type contains `stuck` | Count today |
| `circuit_breaker_triggers` | `events.jsonl` type=`circuit_breaker` or `empty_response` | Count |
| `directive_compliance` | `state/directives.json` + task logs | Active directives respected (no violations detected) |
| `commitments_met` | `state/commitments.json` | Completed on time / total due today |
| `commitments_overdue` | `state/commitments.json` | Overdue count |
| `message_dedup_blocked` | `events.jsonl` type=`message_dedup_blocked` | Duplicate messages caught |
| `proactive_skipped` | `events.jsonl` type=`consciousness_proactive_skipped` | Unnecessary actions prevented |
| `avg_pause_before_action` | `events.jsonl` | Time between task_received and first tool_call (proxy for "space between stimulus and reaction") |
| `announcement_execution_ratio` | commitments planned vs started | < 1.0 means plans without execution |

**Behavioral health score (0–10):**
```python
score = 10.0
score -= min(3, stuck_events * 1.0)                    # Each stuck loop costs points
score -= min(2, circuit_breaker_triggers * 0.5)         # Each breaker costs points
score -= min(2, commitments_overdue * 1.0)              # Overdue = broken promises
score += min(1, proactive_skipped * 0.2)                # Self-restraint is good
score += 1.0 if directive_compliance else 0             # Following shareholder directives
score = max(0, min(10, score))
```

---

## Data Model

### Daily snapshot (`consciousness_history.json`)

```json
{
  "snapshots": [
    {
      "date": "2026-04-02",
      "generated_at": "2026-04-02T23:55:00Z",
      
      "meta_cognition": {
        "score": 2.0,
        "experiments_started": 0,
        "experiments_concluded": 0,
        "experiments_confirmed": 0,
        "self_evolution_commits": 0,
        "reflections_with_action": 0,
        "skills_created_today": 0,
        "patterns_detected": 0,
        "reuse_rate": 0.0
      },
      
      "efficiency": {
        "tasks_completed": 12,
        "avg_rounds": 6.3,
        "avg_cost": 0.42,
        "total_daily_cost": 10.15,
        "consciousness_cost": 0.064,
        "task_success_rate": 0.83,
        "rounds_trend": null,
        "cost_trend": null
      },
      
      "memory": {
        "total_skills": 3,
        "skills_created_today": 0,
        "skills_used_today": 8,
        "skill_reuse_rate": 0.67,
        "total_episodes": 55,
        "total_knowledge_files": 12,
        "knowledge_created_today": 0,
        "history_chunks": 483,
        "memory_search_rate": 1.0
      },
      
      "behavior": {
        "score": 7.0,
        "stuck_events": 0,
        "circuit_breaker_triggers": 1,
        "directive_compliance": true,
        "commitments_met": 2,
        "commitments_overdue": 1,
        "message_dedup_blocked": 3,
        "proactive_skipped": 5,
        "avg_pause_before_action_sec": 2.1,
        "announcement_execution_ratio": 0.6
      },
      
      "summary": {
        "overall_consciousness_score": 4.5,
        "budget_remaining": 68.0,
        "budget_total": 400.0,
        "total_tasks_all_time": 462
      }
    }
  ]
}
```

### Overall consciousness score

```python
overall = (
    meta_cognition.score * 0.30 +    # 30% — this is the growth frontier
    efficiency_score * 0.25 +          # 25% — normalized 0-10 from trends
    memory_score * 0.20 +             # 20% — normalized 0-10 from reuse + growth
    behavior.score * 0.25             # 25% — behavioral health
)
```

Weights reflect priorities: meta-cognition is the hardest and most important dimension — it's the difference between an agent that needs manual fixes and one that fixes itself.

---

## Implementation

### File 1: `scripts/consciousness_metrics.py` (~250 lines)

**Zone:** Green (new script)
**Dependencies:** json, pathlib, datetime, statistics (stdlib only). ChromaDB client for collection counts.

```python
#!/usr/bin/env python3
"""Daily consciousness metrics aggregator.

Usage:
    python scripts/consciousness_metrics.py              # Today's snapshot
    python scripts/consciousness_metrics.py --date 2026-04-01  # Specific date
    python scripts/consciousness_metrics.py --backfill 30       # Last 30 days
"""

import json, sys, os
from pathlib import Path
from datetime import datetime, timedelta, timezone
from statistics import mean
from collections import Counter

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

    def compute_daily(self, date: str) -> dict:
        """Compute all metrics for a given date (YYYY-MM-DD)."""
        events = self._load_events_for_date(date)
        tasks = self._load_task_results_for_date(date)
        experiments = self._load_experiments()
        commitments = self._load_commitments()

        return {
            "date": date,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "meta_cognition": self._compute_meta_cognition(date, events, tasks, experiments),
            "efficiency": self._compute_efficiency(date, events, tasks),
            "memory": self._compute_memory(date, events, tasks),
            "behavior": self._compute_behavior(date, events, commitments),
            "summary": self._compute_summary(date, events, tasks),
        }

    def _load_events_for_date(self, date: str) -> list[dict]:
        """Load events.jsonl entries matching date."""
        events = []
        events_file = self.logs_dir / "events.jsonl"
        if not events_file.exists():
            return events
        with open(events_file, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    ts = ev.get("ts", "")
                    if ts.startswith(date):
                        events.append(ev)
                except json.JSONDecodeError:
                    continue
        return events

    def _load_task_results_for_date(self, date: str) -> list[dict]:
        """Load task result JSON files matching date."""
        tasks = []
        if not self.task_results_dir.exists():
            return tasks
        for f in self.task_results_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                ts = data.get("completed_at", data.get("ts", data.get("started_at", "")))
                if ts.startswith(date):
                    tasks.append(data)
            except (json.JSONDecodeError, OSError):
                continue
        return tasks

    # ... (each _compute_* method implements the formulas above)

    def save_snapshot(self, snapshot: dict):
        """Append snapshot to history file, replacing if date exists."""
        history = {"snapshots": []}
        if HISTORY_FILE.exists():
            try:
                history = json.loads(HISTORY_FILE.read_text())
            except json.JSONDecodeError:
                pass

        # Replace existing date or append
        snapshots = [s for s in history["snapshots"] if s["date"] != snapshot["date"]]
        snapshots.append(snapshot)
        snapshots.sort(key=lambda s: s["date"])

        history["snapshots"] = snapshots
        HISTORY_FILE.write_text(json.dumps(history, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    metrics = ConsciousnessMetrics()
    # Parse args: --date, --backfill
    # Compute and save
```

### File 2: API endpoint

**Option A (minimal — recommended):** Static JSON served by Caddy.

Caddy already runs on the server. Add a route:

```
# In Caddyfile
handle /api/consciousness {
    root * /home/deploy/ouroboros-data/state
    file_server
    header Content-Type application/json
}
```

Dashboard fetches `https://vendorlens.app/api/consciousness/consciousness_history.json` — or via SSH tunnel on localhost.

**Option B:** FastAPI endpoint in the existing VendorLens backend. More work, less benefit for a single JSON file.

### File 3: Frontend page

**Option A (standalone HTML — recommended for speed):**

Single `consciousness-dashboard.html` served by Caddy at `/consciousness`. Uses vanilla JS + Chart.js CDN. No build step. Reads from the JSON API.

**Option B:** New page in CEO Dashboard (Next.js). More integrated but requires rebuilding the frontend.

### Cron job

```bash
# /etc/cron.d/consciousness-metrics
55 23 * * * deploy cd /home/deploy/ouroboros && source /home/deploy/.ouroboros-venv/bin/activate && python scripts/consciousness_metrics.py >> /home/deploy/ouroboros-data/logs/cron.log 2>&1
```

Runs at 23:55 daily. Snapshot captures the full day's activity.

---

## Dashboard Layout

```
┌──────────────────────────────────────────────────────────────────┐
│  THAI Consciousness Growth Dashboard              [Apr 2, 2026] │
│                                                                  │
│  Overall: ████████░░ 4.5/10       Budget: $68/$400 (17% left)   │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─ Meta-Cognition ──────┐  ┌─ Efficiency ──────────────────┐   │
│  │                       │  │                                │   │
│  │  Score: 2.0/10        │  │  Tasks: 12    Avg rounds: 6.3 │   │
│  │  ○ Experiments: 0     │  │  Avg cost: $0.42              │   │
│  │  ○ Self-evolutions: 0 │  │  Success rate: 83%            │   │
│  │  ○ Skills created: 0  │  │                                │   │
│  │  ○ Reuse rate: 0%     │  │  [7-day trend chart ↘ ────]   │   │
│  │                       │  │  rounds ── cost ──             │   │
│  │  [Sparkline: flat]    │  │                                │   │
│  └───────────────────────┘  └────────────────────────────────┘   │
│                                                                  │
│  ┌─ Memory ──────────────┐  ┌─ Behavior ────────────────────┐   │
│  │                       │  │                                │   │
│  │  Skills: 3 (+0)       │  │  Score: 7.0/10                │   │
│  │  Episodes: 55 (+2)    │  │  ○ Stuck loops: 0             │   │
│  │  Knowledge: 12 (+0)   │  │  ○ Circuit breakers: 1        │   │
│  │  History: 483 (+15)   │  │  ○ Commitments met: 2/3       │   │
│  │  Reuse rate: 67%      │  │  ○ Directives: ✓ compliant    │   │
│  │  Search rate: 100%    │  │  ○ Dedup blocked: 3           │   │
│  │                       │  │  ○ Avg pause: 2.1s            │   │
│  │  [Growth chart ↗]     │  │                                │   │
│  └───────────────────────┘  └────────────────────────────────┘   │
│                                                                  │
│  ┌─ 30-Day Timeline ────────────────────────────────────────┐   │
│  │                                                           │   │
│  │  Overall ═══════════════════════════════════════════      │   │
│  │  Meta    ═══════════════════════════════════════════      │   │
│  │  Effic   ═══════════════════════════════════════════      │   │
│  │  Memory  ═══════════════════════════════════════════      │   │
│  │  Behav   ═══════════════════════════════════════════      │   │
│  │  Apr 2    Apr 9    Apr 16    Apr 23    Apr 30    May 2   │   │
│  └───────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─ Key Events ─────────────────────────────────────────────┐   │
│  │  Apr 2: Memory System complete. Behavioral fixes done.    │   │
│  │  Apr 2: Skill Lifecycle merged. Experiment Engine spec.   │   │
│  │  ...future events auto-detected from experiments/commits  │   │
│  └───────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

---

## Backfill Strategy

THAI has ~450 tasks in task_results/ dating back to early March. Run:

```bash
python scripts/consciousness_metrics.py --backfill 30
```

This retroactively computes snapshots for the last 30 days, giving immediate historical context. Some metrics (experiments, skill lifecycle) will be 0 for historical dates since those systems were just installed — that's correct and shows the growth trajectory.

---

## Implementation Order

1. `scripts/consciousness_metrics.py` — aggregator with all 4 dimensions
2. Backfill last 30 days
3. Cron job setup
4. Caddy route for static JSON serving
5. `consciousness-dashboard.html` — standalone frontend
6. Test end-to-end via SSH tunnel

**Estimated effort:** One Claude Code session (~1 hour).

---

## File Zones

| File | Zone | Notes |
|------|------|-------|
| `scripts/consciousness_metrics.py` | Green (new) | Pure Python + ChromaDB read-only |
| `consciousness-dashboard.html` | Green (new) | Static HTML, served by Caddy |
| Caddyfile | Yellow | Add one route block |
| cron.d/consciousness-metrics | Green (new) | System cron |
| `ouroboros-data/state/consciousness_history.json` | Data | Auto-created |

---

## Success Criteria

1. Dashboard loads in <2s via SSH tunnel
2. Historical data visible from backfill
3. Daily auto-update at 23:55
4. All four dimension scores compute correctly
5. 30-day timeline chart shows growth trajectory
6. Key events auto-detected and displayed
