"""Output writer for eval artifacts."""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import subprocess
from typing import Any, Dict


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
RESULTS_ROOT = REPO_ROOT / "eval_results"


def git_sha_short(repo_dir: pathlib.Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo_dir), "rev-parse", "--short", "HEAD"],
        text=True,
    ).strip()


def git_sha_full(repo_dir: pathlib.Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
        text=True,
    ).strip()


def git_branch(repo_dir: pathlib.Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo_dir), "rev-parse", "--abbrev-ref", "HEAD"],
        text=True,
    ).strip()


def git_dirty(repo_dir: pathlib.Path) -> bool:
    out = subprocess.check_output(
        ["git", "-C", str(repo_dir), "status", "--porcelain"],
        text=True,
    )
    return bool(out.strip())


def make_run_dir(repo_dir: pathlib.Path) -> pathlib.Path:
    sha = git_sha_short(repo_dir)
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    run_dir = RESULTS_ROOT / sha / ts
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def write_scenario_result(run_dir: pathlib.Path, scenario_id: str, result: Dict[str, Any]) -> pathlib.Path:
    path = run_dir / f"{scenario_id}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result, default=str, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def write_summary(run_dir: pathlib.Path, summary: Dict[str, Any]) -> pathlib.Path:
    path = run_dir / "summary.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(summary, default=str, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path
