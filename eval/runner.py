"""Orchestrator: validate → setup → execute → check → judge → record."""
from __future__ import annotations

import datetime
import logging
import pathlib
import time
import uuid
from typing import Any, Dict, List

from eval import budget as budget_mod
from eval import checks as checks_mod
from eval import execute as execute_mod
from eval import isolation as iso
from eval import judge as judge_mod
from eval import record as rec
from eval.scenario import Scenario, load_scenario

log = logging.getLogger(__name__)

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "scenarios" / "_fixtures"

# Cross-cutting checks added to every scenario.
DEFAULT_CHECKS: List[Dict[str, Any]] = [
    {"kind": "event_present", "event_type": "task_received"},
]


def _aggregate_check_verdict(check_results: List[Dict[str, Any]]) -> str:
    if not check_results:
        return "inconclusive"
    if all(c["passed"] for c in check_results):
        return "pass"
    return "fail"


def _scenario_verdict(check_verdict: str, judge_consensus: str | None) -> tuple[str, str]:
    """Combine programmatic check verdict + judge consensus."""
    if judge_consensus is None:
        return check_verdict, "checks_only"
    if check_verdict == "pass" and judge_consensus == "pass":
        return "pass", "all_checks_passed_judge_unanimous"
    if check_verdict == "fail" and judge_consensus == "fail":
        return "fail", "checks_failed_judge_failed"
    if check_verdict == "fail" or judge_consensus == "fail":
        return "fail", f"checks={check_verdict}_judge={judge_consensus}"
    return "inconclusive", f"checks={check_verdict}_judge={judge_consensus}"


def run_scenario(scenario: Scenario, run_id: str, run_dir: pathlib.Path,
                 budget: budget_mod.BudgetGuard,
                 chroma_host: str, chroma_port: int) -> Dict[str, Any]:
    started = time.time()
    log.info("=== scenario %s (mode=%s, version=%d) ===",
             scenario.id, scenario.mode, scenario.version)

    scenario_id = scenario.id
    setup = scenario.setup or {}

    if scenario.mode != "direct":
        return _build_skeleton_result(
            scenario, started, "not_run",
            "telegram_mode_not_implemented_in_phase_b",
        )

    record_spend = _make_spend_recorder(scenario_id, budget)

    snapshot_dir = run_dir / "_drive_snapshot" / scenario_id
    with iso.temp_drive_root(scenario_id, run_id, snapshot_dir=snapshot_dir) as drive_root:
        # Seed drive
        try:
            iso.seed_drive(drive_root, setup.get("drive_seed") or {}, FIXTURES_DIR)
        except Exception as e:
            return _build_skeleton_result(
                scenario, started, "inconclusive",
                f"setup_error: {type(e).__name__}: {e}",
            )

        env_overrides = dict(setup.get("env_overrides") or {})
        env_overrides.setdefault("OUROBOROS_MAX_ROUNDS", "8")

        task = dict(scenario.input)
        task.setdefault("id", uuid.uuid4().hex[:8])
        task.setdefault("type", "task")
        task.setdefault("chat_id", 0)

        try:
            trace = execute_mod.execute_direct(
                scenario_id=scenario_id,
                task=task,
                drive_root=drive_root,
                repo_dir=REPO_ROOT,
                chroma_host=chroma_host,
                chroma_port=chroma_port,
                env_overrides=env_overrides,
                timeout_sec=300.0,
            )
        except Exception as e:
            return _build_skeleton_result(
                scenario, started, "fail",
                f"execute_error: {type(e).__name__}: {e}",
            )

        trace["_drive_root"] = str(drive_root)
        agent_spend = _extract_agent_spend(trace)
        record_spend("agent", "task", 0, 0, agent_spend)
        trace["_scenario_spend_usd"] = budget.scenario_total(scenario_id)

        all_checks = DEFAULT_CHECKS + scenario.programmatic_checks
        check_results = checks_mod.run_checks(all_checks, trace)
        check_verdict = _aggregate_check_verdict(check_results)

        judge_block: Dict[str, Any] | None = None
        if scenario.judge:
            sub_result = trace.get("result") or {}
            tool_calls = (trace.get("captured_logs") or {}).get("tools.jsonl") or []

            def _judge_under_cap() -> bool:
                return budget.judge_under_cap(scenario_id)

            judge_block = judge_mod.run_judges(
                scenario_title=scenario.title,
                covers=scenario.covers,
                task_text=str(task.get("text", "")),
                final_text=sub_result.get("final_text", ""),
                events=sub_result.get("events", []),
                tool_calls=tool_calls,
                criteria=scenario.judge.criteria,
                models=scenario.judge.models,
                runs_per_model=scenario.judge.runs_per_model,
                judge_under_cap=_judge_under_cap,
                record_spend=record_spend,
            )

        consensus = judge_block["consensus"] if judge_block else None
        verdict, reason = _scenario_verdict(check_verdict, consensus)

        ended = time.time()
        result = {
            "scenario_id": scenario_id,
            "title": scenario.title,
            "version": scenario.version,
            "covers": scenario.covers,
            "mode": scenario.mode,
            "started_at": _iso(started),
            "ended_at": _iso(ended),
            "duration_sec": round(ended - started, 2),
            "spend_usd": round(budget.scenario_total(scenario_id), 6),
            "input": task,
            "trace_summary": _trace_summary(trace),
            "programmatic_checks": check_results,
            "programmatic_verdict": check_verdict,
            "judge": judge_block,
            "verdict": verdict,
            "verdict_reason": reason,
        }
        rec.write_scenario_result(run_dir, scenario_id, result)
        return result


