"""
Unit tests for ouroboros.pattern_detector — behavioral pattern detection.

Uses temporary directories with mock task result JSON files.
"""

import json
import pytest
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

from ouroboros.pattern_detector import PatternDetector, _parse_ts, _extract_action_keyword


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task_file(results_dir: Path, task_id: str, **overrides) -> Path:
    """Create a task result JSON file with sensible defaults."""
    data = {
        "task_id": task_id,
        "parent_task_id": None,
        "status": "completed",
        "result": "Task completed successfully.",
        "cost_usd": 0.15,
        "total_rounds": 5,
        "ts": datetime.now(tz=timezone.utc).isoformat(),
    }
    data.update(overrides)
    path = results_dir / f"{task_id}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _seed_tasks(tmpdir: Path, count: int, **overrides) -> list:
    """Seed N task result files with optional overrides."""
    results_dir = tmpdir / "task_results"
    results_dir.mkdir(parents=True, exist_ok=True)
    tasks = []
    for i in range(count):
        tid = f"task_{i:03d}"
        _make_task_file(results_dir, tid, **overrides)
        tasks.append(tid)
    return tasks


# ---------------------------------------------------------------------------
# Tests: _parse_ts
# ---------------------------------------------------------------------------

class TestParseTs:

    def test_iso_format_with_tz(self):
        ts = _parse_ts({"ts": "2026-04-01T10:00:00+00:00"})
        assert ts.year == 2026

    def test_iso_format_with_z(self):
        ts = _parse_ts({"ts": "2026-04-01T10:00:00Z"})
        assert ts.year == 2026

    def test_missing_ts(self):
        ts = _parse_ts({})
        assert ts.year == 2000

    def test_invalid_ts(self):
        ts = _parse_ts({"ts": "not-a-date"})
        assert ts.year == 2000


# ---------------------------------------------------------------------------
# Tests: _extract_action_keyword
# ---------------------------------------------------------------------------

class TestExtractActionKeyword:

    def test_deploy(self):
        assert _extract_action_keyword("Deploying to production") == "deploy"

    def test_check(self):
        assert _extract_action_keyword("Check Caddy status") == "check"

    def test_unknown(self):
        assert _extract_action_keyword("Something random") == "other"


# ---------------------------------------------------------------------------
# Tests: PatternDetector.analyze
# ---------------------------------------------------------------------------

