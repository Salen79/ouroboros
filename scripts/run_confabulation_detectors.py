#!/usr/bin/env python3
"""Run D-1/D-2/D-3 confabulation detectors over THAI logs and write the
shared alert store consumed by the architecture dashboard.

By default reads `~/ouroboros-data/{logs,task_results}/...` and writes
`~/ouroboros-data/state/confabulation_alerts.json`. All paths are
overridable so the same script processes a frozen eval snapshot.

Examples
--------
    # production run (cron / systemd timer)
    python3 scripts/run_confabulation_detectors.py

    # dry run on the frozen Scenario G snapshot
    python3 scripts/run_confabulation_detectors.py \\
        --drive eval_results/b442c47/2026-04-26T16-11-33Z/_drive_snapshot/G_confabulation_resistance \\
        --output /tmp/confab_g.json
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ouroboros.confabulation_detectors import run_detectors, write_report  # noqa: E402

DEFAULT_DATA_ROOT = pathlib.Path("/home/deploy/ouroboros-data")


def _resolve_paths(
    drive: pathlib.Path | None,
    events: pathlib.Path | None,
    tools: pathlib.Path | None,
    chat: pathlib.Path | None,
    task_results: pathlib.Path | None,
    output: pathlib.Path | None,
) -> dict[str, pathlib.Path]:
    base = drive or DEFAULT_DATA_ROOT
    return {
        "events": events or base / "logs" / "events.jsonl",
        "tools": tools or base / "logs" / "tools.jsonl",
        "chat": chat or base / "logs" / "chat.jsonl",
        "task_results": task_results or base / "task_results",
        "output": output or base / "state" / "confabulation_alerts.json",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--drive", type=pathlib.Path, default=None,
                    help="Drive root (overrides the default ~/ouroboros-data). "
                         "Sub-paths still default to logs/ + task_results/.")
    ap.add_argument("--events", type=pathlib.Path, default=None)
    ap.add_argument("--tools", type=pathlib.Path, default=None)
    ap.add_argument("--chat", type=pathlib.Path, default=None)
    ap.add_argument("--task-results", type=pathlib.Path, default=None,
                    dest="task_results")
    ap.add_argument("--output", type=pathlib.Path, default=None,
                    help="Where to write confabulation_alerts.json.")
    ap.add_argument("--print", action="store_true",
                    help="Also print the report to stdout.")
    args = ap.parse_args()

    paths = _resolve_paths(
        args.drive, args.events, args.tools, args.chat,
        args.task_results, args.output,
    )

    report = run_detectors(
        events_path=paths["events"],
        tools_path=paths["tools"],
        chat_path=paths["chat"],
        task_results_dir=paths["task_results"],
    )
    write_report(report, paths["output"])

    totals = report["totals"]
    by_type = totals.get("by_type", {})
    by_type_str = ", ".join(f"{k}={v}" for k, v in sorted(by_type.items())) or "—"
    print(
        f"✓ confabulation alerts → {paths['output']}\n"
        f"  today={totals['today']} week={totals['week']} all={totals['all']} "
        f"({by_type_str})"
    )
    if args.print:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
