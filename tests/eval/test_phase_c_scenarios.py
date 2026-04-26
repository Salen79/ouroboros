"""Smoke tests: every Phase C scenario YAML loads cleanly and has the
fields the runner depends on."""
from __future__ import annotations

import pytest

from eval.scenario import load_scenario, SCENARIOS_DIR

PHASE_C_SCENARIOS = [
    "B_identity_tampering",
    "C_directive_confusion",
    "D_scope_discipline",
    "E_skill_extraction",
    "F_memory_retrieval",
    "G_confabulation_resistance",
    "H_hard_rule_recall",
]


@pytest.mark.parametrize("scenario_id", PHASE_C_SCENARIOS)
def test_scenario_loads(scenario_id):
    s = load_scenario(scenario_id)
    assert s.id == scenario_id
    assert s.title
    assert s.version >= 1
    assert s.mode in ("direct", "telegram")
    assert s.input.get("text"), f"{scenario_id}: input.text missing"
    assert s.has_verdict_source(), f"{scenario_id}: no checks and no judge"


@pytest.mark.parametrize("scenario_id", PHASE_C_SCENARIOS)
def test_scenario_has_judge_with_two_models(scenario_id):
    """Phase B fix: cross-model judge (Sonnet + GPT-4.1) on every scenario."""
    s = load_scenario(scenario_id)
    assert s.judge is not None
    assert "anthropic/claude-sonnet-4.6" in s.judge.models
    assert "openai/gpt-4.1" in s.judge.models


@pytest.mark.parametrize("scenario_id", PHASE_C_SCENARIOS)
def test_scenario_pins_light_model(scenario_id):
    """B-O1 fix: every scenario pins OUROBOROS_MODEL_LIGHT to '' so
    routing falls through to Sonnet, eliminating flash-lite variance."""
    s = load_scenario(scenario_id)
    env = (s.setup or {}).get("env_overrides") or {}
    assert env.get("OUROBOROS_MODEL_LIGHT") == "", \
        f"{scenario_id}: missing OUROBOROS_MODEL_LIGHT='' env override"


@pytest.mark.parametrize("scenario_id", [
    s for s in PHASE_C_SCENARIOS if s != "C_directive_confusion"
])
def test_direct_mode_scenarios(scenario_id):
    """All Phase C scenarios except C run in direct mode."""
    s = load_scenario(scenario_id)
    assert s.mode == "direct", f"{scenario_id}: expected direct mode"


def test_scenario_c_marked_telegram():
    """C is the only telegram-mode scenario; documented as draft."""
    s = load_scenario("C_directive_confusion")
    assert s.mode == "telegram"


def test_all_scenarios_discovered_by_glob():
    """The --all flag must pick up every Phase C scenario file."""
    discovered = sorted(p.stem for p in SCENARIOS_DIR.glob("*.yaml")
                        if not p.stem.startswith("_"))
    for sid in PHASE_C_SCENARIOS:
        assert sid in discovered, f"{sid} not discovered by glob"
    # A_infra_confusion should also be present (Phase B pilot).
    assert "A_infra_confusion" in discovered
