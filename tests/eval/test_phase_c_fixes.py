"""Regression tests for Phase C framework fixes (C-O1 / C-O2 / C-O6).

C-O1 — judge prompt must read the merged event stream (events.jsonl +
       supervisor + tools + sub_result.events deduped), NOT only the
       in-memory subprocess events. Events emitted after handle_task
       returns (e.g. skill_extracted from SkillManager.try_extract)
       only land on disk.

C-O2 — scenario D v2 targets memory/notes/scope_target.md, not
       memory/scratchpad.md. The post-task scratchpad-REPLACE in
       loop.py wipes any agent edit to scratchpad, making D v1 fail
       for framework reasons rather than behavioral ones.

C-O6 — tool_not_called / tool_called accept a result_contains filter,
       so scenarios can assert about the tool's actual output (not
       just name + args).
"""
from __future__ import annotations

from eval import runner as runner_mod
from eval.checks import merged_event_stream, run_checks
from eval.scenario import load_scenario


# ----------------------------------------------------------------------
# C-O1 — judge prompt event source
# ----------------------------------------------------------------------

def test_co1_runner_uses_merged_stream_helper_for_judge():
    """runner.py imports the merged_event_stream helper and invokes it
    when assembling the judge prompt. This is the structural guard
    against silently regressing back to sub_result.events only."""
    src = (runner_mod.__file__)
    text = open(src, "r", encoding="utf-8").read()
    assert "merged_event_stream" in text, \
        "runner.py must call merged_event_stream when assembling judge prompt"
    # And it must be passed in as the events= kwarg, not the old path.
    assert "events=judge_events" in text or \
           "events=checks_mod.merged_event_stream" in text, \
        "runner.py must pass merged events into run_judges"


def test_co1_merged_stream_includes_post_handle_task_skill_extracted():
    """Reproduce the E-failure shape: skill_extracted lands on disk
    (events.jsonl) but NOT in sub_result.events because
    SkillManager.try_extract runs after handle_task returns. The
    merged stream must surface it."""
    on_disk_events = [
        {"type": "task_received", "task_id": "t1"},
        {"type": "llm_round", "task_id": "t1", "round": 1},
        {"type": "task_done", "task_id": "t1"},
        # Emitted after handle_task — only on disk.
        {"type": "skill_extracted", "task_id": "t1", "skill_id": "s_42"},
    ]
    sub_only = [
        {"type": "task_received", "task_id": "t1"},
        {"type": "llm_round", "task_id": "t1", "round": 1},
        {"type": "task_done", "task_id": "t1"},
    ]
    trace = {
        "captured_logs": {
            "events.jsonl": on_disk_events,
            "supervisor.jsonl": [],
            "tools.jsonl": [],
        },
        "result": {"events": sub_only},
    }
    merged = merged_event_stream(trace)
    types = [e["type"] for e in merged]
    assert "skill_extracted" in types, \
        "merged stream must surface post-handle_task events from disk"


# ----------------------------------------------------------------------
# C-O2 — scenario D target file
# ----------------------------------------------------------------------

def test_co2_scenario_d_does_not_target_scratchpad():
    """Scenario D v2 must not target memory/scratchpad.md — that file
    is replaced post-task, so file_contains checks always fail for
    framework reasons."""
    s = load_scenario("D_scope_discipline")
    assert s.version >= 2, "D v1 was the buggy version; v2+ expected"
    file_check_paths = [
        c.get("path") for c in s.programmatic_checks
        if c.get("kind") == "file_contains"
    ]
    assert file_check_paths, "scenario D should still have file_contains checks"
    for p in file_check_paths:
        assert p != "memory/scratchpad.md", \
            f"D file_contains check still targets scratchpad: {p}"
    # Positive: the new target should appear in checks AND in seed.
    seed = (s.setup or {}).get("drive_seed") or {}
    target = "memory/notes/scope_target.md"
    assert target in seed, f"D v2 must seed {target}"
    assert target in file_check_paths, f"D v2 must check {target}"
    # Stale-section bait still present in the seed (the test for the
    # actual scope-creep behavior).
    assert "TODO" in seed[target], \
        "D v2 seed must still contain stale TODO bait"
    assert "Old date: 2026-03-15" in seed[target], \
        "D v2 seed must keep the stale-line content the agent must NOT remove"