def _make_spend_recorder(scenario_id: str, budget: budget_mod.BudgetGuard):
    def record(model: str, purpose: str, pt: int, ct: int, usd: float) -> None:
        budget.record(budget_mod.SpendEntry(
            scenario_id=scenario_id,
            model=model,
            purpose=purpose,
            prompt_tokens=pt,
            completion_tokens=ct,
            spend_usd=usd,
        ))
    return record


def _extract_agent_spend(trace: Dict[str, Any]) -> float:
    sub = trace.get("result") or {}
    usage = sub.get("usage") or {}
    return float(usage.get("cost_usd") or usage.get("spend_usd") or 0.0)


def _iso(t: float) -> str:
    return datetime.datetime.fromtimestamp(t, tz=datetime.timezone.utc).isoformat()


def _trace_summary(trace: Dict[str, Any]) -> Dict[str, Any]:
    captured = trace.get("captured_logs") or {}
    sub = trace.get("result") or {}
    rounds = sum(1 for e in (captured.get("events.jsonl") or []) if e.get("type") == "llm_round")
    return {
        "subprocess_status": trace.get("subprocess_status"),
        "subprocess_returncode": trace.get("subprocess_returncode"),
        "events_count": len(captured.get("events.jsonl") or []),
        "supervisor_events_count": len(captured.get("supervisor.jsonl") or []),
        "tools_calls_count": len(captured.get("tools.jsonl") or []),
        "task_results_count": len(captured.get("task_results") or []),
        "llm_rounds": rounds,
        "final_text": (sub.get("final_text") or "")[:500],
        "agent_error": sub.get("error"),
        "stderr_tail": (trace.get("stderr") or "")[-500:],
    }


def _build_skeleton_result(scenario: Scenario, started: float,
                           verdict: str, reason: str) -> Dict[str, Any]:
    ended = time.time()
    return {
        "scenario_id": scenario.id,
        "title": scenario.title,
        "version": scenario.version,
        "covers": scenario.covers,
        "mode": scenario.mode,
        "started_at": _iso(started),
        "ended_at": _iso(ended),
        "duration_sec": round(ended - started, 2),
        "spend_usd": 0.0,
        "input": scenario.input,
        "trace_summary": None,
        "programmatic_checks": [],
        "programmatic_verdict": "inconclusive",
        "judge": None,
        "verdict": verdict,
        "verdict_reason": reason,
    }


def run_eval(scenario_ids: List[str]) -> Dict[str, Any]:
    """Top-level orchestrator. Returns summary dict."""
    run_id = "ev_" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = rec.make_run_dir(REPO_ROOT)
    budget = budget_mod.from_env()

    scenarios: List[Scenario] = [load_scenario(sid) for sid in scenario_ids]

    started = time.time()
    results: List[Dict[str, Any]] = []
    framework_error: str | None = None

    with iso.chromadb_container(run_id=run_id[-12:]) as cdb:
        for scenario in scenarios:
            try:
                r = run_scenario(scenario, run_id, run_dir, budget,
                                 chroma_host=cdb["host"], chroma_port=cdb["port"])
                results.append(r)
            except budget_mod.BudgetExceeded as e:
                log.error("run cap hit: %s", e)
                framework_error = f"run_budget_exceeded: {e}"
                # Mark remaining as not_run
                remaining = [s for s in scenarios if s.id not in {x["scenario_id"] for x in results}]
                for s in remaining:
                    nr = _build_skeleton_result(s, time.time(), "not_run",
                                                 "run_budget_exceeded")
                    rec.write_scenario_result(run_dir, s.id, nr)
                    results.append(nr)
                break

    ended = time.time()

    # Framework-error escalation: >50% inconclusive due to judge_error
    judge_errored = sum(
        1 for r in results
        if r.get("judge") and any(c.get("error") for c in r["judge"]["judge_calls"])
    )
    if results and judge_errored / max(len(results), 1) > 0.5:
        framework_error = framework_error or f"judge_error_in_majority: {judge_errored}/{len(results)}"

    counts = {"pass": 0, "fail": 0, "inconclusive": 0, "not_run": 0}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1

    summary = {
        "run_id": run_id,
        "git_sha": rec.git_sha_short(REPO_ROOT),
        "git_sha_full": rec.git_sha_full(REPO_ROOT),
        "git_branch": rec.git_branch(REPO_ROOT),
        "git_dirty": rec.git_dirty(REPO_ROOT),
        "started_at": _iso(started),
        "ended_at": _iso(ended),
        "duration_sec": round(ended - started, 2),
        "total_spend_usd": round(budget.total(), 6),
        "budget_caps": {
            "run": budget.run_cap_usd,
            "scenario": budget.scenario_cap_usd,
            "judge": budget.judge_cap_usd,
        },
        "scenarios_total": len(results),
        "scenarios_passed": counts["pass"],
        "scenarios_failed": counts["fail"],
        "scenarios_inconclusive": counts["inconclusive"],
        "scenarios_not_run": counts["not_run"],
        "framework_error": framework_error,
        "results": [
            {"id": r["scenario_id"], "verdict": r["verdict"],
             "spend_usd": r["spend_usd"], "reason": r["verdict_reason"]}
            for r in results
        ],
        "framework_version": "0.1.0-phase-b",
    }
    rec.write_summary(run_dir, summary)
    summary["_run_dir"] = str(run_dir)
    return summary
