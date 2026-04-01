"""
Ouroboros — Strategic Planner.

Generates daily plans of 1-3 autonomous tasks when the task queue is empty.
Uses light LLM model (same as consciousness) for plan generation.
Integrates with BIBLE.md P11 shareholder gates.

Session 2 of the Self-Evolution Plan.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ouroboros.llm import LLMClient, DEFAULT_LIGHT_MODEL
from ouroboros.utils import utc_now_iso, read_text, clip_text

log = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────
DAILY_BUDGET_CAP = 50.00
SELF_MOD_COOLDOWN = 3       # normal tasks required between self-modifications
MAX_TASKS_PER_CYCLE = 3

CATEGORIES = ("product", "self_improvement", "infrastructure", "exploration", "maintenance")

# BIBLE.md P11 gates — tasks matching these require shareholder /approve
_P11_GATE_KEYWORDS = (
    "new product", "launch", "budget increase", "constitutional amendment",
    "legal", "financial", "bible", "constitution",
)


@dataclass
class PlannedTask:
    """A single task produced by the strategic planner."""
    title: str
    description: str
    category: str = "maintenance"
    est_cost: float = 1.00
    priority: int = 1          # 1 = highest
    reasoning: str = ""
    requires_gate: bool = False
    gate_reason: str = ""
    approved: bool = False


@dataclass
class StrategicPlan:
    """A plan produced by the strategic planner for one cycle."""
    tasks: List[PlannedTask] = field(default_factory=list)
    generated_at: str = ""
    context_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "context_summary": self.context_summary,
            "tasks": [
                {
                    "title": t.title,
                    "description": t.description,
                    "category": t.category,
                    "est_cost": t.est_cost,
                    "priority": t.priority,
                    "reasoning": t.reasoning,
                    "requires_gate": t.requires_gate,
                    "gate_reason": t.gate_reason,
                    "approved": t.approved,
                }
                for t in self.tasks
            ],
        }


class StrategicPlanner:
    """Generates autonomous task plans using a light LLM model."""

    def __init__(
        self,
        repo_dir: Optional[pathlib.Path] = None,
        drive_root: Optional[pathlib.Path] = None,
    ):
        self._repo_dir = repo_dir or pathlib.Path(
            os.environ.get("OUROBOROS_REPO_DIR", os.path.expanduser("~/ouroboros"))
        )
        self._drive_root = drive_root or pathlib.Path(
            os.environ.get("DRIVE_ROOT", os.path.expanduser("~/ouroboros-data"))
        )
        self._llm = LLMClient()

    @property
    def _model(self) -> str:
        return os.environ.get("OUROBOROS_MODEL_LIGHT", "") or DEFAULT_LIGHT_MODEL

    # ── Plan generation ─────────────────────────────────────────────

    def generate_plan(self, context: Optional[Dict[str, Any]] = None) -> StrategicPlan:
        """Generate a strategic plan of 1-3 tasks.

        Args:
            context: Optional dict with keys like 'state', 'memory_snippets',
                     'health', 'recent_events'. If None, auto-loads from disk.

        Returns:
            StrategicPlan with prioritised tasks.
        """
        ctx = context or self._auto_context()
        prompt = self._build_prompt(ctx)

        try:
            msg, usage = self._llm.chat(
                messages=[
                    {"role": "system", "content": "You are THAI's strategic planning module. "
                     "Produce a JSON plan of 1-3 tasks."},
                    {"role": "user", "content": prompt},
                ],
                model=self._model,
                reasoning_effort="low",
                max_tokens=1024,
            )
            cost = float(usage.get("cost") or 0)
            log.info("Strategic plan generated (cost=$%.4f)", cost)

            content = msg.get("content", "")
            return self._parse_plan(content, ctx)

        except Exception as e:
            log.error("Strategic plan generation failed: %s", e)
            return StrategicPlan(
                generated_at=utc_now_iso(),
                context_summary="Plan generation failed: " + str(e),
            )

    def _auto_context(self) -> Dict[str, Any]:
        """Load context from disk for plan generation."""
        ctx: Dict[str, Any] = {}

        # State
        state_path = self._drive_root / "state" / "state.json"
        if state_path.exists():
            try:
                ctx["state"] = json.loads(read_text(state_path))
            except Exception:
                ctx["state"] = {}

        # Scratchpad
        sp_path = self._drive_root / "memory" / "scratchpad.md"
        if sp_path.exists():
            ctx["scratchpad"] = clip_text(read_text(sp_path), 3000)

        # Identity
        id_path = self._drive_root / "memory" / "identity.md"
        if id_path.exists():
            ctx["identity"] = clip_text(read_text(id_path), 2000)

        # Health check
        try:
            from ouroboros.self_evolution import SelfEvolution
            evo = SelfEvolution(repo_dir=self._repo_dir)
            ctx["health"] = evo.health_check()
        except Exception:
            ctx["health"] = {}

        # Daily budget remaining
        try:
            from ouroboros.budget import DailyBudget
            budget = DailyBudget()
            ctx["daily_budget_remaining"] = budget.remaining()
        except Exception:
            ctx["daily_budget_remaining"] = DAILY_BUDGET_CAP

        # Self-mod cooldown
        try:
            from ouroboros.self_evolution import SelfModCooldown
            cooldown = SelfModCooldown()
            ctx["can_self_modify"] = cooldown.can_self_modify()
        except Exception:
            ctx["can_self_modify"] = True

        return ctx

    def _build_prompt(self, ctx: Dict[str, Any]) -> str:
        """Build the LLM prompt for plan generation."""
        parts = []

        # BIBLE principles (abbreviated)
        bible_path = self._repo_dir / "BIBLE.md"
        if bible_path.exists():
            parts.append("## BIBLE.md (abbreviated)\n" + clip_text(read_text(bible_path), 4000))

        parts.append(f"## Current state\n```json\n{json.dumps(ctx, indent=2, default=str)[:3000]}\n```")

        parts.append(f"""## Instructions

