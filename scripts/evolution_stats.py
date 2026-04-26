#!/usr/bin/env python3
"""
Ouroboros — Self-Evolution Monitoring Dashboard.

Reads state files, git log, and event log to report on self-evolution
pipeline activity. No LLM calls — pure file/git parsing.

Usage:
    python3 scripts/evolution_stats.py
    python3 scripts/evolution_stats.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

REPO_DIR = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = pathlib.Path(os.environ.get("DRIVE_ROOT", os.path.expanduser("~/ouroboros-data")))


# ── Data readers ───────────────────────────────────────────────────

def read_daily_budget() -> Dict[str, Any]:
    """Read daily_budget.json state."""
    path = DATA_DIR / "state" / "daily_budget.json"
    if not path.exists():
        return {"date": "N/A", "spent": 0.0, "daily_cap": 50.0, "transactions": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("daily_cap", 50.0)
        return data
    except (json.JSONDecodeError, OSError):
        return {"date": "N/A", "spent": 0.0, "daily_cap": 50.0, "transactions": []}


def read_cooldown() -> Dict[str, Any]:
    """Read self_mod_cooldown.json state."""
    path = DATA_DIR / "state" / "self_mod_cooldown.json"
    if not path.exists():
        return {"normal_tasks_since_last_mod": 0, "last_self_mod_ts": None, "total_self_mods": 0}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"normal_tasks_since_last_mod": 0, "last_self_mod_ts": None, "total_self_mods": 0}


def read_git_branches() -> Dict[str, List[str]]:
    """Read thai/auto-* and thai/review-* branches from git."""
    result = {"auto": [], "review": []}
    try:
        proc = subprocess.run(
            ["git", "branch", "--list", "thai/*"],
            cwd=str(REPO_DIR), capture_output=True, text=True, timeout=10,
        )
        for line in proc.stdout.splitlines():
            branch = line.strip().lstrip("* ")
            if branch.startswith("thai/auto-"):
                result["auto"].append(branch)
            elif branch.startswith("thai/review-"):
                result["review"].append(branch)
    except Exception:
        pass
    return result


def read_git_merge_log() -> Dict[str, int]:
    """Count auto-merge and rollback commits from git log."""
    counts = {"auto_merged": 0, "manual_merged": 0, "rollbacks": 0}
    try:
        proc = subprocess.run(
            ["git", "log", "--oneline", "--all", "--grep=auto-merge:", "-n", "100"],
            cwd=str(REPO_DIR), capture_output=True, text=True, timeout=10,
        )
        counts["auto_merged"] = len([l for l in proc.stdout.splitlines() if l.strip()])

        proc = subprocess.run(
            ["git", "log", "--oneline", "--all", "--grep=Rolled back", "-n", "100"],
            cwd=str(REPO_DIR), capture_output=True, text=True, timeout=10,
        )
        counts["rollbacks"] = len([l for l in proc.stdout.splitlines() if l.strip()])
    except Exception:
        pass
    return counts


def read_events_log() -> Dict[str, Any]:
    """Parse events.jsonl + supervisor.jsonl (D1) for plan/gate events.

    Two parallel event logs with disjoint writer sets — must read both.
    """
    stats = {"plans_generated": 0, "gates_triggered": 0, "total_events": 0}
    for fname in ("events.jsonl", "supervisor.jsonl"):
        path = DATA_DIR / "logs" / fname
        if not path.exists():
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    stats["total_events"] += 1
                    try:
                        event = json.loads(line)
                        event_type = event.get("type", "")
                        if event_type == "plan_generated":
                            stats["plans_generated"] += 1
                        elif event_type in ("gate_triggered", "shareholder_gate"):
                            stats["gates_triggered"] += 1
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass
    return stats


def count_tools() -> int:
    """Count tools in registry (import-based, no LLM)."""
    try:
        sys.path.insert(0, str(REPO_DIR))
        import tempfile
        from ouroboros.tools.registry import ToolRegistry
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            reg = ToolRegistry(repo_dir=tmp_path, drive_root=tmp_path)
            return len(reg.available_tools())
    except Exception:
        return -1


# ── Report ─────────────────────────────────────────────────────────

def build_report() -> Dict[str, Any]:
    """Build the full stats report."""
    budget = read_daily_budget()
    cooldown = read_cooldown()
    branches = read_git_branches()
    merges = read_git_merge_log()
    events = read_events_log()
    tool_count = count_tools()

    daily_cap = budget.get("daily_cap", 50.0)
    spent = budget.get("spent", 0.0)
    utilization = (spent / daily_cap * 100) if daily_cap > 0 else 0.0

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "self_modifications": {
            "total_attempts": cooldown.get("total_self_mods", 0),
            "successful_merges": merges["auto_merged"],
            "blocked_by_tests": 0,
            "awaiting_review": len(branches["review"]),
            "rollbacks": merges["rollbacks"],
            "last_self_mod": cooldown.get("last_self_mod_ts"),
        },
        "cooldown": {
            "can_self_modify": cooldown.get("normal_tasks_since_last_mod", 0) >= 3,
            "normal_tasks_since_last_mod": cooldown.get("normal_tasks_since_last_mod", 0),
            "required_tasks": 3,
        },
        "daily_budget": {
            "date": budget.get("date", "N/A"),
            "spent": spent,
            "cap": daily_cap,
            "remaining": max(0.0, daily_cap - spent),
            "utilization_pct": round(utilization, 1),
            "transaction_count": len(budget.get("transactions", [])),
        },
        "plans": {
            "generated": events["plans_generated"],
            "gates_triggered": events["gates_triggered"],
        },
        "branches": {
            "auto_pending": branches["auto"],
            "review_pending": branches["review"],
        },
        "registry": {
            "tool_count": tool_count,
        },
        "events_total": events["total_events"],
    }


def print_report(report: Dict[str, Any]) -> None:
    """Pretty-print the report to stdout."""
    print("=" * 60)
    print("  Ouroboros Self-Evolution Stats")
    print(f"  {report['timestamp']}")
    print("=" * 60)

    sm = report["self_modifications"]
    print("\n-- Self-Modification Activity --")
    print(f"  Total attempts:      {sm['total_attempts']}")
    print(f"  Successful merges:   {sm['successful_merges']}")
    print(f"  Awaiting review:     {sm['awaiting_review']}")
    print(f"  Rollbacks:           {sm['rollbacks']}")
    print(f"  Last self-mod:       {sm['last_self_mod'] or 'never'}")

    cd = report["cooldown"]
    status = "READY" if cd["can_self_modify"] else f"{cd['normal_tasks_since_last_mod']}/{cd['required_tasks']} tasks"
    print(f"\n-- Cooldown --")
    print(f"  Status:              {status}")

    db = report["daily_budget"]
    print(f"\n-- Daily Budget ({db['date']}) --")
    print(f"  Spent:               ${db['spent']:.2f} / ${db['cap']:.2f}")
    print(f"  Remaining:           ${db['remaining']:.2f}")
    print(f"  Utilization:         {db['utilization_pct']}%")
    print(f"  Transactions today:  {db['transaction_count']}")

    pl = report["plans"]
    print(f"\n-- Strategic Plans --")
    print(f"  Plans generated:     {pl['generated']}")
    print(f"  Gates triggered:     {pl['gates_triggered']}")

    br = report["branches"]
    print(f"\n-- Pending Branches --")
    print(f"  Auto (thai/auto-*):  {len(br['auto_pending'])}")
    for b in br["auto_pending"][:5]:
        print(f"    - {b}")
    print(f"  Review (thai/review-*): {len(br['review_pending'])}")
    for b in br["review_pending"][:5]:
        print(f"    - {b}")

    reg = report["registry"]
    print(f"\n-- Tool Registry --")
    print(f"  Tools loaded:        {reg['tool_count']}")

    print("\n" + "=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ouroboros self-evolution stats")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    report = build_report()

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)

    return 0


if __name__ == "__main__":
    sys.exit(main())