class TestPatternDetectorAnalyze:

    def test_returns_empty_with_few_tasks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            _seed_tasks(tmpdir, 5, result="check something")
            detector = PatternDetector(tmpdir)
            assert detector.analyze() == []

    def test_returns_empty_with_no_results_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            detector = PatternDetector(Path(tmpdir))
            assert detector.analyze() == []

    def test_detects_expensive_repeat_pattern(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            results_dir = tmpdir / "task_results"
            results_dir.mkdir(parents=True)

            # 10+ tasks with 3+ in same group with avg_rounds > 5
            for i in range(12):
                _make_task_file(
                    results_dir, f"task_{i:03d}",
                    result="deploy the application to server",
                    total_rounds=10,
                    cost_usd=0.50,
                )

            detector = PatternDetector(tmpdir)
            patterns = detector.analyze()

            assert len(patterns) >= 1
            assert patterns[0]["type"] == "expensive_repeat"
            assert patterns[0]["avg_rounds"] == 10.0
            assert patterns[0]["count"] == 12

    def test_detects_recurring_error_pattern(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            results_dir = tmpdir / "task_results"
            results_dir.mkdir(parents=True)

            # Mix of successful and failed tasks in same group
            for i in range(12):
                status = "failed" if i % 2 == 0 else "completed"
                _make_task_file(
                    results_dir, f"task_{i:03d}",
                    result="fix the broken service",
                    status=status,
                    total_rounds=3,
                    cost_usd=0.05,
                )

            detector = PatternDetector(tmpdir)
            patterns = detector.analyze()

            error_patterns = [p for p in patterns if p["type"] == "recurring_error"]
            assert len(error_patterns) >= 1
            assert error_patterns[0]["error_rate"] == 0.5

    def test_detects_degrading_performance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            results_dir = tmpdir / "task_results"
            results_dir.mkdir(parents=True)

            now = datetime.now(tz=timezone.utc)

            # Older tasks: low rounds
            for i in range(5):
                _make_task_file(
                    results_dir, f"old_{i:03d}",
                    result="check service health status",
                    total_rounds=3,
                    cost_usd=0.05,
                    ts=(now - timedelta(days=15 + i)).isoformat(),
                )

            # Recent tasks: high rounds (degrading)
            for i in range(5):
                _make_task_file(
                    results_dir, f"new_{i:03d}",
                    result="check the system health",
                    total_rounds=12,
                    cost_usd=0.50,
                    ts=(now - timedelta(days=i)).isoformat(),
                )

            detector = PatternDetector(tmpdir)
            patterns = detector.analyze()

            degrading = [p for p in patterns if p["type"] == "degrading_performance"]
            assert len(degrading) >= 1

    def test_max_3_patterns_returned(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            results_dir = tmpdir / "task_results"
            results_dir.mkdir(parents=True)

            # Create many groups, each qualifying
            for action in ["deploy", "check", "fix", "update", "test"]:
                for i in range(4):
                    _make_task_file(
                        results_dir, f"{action}_{i:03d}",
                        result=f"{action} the service",
                        total_rounds=10,
                        cost_usd=0.50,
                    )

            detector = PatternDetector(tmpdir)
            patterns = detector.analyze()
            assert len(patterns) <= 3

    def test_skips_old_tasks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            results_dir = tmpdir / "task_results"
            results_dir.mkdir(parents=True)

            old_ts = (datetime.now(tz=timezone.utc) - timedelta(days=60)).isoformat()
            for i in range(15):
                _make_task_file(
                    results_dir, f"old_{i:03d}",
                    result="deploy something",
                    total_rounds=10,
                    ts=old_ts,
                )

            detector = PatternDetector(tmpdir)
            patterns = detector.analyze(lookback_days=30)
            assert patterns == []


# ---------------------------------------------------------------------------
# Tests: grouping
# ---------------------------------------------------------------------------

class TestGrouping:

    def test_groups_by_action_keyword(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            results_dir = tmpdir / "task_results"
            results_dir.mkdir(parents=True)

            for i in range(5):
                _make_task_file(results_dir, f"d_{i}", result="deploy app")
            for i in range(5):
                _make_task_file(results_dir, f"c_{i}", result="check status")

            detector = PatternDetector(tmpdir)
            tasks = detector._load_task_results(30)
            groups = detector._group_by_type(tasks)

            assert "task:deploy" in groups
            assert "task:check" in groups


# ---------------------------------------------------------------------------
# Tests: statistics
# ---------------------------------------------------------------------------

class TestComputeStats:

    def test_basic_stats(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            detector = PatternDetector(Path(tmpdir))
            tasks = [
                {"rounds": 5, "cost": 0.10, "success": True, "task_id": "t1", "ts": datetime.now(tz=timezone.utc).isoformat()},
                {"rounds": 10, "cost": 0.20, "success": True, "task_id": "t2", "ts": datetime.now(tz=timezone.utc).isoformat()},
                {"rounds": 15, "cost": 0.30, "success": False, "task_id": "t3", "ts": datetime.now(tz=timezone.utc).isoformat()},
            ]
            stats = detector._compute_stats(tasks)
            assert stats["count"] == 3
            assert stats["avg_rounds"] == 10.0
            assert stats["error_rate"] == 0.33  # 1/3

    def test_common_errors_extraction(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            detector = PatternDetector(Path(tmpdir))
            tasks = [
                {"success": False, "result": "permission denied", "task_id": "t1", "ts": ""},
                {"success": False, "result": "permission denied", "task_id": "t2", "ts": ""},
                {"success": True, "result": "ok", "task_id": "t3", "ts": ""},
            ]
            errors = detector._extract_common_errors(tasks)
            assert "permission denied" in errors