Generate a plan of 1-{MAX_TASKS_PER_CYCLE} tasks for the current cycle.
Daily budget remaining: ${ctx.get('daily_budget_remaining', DAILY_BUDGET_CAP):.2f}
Can self-modify: {ctx.get('can_self_modify', True)}

Categories: {', '.join(CATEGORIES)}

For each task provide:
- title: short name
- description: what to do (1-3 sentences)
- category: one of the categories above
- est_cost: estimated USD cost ($0.50-$5.00 per task)
- priority: 1=highest, 3=lowest
- reasoning: why this task matters now

Rules:
- Total est_cost must not exceed daily budget remaining
- If can_self_modify is False, do NOT plan self_improvement tasks
- If any task involves: new product launch, budget increase, constitutional amendment,
  or legal/financial decisions — mark it as requiring a shareholder gate
- Prefer product and maintenance tasks over exploration
- Be specific and actionable

Respond with JSON:
{{"tasks": [{{"title": "...", "description": "...", "category": "...", "est_cost": N.NN, "priority": N, "reasoning": "...", "requires_gate": false, "gate_reason": ""}}]}}
""")

        return "\n\n".join(parts)

    def _parse_plan(self, content: str, ctx: Dict[str, Any]) -> StrategicPlan:
        """Parse LLM response into a StrategicPlan."""
        plan = StrategicPlan(generated_at=utc_now_iso())

        # Extract JSON
        parsed = self._extract_json(content)
        if not parsed or "tasks" not in parsed:
            plan.context_summary = "Failed to parse plan from LLM response"
            return plan

        raw_tasks = parsed["tasks"][:MAX_TASKS_PER_CYCLE]

        for rt in raw_tasks:
            category = rt.get("category", "maintenance")
            if category not in CATEGORIES:
                category = "maintenance"

            task = PlannedTask(
                title=str(rt.get("title", "untitled"))[:100],
                description=str(rt.get("description", ""))[:500],
                category=category,
                est_cost=min(float(rt.get("est_cost", 1.0)), 5.0),
                priority=max(1, min(3, int(rt.get("priority", 2)))),
                reasoning=str(rt.get("reasoning", ""))[:300],
                requires_gate=bool(rt.get("requires_gate", False)),
                gate_reason=str(rt.get("gate_reason", ""))[:200],
            )

            # Double-check P11 gates
            if not task.requires_gate and self._needs_shareholder_gate(task):
                task.requires_gate = True
                task.gate_reason = "Auto-detected: matches BIBLE P11 gate criteria"

            plan.tasks.append(task)

        plan.context_summary = f"{len(plan.tasks)} tasks planned"
        return plan

    def _needs_shareholder_gate(self, task: PlannedTask) -> bool:
        """Check if a task requires BIBLE.md P11 shareholder gate.

        Gates: new product, launch, budget increase, constitutional amendment,
        legal/financial decisions.
        """
        text = f"{task.title} {task.description} {task.reasoning}".lower()
        return any(kw in text for kw in _P11_GATE_KEYWORDS)

    @staticmethod
    def _extract_json(text: str) -> Optional[Dict[str, Any]]:
        """Extract JSON from LLM response (handles markdown code blocks)."""
        import re
        text = text.strip()
        # Direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Markdown code block
        m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        # First { ... }
        start = text.find('{')
        end = text.rfind('}')
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
        return None

    # ── Telegram formatting ─────────────────────────────────────────

    def format_telegram_summary(self, plan: StrategicPlan) -> str:
        """Format a plan as a Telegram-friendly message."""
        if not plan.tasks:
            return "📋 Strategic Plan: no tasks generated."

        lines = ["📋 Strategic Plan", ""]

        total_cost = 0.0
        for i, task in enumerate(plan.tasks, 1):
            gate_icon = "🔒" if task.requires_gate else "✅"
            cat_icon = {
                "product": "📦",
                "self_improvement": "🧬",
                "infrastructure": "🔧",
                "exploration": "🔍",
                "maintenance": "🛠️",
            }.get(task.category, "📌")

            lines.append(
                f"{i}. {cat_icon} {gate_icon} {task.title}\n"
                f"   {task.description[:120]}\n"
                f"   Est: ${task.est_cost:.2f} | Priority: {task.priority}"
            )
            if task.requires_gate:
                lines.append(f"   ⚠️ Gate: {task.gate_reason or 'Requires /approve'}")
            lines.append("")
            total_cost += task.est_cost

        lines.append(f"Total estimated cost: ${total_cost:.2f}")

        return "\n".join(lines)
