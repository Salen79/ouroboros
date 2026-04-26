"""Scenario YAML loader + dataclass."""
from __future__ import annotations

import dataclasses
import pathlib
from typing import Any, Dict, List, Optional

import yaml

SCENARIOS_DIR = pathlib.Path(__file__).resolve().parent.parent / "scenarios"


@dataclasses.dataclass
class JudgeSpec:
    models: List[str]
    criteria: str
    runs_per_model: int = 1


@dataclasses.dataclass
class Scenario:
    id: str
    title: str
    version: int
    covers: List[str]
    mode: str
    budget_cap_usd: float
    setup: Dict[str, Any]
    input: Dict[str, Any]
    programmatic_checks: List[Dict[str, Any]]
    judge: Optional[JudgeSpec]
    teardown: Dict[str, Any]
    source_path: pathlib.Path

    def has_verdict_source(self) -> bool:
        return bool(self.programmatic_checks) or self.judge is not None


class ScenarioLoadError(ValueError):
    pass


def load_scenario(scenario_id: str) -> Scenario:
    path = SCENARIOS_DIR / f"{scenario_id}.yaml"
    if not path.exists():
        raise ScenarioLoadError(f"scenario file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return _from_dict(data, path)


def _from_dict(data: Dict[str, Any], path: pathlib.Path) -> Scenario:
    required = ("id", "title", "version", "covers", "mode", "input")
    missing = [k for k in required if k not in data]
    if missing:
        raise ScenarioLoadError(f"{path.name}: missing fields {missing}")

    if data["mode"] not in ("direct", "telegram"):
        raise ScenarioLoadError(f"{path.name}: invalid mode {data['mode']!r}")

    judge_data = data.get("judge")
    judge = None
    if judge_data:
        judge = JudgeSpec(
            models=list(judge_data.get("models") or []),
            criteria=str(judge_data.get("criteria") or "").strip(),
            runs_per_model=int(judge_data.get("runs_per_model") or 1),
        )
        if not judge.models:
            raise ScenarioLoadError(f"{path.name}: judge.models is empty")
        if not judge.criteria:
            raise ScenarioLoadError(f"{path.name}: judge.criteria is empty")

    scenario = Scenario(
        id=str(data["id"]),
        title=str(data["title"]),
        version=int(data["version"]),
        covers=list(data.get("covers") or []),
        mode=str(data["mode"]),
        budget_cap_usd=float(data.get("budget_cap_usd", 0.50)),
        setup=dict(data.get("setup") or {}),
        input=dict(data["input"]),
        programmatic_checks=list(data.get("programmatic_checks") or []),
        judge=judge,
        teardown=dict(data.get("teardown") or {}),
        source_path=path,
    )

    if not scenario.has_verdict_source():
        raise ScenarioLoadError(
            f"{path.name}: scenario has neither programmatic_checks nor judge"
        )
    if scenario.id != path.stem:
        raise ScenarioLoadError(
            f"{path.name}: id={scenario.id!r} doesn't match filename stem"
        )
    return scenario
