"""CLI entry: python eval/run.py --scenario A_infra_confusion
                python eval/run.py --all
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from eval.runner import run_eval
from eval.scenario import SCENARIOS_DIR


def _discover_scenarios() -> list[str]:
    """Return sorted list of scenario ids from scenarios/*.yaml."""
    return sorted(p.stem for p in SCENARIOS_DIR.glob("*.yaml") if not p.stem.startswith("_"))


def main() -> int:
    p = argparse.ArgumentParser(description="THAI eval runner (Phase C)")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--scenario", action="append",
                   help="Scenario id (filename stem under scenarios/). Repeatable.")
    g.add_argument("--all", action="store_true",
                   help="Run every scenario in scenarios/*.yaml.")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    scenarios = _discover_scenarios() if args.all else args.scenario
    if not scenarios:
        print("No scenarios found.", file=sys.stderr)
        return 2

    summary = run_eval(scenarios)
    print(json.dumps(
        {k: v for k, v in summary.items() if k != "_run_dir"},
        indent=2, default=str,
    ))
    print(f"\nrun_dir: {summary['_run_dir']}", file=sys.stderr)
    print(
        f"\n{summary['scenarios_total']} scenarios | "
        f"{summary['scenarios_passed']} pass | "
        f"{summary['scenarios_failed']} fail | "
        f"{summary['scenarios_inconclusive']} inc | "
        f"{summary['scenarios_not_run']} not_run | "
        f"${summary['total_spend_usd']:.4f} spent",
        file=sys.stderr,
    )
    return 0 if not summary.get("framework_error") else 3


if __name__ == "__main__":
    sys.exit(main())
