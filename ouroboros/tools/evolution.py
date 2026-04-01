"""
Self-Evolution tools for THAI.

Tools:
1. propose_change — propose a code modification with zone classification
2. apply_change — apply a proposed change (branch, commit, smoke test)
3. check_evolution_status — check current evolution pipeline status
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ouroboros.tools.registry import ToolContext, ToolEntry

log = logging.getLogger(__name__)


def _get_evolution():
    """Lazy-load SelfEvolution to avoid circular imports."""
    from ouroboros.self_evolution import SelfEvolution
    return SelfEvolution()


def _tool_propose_change(
    ctx: ToolContext,
    files: List[str],
    description: str,
    has_deletions: bool = False,
    **kwargs,
) -> str:
    """Propose a code modification and get zone classification.

    Analyzes the files to be changed and returns the zone level,
    which determines what approval is needed before merge.
    """
    if not files:
        return "⚠️ files list is required"
    if not description or not description.strip():
        return "⚠️ description is required"

    evo = _get_evolution()
    zone = evo.classify_changeset(files, has_deletions=has_deletions)

    # Classify each file individually for detail
    file_zones = []
    for f in files:
        fz = evo.classify_file(f)
        file_zones.append(f"  {fz.value.upper():6s} {f}")

    zone_rules = {
        "green": "Auto-merge allowed after smoke tests pass",
        "yellow": "Owner approval required before merge",
        "red": "Explicit owner permission required — BLOCKED by default",
    }

    lines = [
        f"📋 Change Proposal: {description}",
        f"",
        f"Overall zone: {zone.value.upper()}",
        f"Rule: {zone_rules[zone.value]}",
        f"",
        f"File classification:",
        *file_zones,
    ]

    if has_deletions:
        lines.append("")
        lines.append("⚠️ File deletions detected — elevated to RED zone")

    return "\n".join(lines)


def _tool_apply_change(
    ctx: ToolContext,
    branch_name: str,
    commit_message: str,
    files: Optional[List[str]] = None,
    auto_merge: bool = False,
    target_branch: str = "ouroboros",
    **kwargs,
) -> str:
    """Apply a code change: commit to branch, run smoke tests, optionally auto-merge.

    Steps:
    1. Commit changes to the specified branch
    2. Run smoke tests
    3. If auto_merge=True and zone is GREEN, merge to target branch
    """
    if not branch_name or not branch_name.strip():
        return "⚠️ branch_name is required"
    if not commit_message or not commit_message.strip():
        return "⚠️ commit_message is required"

    evo = _get_evolution()
    lines = []

    # Commit changes
    try:
        sha = evo.commit_changes(commit_message, files=files)
        lines.append(f"✅ Committed: {sha[:8]} — {commit_message[:60]}")
    except Exception as e:
        return f"⚠️ Commit failed: {e}"

    # Run smoke tests
    passed, test_output = evo.run_smoke_tests()
    if passed:
        lines.append("✅ Smoke tests passed")
    else:
        lines.append(f"❌ Smoke tests FAILED:\n{test_output[:500]}")
        lines.append("Change committed but NOT safe to merge")
        return "\n".join(lines)

    # Auto-merge if requested
    if auto_merge:
        merged, merge_msg = evo.auto_merge(target_branch=target_branch)
        if merged:
            lines.append(f"✅ {merge_msg}")
        else:
            lines.append(f"⏸️ {merge_msg}")
    else:
        if evo._active_mod:
            lines.append(f"Zone: {evo._active_mod.zone.value.upper()} — merge not requested")

    return "\n".join(lines)


def _tool_check_evolution_status(ctx: ToolContext, **kwargs) -> str:
    """Check the current state of the self-evolution pipeline.

    Returns health check info, active modifications, and zone config status.
    """
    evo = _get_evolution()
    health = evo.health_check()

    lines = [
        "🔬 Self-Evolution Status",
        "",
        f"Status: {health.get('status', 'unknown')}",
        f"Zones config: {'✅' if health.get('zones_config') else '❌'} FILE_ZONES.yaml",
        f"Smoke tests: {'✅' if health.get('smoke_test_exists') else '❌'} smoke_test.py",
        f"Zone self-protection: {'✅' if health.get('zones_self_protection') else '❌'}",
        f"Git clean: {'✅' if health.get('git_clean') else '⚠️ dirty'}",
    ]

    if health.get("active_modification"):
        lines.append("")
        lines.append(f"Active modification: branch={health.get('active_branch')}, zone={health.get('active_zone')}")

    # Run smoke tests
    passed, output = evo.run_smoke_tests()
    lines.append("")
    if passed:
        lines.append("✅ Smoke tests: ALL PASSING")
    else:
        lines.append(f"❌ Smoke tests: FAILING\n{output[:300]}")

    return "\n".join(lines)


def get_tools() -> List[ToolEntry]:
    """Return tool definitions for self-evolution."""
    return [
        ToolEntry(
            name="propose_change",
            schema={
                "name": "propose_change",
                "description": (
                    "Propose a code modification and get zone classification. "
                    "Returns GREEN/YELLOW/RED zone level which determines approval needed. "
                    "GREEN = auto-merge after smoke tests. YELLOW = owner approval. "
                    "RED = explicit owner permission required. "
                    "File deletions are ALWAYS RED zone."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "files": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of file paths to be modified (relative to repo root)"
                        },
                        "description": {
                            "type": "string",
                            "description": "Human-readable description of the proposed change"
                        },
                        "has_deletions": {
                            "type": "boolean",
                            "description": "Whether any files will be deleted (always elevates to RED)",
                            "default": False
                        }
                    },
                    "required": ["files", "description"]
                },
            },
            handler=_tool_propose_change,
        ),
        ToolEntry(
            name="apply_change",
            schema={
                "name": "apply_change",
                "description": (
                    "Apply a code change: commit, run smoke tests, optionally auto-merge. "
                    "Use after making code modifications. Smoke tests must pass before merge. "
                    "Auto-merge only works for GREEN zone changes."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "branch_name": {
                            "type": "string",
                            "description": "Branch name for the change"
                        },
                        "commit_message": {
                            "type": "string",
                            "description": "Git commit message"
                        },
                        "files": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Specific files to stage (null = all tracked changes)"
                        },
                        "auto_merge": {
                            "type": "boolean",
                            "description": "Whether to auto-merge if zone allows (GREEN only)",
                            "default": False
                        },
                        "target_branch": {
                            "type": "string",
                            "description": "Branch to merge into (default: ouroboros)",
                            "default": "ouroboros"
                        }
                    },
                    "required": ["branch_name", "commit_message"]
                },
            },
            handler=_tool_apply_change,
        ),
        ToolEntry(
            name="check_evolution_status",
            schema={
                "name": "check_evolution_status",
                "description": (
                    "Check the current state of the self-evolution pipeline. "
                    "Shows health check, zone config status, active modifications, "
                    "and runs smoke tests to verify system integrity."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                },
            },
            handler=_tool_check_evolution_status,
        ),
    ]
