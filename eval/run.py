"""CLI entry: python eval/run.py --scenario A_infra_confusion"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from eval.runner import run_eval


def main() -> int:
    p = argparse.ArgumentParser(description="THAI eval runner (Phase B)")
    p.add_argument("--scenario", action="append", required=True,
                   help="Scenario id (filename stem under scenarios/). Repeatable.")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    summary = run_eval(args.scenario)
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
