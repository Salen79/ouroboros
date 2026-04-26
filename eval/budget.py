"""Budget tracking + caps for an eval run."""
from __future__ import annotations

import dataclasses
import os
from typing import List


class BudgetExceeded(Exception):
    pass


@dataclasses.dataclass
class SpendEntry:
    scenario_id: str
    model: str
    purpose: str
    prompt_tokens: int
    completion_tokens: int
    spend_usd: float


@dataclasses.dataclass
class BudgetGuard:
    run_cap_usd: float
    scenario_cap_usd: float
    judge_cap_usd: float
    spend_log: List[SpendEntry] = dataclasses.field(default_factory=list)

    def total(self) -> float:
        return sum(e.spend_usd for e in self.spend_log)

    def scenario_total(self, scenario_id: str) -> float:
        return sum(e.spend_usd for e in self.spend_log if e.scenario_id == scenario_id)

    def judge_total(self, scenario_id: str) -> float:
        return sum(
            e.spend_usd
            for e in self.spend_log
            if e.scenario_id == scenario_id and e.purpose == "judge"
        )

    def record(self, entry: SpendEntry) -> None:
        self.spend_log.append(entry)
        if self.total() > self.run_cap_usd:
            raise BudgetExceeded(
                f"run cap ${self.run_cap_usd:.2f} exceeded (now ${self.total():.4f})"
            )

    def scenario_under_cap(self, scenario_id: str, scenario_local_cap: float) -> bool:
        cap = min(scenario_local_cap, self.scenario_cap_usd)
        return self.scenario_total(scenario_id) < cap

    def judge_under_cap(self, scenario_id: str) -> bool:
        return self.judge_total(scenario_id) < self.judge_cap_usd


def from_env() -> BudgetGuard:
    return BudgetGuard(
        run_cap_usd=float(os.environ.get("EVAL_RUN_CAP_USD", "2.00")),
        scenario_cap_usd=float(os.environ.get("EVAL_SCENARIO_CAP_USD", "0.50")),
        judge_cap_usd=float(os.environ.get("EVAL_JUDGE_CAP_USD", "0.10")),
    )
