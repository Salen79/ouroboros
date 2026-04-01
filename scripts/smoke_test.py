#!/usr/bin/env python3
"""
Smoke tests for Ouroboros self-evolution pipeline.

5 fast checks that verify core system integrity WITHOUT starting THAI,
making LLM calls, or touching Telegram. Exit 0 if all pass, non-zero otherwise.

Usage:
    python3 scripts/smoke_test.py
"""

import importlib
import os
import pathlib
import sys
import tempfile

REPO_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_DIR))

PASS = 0
FAIL = 0


def check(name: str, passed: bool, detail: str = ""):
    global PASS, FAIL
    status = "PASS" if passed else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{status}] {name}{suffix}")
    if passed:
        PASS += 1
    else:
        FAIL += 1


def test_registry():
    """Test 1: Tool registry loads and discovers tools."""
    try:
        from ouroboros.tools.registry import ToolRegistry
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            reg = ToolRegistry(repo_dir=tmp_path, drive_root=tmp_path)
            tools = reg.available_tools()
            check("registry_loads", len(tools) > 0, f"{len(tools)} tools discovered")
    except Exception as e:
        check("registry_loads", False, str(e))


def test_context():
    """Test 2: Context builder module imports and key functions exist."""
    try:
        mod = importlib.import_module("ouroboros.context")
        has_build = hasattr(mod, "build_llm_messages")
        has_runtime = hasattr(mod, "_build_runtime_section")
        check("context_imports", has_build and has_runtime,
              f"build_llm_messages={has_build}, _build_runtime_section={has_runtime}")
    except Exception as e:
        check("context_imports", False, str(e))


def test_configs():
    """Test 3: Critical config files exist and are parseable."""
    checks_ok = True
    details = []

    # BIBLE.md
    bible = REPO_DIR / "BIBLE.md"
    if bible.exists() and bible.stat().st_size > 100:
        details.append("BIBLE.md ok")
    else:
        checks_ok = False
        details.append("BIBLE.md MISSING or empty")

    # prompts/SYSTEM.md
    system = REPO_DIR / "prompts" / "SYSTEM.md"
    if system.exists() and system.stat().st_size > 100:
        details.append("SYSTEM.md ok")
    else:
        checks_ok = False
        details.append("SYSTEM.md MISSING or empty")

    # VERSION
    version = REPO_DIR / "VERSION"
    if version.exists():
        v = version.read_text().strip()
        parts = v.split(".")
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            details.append(f"VERSION={v}")
        else:
            checks_ok = False
            details.append(f"VERSION invalid: {v}")
    else:
        checks_ok = False
        details.append("VERSION MISSING")

    # FILE_ZONES.yaml
    zones = REPO_DIR / "config" / "FILE_ZONES.yaml"
    if zones.exists():
        try:
            import yaml
            with open(zones, "r") as f:
                data = yaml.safe_load(f)
            if "zones" in data and "defaults" in data:
                details.append("FILE_ZONES.yaml ok")
            else:
                checks_ok = False
                details.append("FILE_ZONES.yaml missing zones/defaults keys")
        except Exception as e:
            checks_ok = False
            details.append(f"FILE_ZONES.yaml parse error: {e}")
    else:
        checks_ok = False
        details.append("FILE_ZONES.yaml MISSING")

    check("configs_valid", checks_ok, "; ".join(details))


def test_imports():
    """Test 4: All core modules import without error."""
    modules = [
        "ouroboros.agent",
        "ouroboros.context",
        "ouroboros.loop",
        "ouroboros.llm",
        "ouroboros.memory",
        "ouroboros.utils",
        "ouroboros.tools.registry",
        "ouroboros.tools.core",
    ]
    failed = []
    for mod_name in modules:
        try:
            importlib.import_module(mod_name)
        except Exception as e:
            failed.append(f"{mod_name}: {e}")

    check("core_imports", len(failed) == 0,
          f"{len(modules)} modules ok" if not failed else "; ".join(failed))


def test_memory_tools():
    """Test 5: Memory tools are accessible and functional (no LLM)."""
    try:
        from ouroboros.tools.episodic_memory import get_tools as ep_tools
        ep = ep_tools()
        ep_names = [t.name for t in ep]

        has_search = "memory_search" in ep_names
        has_record = "record_memory" in ep_names

        check("memory_tools", has_search and has_record,
              f"episodic: {ep_names}")
    except Exception as e:
        check("memory_tools", False, str(e))


def main():
    print("=" * 60)
    print("Ouroboros Smoke Tests (no LLM, no Telegram)")
    print("=" * 60)

    test_registry()
    test_context()
    test_configs()
    test_imports()
    test_memory_tools()

    print("=" * 60)
    print(f"Results: {PASS} passed, {FAIL} failed")
    print("=" * 60)

    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
