"""D22 — _post_task_scratchpad_write must fall back to scratchpad itself.

Pre-D22 the post-task write took prev_task_id / prev_task_summary from
upstream state (state.json or task_results glob). When those drifted (e.g.
after the D20 issue, or when the task_results dir was rotated away), the
"Previous:" line vanished.

The fix: when both kwargs are empty, parse the existing scratchpad's
"Last task" / "Result" lines and use those for the new "Previous:" line.
This makes the chain self-consistent on its own data.
"""
from __future__ import annotations

import pathlib

from ouroboros.loop import _post_task_scratchpad_write, _read_prev_from_scratchpad


def _setup(tmp_path: pathlib.Path) -> pathlib.Path:
    drive = tmp_path / "drive"
    (drive / "memory").mkdir(parents=True)
    return drive


def test_fallback_reads_last_task_line(tmp_path):
    drive = _setup(tmp_path)
    sp = drive / "memory" / "scratchpad.md"
    sp.write_text(
        "## Current state (2026-04-26)\n"
        "Last task: deploy caddy — 3R, $0.020 — completed\n"
        "Result: Caddy reloaded successfully on port 443\n"
        "Active directives: none\n",
        encoding="utf-8",
    )

    pid, psum = _read_prev_from_scratchpad(sp)
    assert pid == "deploy caddy"
    assert "Caddy reloaded successfully" in psum


def test_fallback_returns_empty_when_scratchpad_missing(tmp_path):
    drive = _setup(tmp_path)
    sp = drive / "memory" / "scratchpad.md"
    pid, psum = _read_prev_from_scratchpad(sp)
    assert pid == ""
    assert psum == ""


def test_post_task_write_uses_fallback_when_kwargs_empty(tmp_path):
    """End-to-end: write a fresh scratchpad with no prev kwargs.

    The new content's "Previous:" line must come from the OLD scratchpad's
    "Last task" / "Result" lines.
    """
    drive = _setup(tmp_path)
    sp = drive / "memory" / "scratchpad.md"
    sp.write_text(
        "## Current state (2026-04-25)\n"
        "Last task: check disk space — 2R, $0.010 — completed\n"
        "Result: 12GB free on root\n"
        "Active directives: none\n",
        encoding="utf-8",
    )

    _post_task_scratchpad_write(
        drive_root=drive,
        task_text="restart prism bot",
        round_idx=4,
        accumulated_usage={"cost": 0.018},
        final_text="prism-bot restarted",
        hit_max_rounds=False,
        # both empty → fallback engages
        prev_task_id="",
        prev_task_summary="",
    )

    text = sp.read_text(encoding="utf-8")
    assert "Last task: restart prism bot" in text
    # Fallback populated the previous line from what was previously in the file
    assert "Previous: check disk space" in text
    assert "12GB free on root" in text


def test_post_task_write_prefers_explicit_kwargs(tmp_path):
    """When kwargs are supplied, they win — fallback is only a backup."""
    drive = _setup(tmp_path)
    sp = drive / "memory" / "scratchpad.md"
    sp.write_text(
        "## Current state (2026-04-25)\n"
        "Last task: scratchpad-task — 2R, $0.010 — completed\n"
        "Result: scratchpad-result\n"
        "Active directives: none\n",
        encoding="utf-8",
    )

    _post_task_scratchpad_write(
        drive_root=drive,
        task_text="new task",
        round_idx=3,
        accumulated_usage={"cost": 0.012},
        final_text="new result",
        hit_max_rounds=False,
        prev_task_id="kwarg-id",
        prev_task_summary="kwarg-summary",
    )

    text = sp.read_text(encoding="utf-8")
    assert "Previous: kwarg-id — kwarg-summary" in text
    # Scratchpad's old data must NOT bleed through
    assert "scratchpad-task" not in text
    assert "scratchpad-result" not in text


def test_post_task_write_no_previous_line_when_blank_scratchpad(tmp_path):
    """Empty scratchpad + empty kwargs → no Previous: line at all."""
    drive = _setup(tmp_path)
    sp = drive / "memory" / "scratchpad.md"
    sp.write_text(
        "Scratchpad not yet initialised — first task will replace this placeholder.\n",
        encoding="utf-8",
    )

    _post_task_scratchpad_write(
        drive_root=drive,
        task_text="first real task",
        round_idx=2,
        accumulated_usage={"cost": 0.005},
        final_text="ok",
        hit_max_rounds=False,
        prev_task_id="",
        prev_task_summary="",
    )

    text = sp.read_text(encoding="utf-8")
    assert "Last task: first real task" in text
    assert "Previous:" not in text  # no fallback signal in placeholder text
