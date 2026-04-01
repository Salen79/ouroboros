"""
Ouroboros — Daily Autonomous Budget.

Separate from the total OpenRouter budget — this limits how much
the agent can spend autonomously per day on planned tasks.

State persisted to ~/ouroboros-data/state/daily_budget.json.
Resets at midnight UTC.

Session 2 of the Self-Evolution Plan.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
from datetime import datetime, timezone
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

_DEFAULT_DAILY_CAP = 50.00


class DailyBudget:
    """Track and enforce daily autonomous spending cap."""

    def __init__(self, drive_root: Optional[pathlib.Path] = None):
        self._drive_root = drive_root or pathlib.Path(
            os.environ.get("DRIVE_ROOT", os.path.expanduser("~/ouroboros-data"))
        )
        self._state_path = self._drive_root / "state" / "daily_budget.json"
        self._daily_cap = float(
            os.environ.get("OUROBOROS_DAILY_AUTO_CAP", str(_DEFAULT_DAILY_CAP))
        )

    # ── Public API ──────────────────────────────────────────────────

    def spend(self, amount: float, task_id: str = "") -> bool:
        """Record spending. Returns False if it would exceed daily cap."""
        state = self._load()
        if state["spent"] + amount > self._daily_cap:
            log.warning(
                "Daily budget exceeded: spent=$%.2f + $%.2f > cap=$%.2f (task=%s)",
                state["spent"], amount, self._daily_cap, task_id,
            )
            return False

        state["spent"] += amount
        state["transactions"].append({
            "amount": amount,
            "task_id": task_id,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        # Keep only last 50 transactions
        state["transactions"] = state["transactions"][-50:]
        self._save(state)
        log.info("Daily budget: spent $%.2f (total today: $%.2f/$%.2f)",
                 amount, state["spent"], self._daily_cap)
        return True

    def remaining(self) -> float:
        """Return remaining daily budget."""
        state = self._load()
        return max(0.0, self._daily_cap - state["spent"])

    def spent_today(self) -> float:
        """Return total spent today."""
        state = self._load()
        return state["spent"]

    def status(self) -> Dict[str, Any]:
        """Return full budget status dict."""
        state = self._load()
        return {
            "daily_cap": self._daily_cap,
            "spent_today": state["spent"],
            "remaining": max(0.0, self._daily_cap - state["spent"]),
            "date": state["date"],
            "transaction_count": len(state["transactions"]),
        }

    # ── State persistence ───────────────────────────────────────────

    def _load(self) -> Dict[str, Any]:
        """Load state, resetting if date has changed (midnight UTC)."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        if self._state_path.exists():
            try:
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
                if data.get("date") == today:
                    return data
                # New day — reset
                log.info("Daily budget reset: new day %s (previous: %s, spent: $%.2f)",
                         today, data.get("date"), data.get("spent", 0))
            except (json.JSONDecodeError, OSError) as e:
                log.warning("Failed to load daily_budget.json: %s", e)

        return {"date": today, "spent": 0.0, "transactions": []}

    def _save(self, state: Dict[str, Any]) -> None:
        """Persist state to disk."""
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(
            json.dumps(state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