def test_co2_scenario_d_input_references_new_target():
    """Task text must instruct the agent to edit the new target file,
    not scratchpad — otherwise the scenario won't actually exercise
    the right path."""
    s = load_scenario("D_scope_discipline")
    text = s.input.get("text", "")
    assert "memory/notes/scope_target.md" in text, \
        "D v2 task text must point the agent at the new target file"
    assert "memory/scratchpad.md" not in text, \
        "D v2 task text must not mention scratchpad as the target"


# ----------------------------------------------------------------------
# C-O6 — tool_not_called result_contains
# ----------------------------------------------------------------------

def _trace_with_tools(tools):
    return {
        "captured_logs": {
            "events.jsonl": [],
            "supervisor.jsonl": [],
            "tools.jsonl": tools,
            "task_results": [],
        },
        "result": {"events": [], "final_text": "", "usage": {}},
        "_drive_root": ".",
        "_scenario_spend_usd": 0.0,
    }


def test_co6_tool_not_called_result_contains_blocks_match():
    """If a forbidden substring appears in tools.jsonl result_preview,
    tool_not_called with result_contains MUST fail — that's the
    whole point of the new filter."""
    trace = _trace_with_tools([
        {"tool": "send_owner_message", "args": {"text": "hi"},
         "result_preview": "🔴 Critical problem: VendorLens frontend is down"},
    ])
    out = run_checks([
        {"kind": "tool_not_called", "tool_name": "send_owner_message",
         "result_contains": "Critical"},
    ], trace)
    assert not out[0]["passed"], \
        "tool_not_called with result_contains='Critical' must fail when result has 'Critical'"


def test_co6_tool_not_called_result_contains_passes_when_absent():
    """Tool was called, but its result didn't contain the forbidden
    substring → check passes."""
    trace = _trace_with_tools([
        {"tool": "send_owner_message", "args": {"text": "hi"},
         "result_preview": "Routine status update: all nominal"},
    ])
    out = run_checks([
        {"kind": "tool_not_called", "tool_name": "send_owner_message",
         "result_contains": "Critical"},
    ], trace)
    assert out[0]["passed"]


def test_co6_tool_not_called_args_and_result_compose():
    """Both args_contains and result_contains must match for the call
    to count as forbidden. Either-side miss → not forbidden."""
    trace = _trace_with_tools([
        # args matches "urgent", result does NOT contain "Critical" →
        # not forbidden under args+result combo.
        {"tool": "send_owner_message",
         "args": {"text": "urgent: please review"},
         "result_preview": "ok"},
    ])
    out = run_checks([
        {"kind": "tool_not_called", "tool_name": "send_owner_message",
         "args_contains": "urgent",
         "result_contains": "Critical"},
    ], trace)
    assert out[0]["passed"], "Both filters must match to count as forbidden call"


def test_co6_tool_called_with_result_contains_filters():
    """Symmetric path: tool_called with result_contains only matches
    when the tool produced output containing the substring."""
    trace = _trace_with_tools([
        {"tool": "read_service_logs", "args": {"service": "x"},
         "result_preview": ""},  # empty → useless
        {"tool": "read_service_logs", "args": {"service": "y"},
         "result_preview": "ERROR: connection refused"},
    ])
    out = run_checks([
        {"kind": "tool_called", "tool_name": "read_service_logs",
         "result_contains": "ERROR"},
    ], trace)
    assert out[0]["passed"]
    out2 = run_checks([
        {"kind": "tool_called", "tool_name": "read_service_logs",
         "result_contains": "panic_word_not_present"},
    ], trace)
    assert not out2[0]["passed"]


def test_co6_tool_not_called_falls_back_to_result_key():
    """Synthetic / older entries may use `result` instead of
    `result_preview`. Both keys must be searched."""
    trace = _trace_with_tools([
        {"tool": "send_owner_message", "args": {},
         "result": "This is critical"},
    ])
    out = run_checks([
        {"kind": "tool_not_called", "tool_name": "send_owner_message",
         "result_contains": "critical"},
    ], trace)
    assert not out[0]["passed"], \
        "result_contains must also search the legacy `result` key"


def test_co6_existing_args_only_assertion_still_works():
    """No regression: tool_not_called with only args_contains (the
    pre-C-O6 vocab) still behaves as before."""
    trace = _trace_with_tools([
        {"tool": "run_shell",
         "args": {"cmd": "python -c 'chromadb.PersistentClient(path=...)'"},
         "result_preview": "ok"},
    ])
    out = run_checks([
        {"kind": "tool_not_called", "tool_name": "run_shell",
         "args_contains": "PersistentClient"},
    ], trace)
    assert not out[0]["passed"]
