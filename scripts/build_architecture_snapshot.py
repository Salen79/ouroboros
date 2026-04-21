#!/usr/bin/env python3
"""
build_architecture_snapshot.py — Phase 1 architecture snapshot generator.

Reads:
  - ouroboros/tools/*.py       (AST parse → ToolEntry name + description + schema)
  - ouroboros/tools/registry.py (CORE_TOOL_NAMES)
  - ouroboros/consciousness.py  (_BG_TOOL_WHITELIST, near line 1284)
  - config/FILE_ZONES.yaml
  - ouroboros-data/ARCHITECTURE_MAP_2026-04-21.md (Dark Zones D1-D25,
                                                   memory backends, modules)

Writes:
  - company/dashboard/arch/architecture.json

The frontend consumes architecture.json — no live fetch, no server round-trip.
Re-run this script (e.g. via cron or manually) to refresh the snapshot.
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA_ROOT = pathlib.Path("/home/deploy/ouroboros-data")
ARCH_MAP = DATA_ROOT / "ARCHITECTURE_MAP_2026-04-21.md"
OUT_PATH = REPO_ROOT / "company" / "dashboard" / "arch" / "architecture.json"


# ---------------------------------------------------------------------------
# AST parsing of tools/*.py for ToolEntry definitions
# ---------------------------------------------------------------------------

def _literal(node: ast.AST) -> Any:
    """ast.literal_eval that tolerates unknown nodes by returning a placeholder."""
    try:
        return ast.literal_eval(node)
    except Exception:
        if isinstance(node, ast.Call):
            return f"<call:{getattr(node.func, 'id', '?')}>"
        if isinstance(node, ast.Name):
            return f"<name:{node.id}>"
        if isinstance(node, ast.Attribute):
            return f"<attr:{ast.unparse(node)}>"
        try:
            return ast.unparse(node)
        except Exception:
            return None


def _extract_tool_entries(py_path: pathlib.Path) -> List[Dict[str, Any]]:
    """Parse a tools/*.py file and return ToolEntry(...) invocations.

    ToolEntry is called as ToolEntry(name, schema, handler, ...) — either
    as positional or keyword args. We only need name + schema.description +
    schema.parameters.
    """
    src = py_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []

    # Build a line → decorator/function map to locate ToolEntry calls by line
    tool_entries: List[Dict[str, Any]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        fname = getattr(func, "id", None) or getattr(func, "attr", None)
        if fname != "ToolEntry":
            continue

        # Parse args
        name: Optional[str] = None
        schema: Optional[Dict[str, Any]] = None
        is_code_tool = False
        timeout_sec = 120

        if len(node.args) >= 1:
            name = _literal(node.args[0]) if isinstance(_literal(node.args[0]), str) else None
        if len(node.args) >= 2:
            sc = _literal(node.args[1])
            if isinstance(sc, dict):
                schema = sc

        for kw in node.keywords:
            val = _literal(kw.value)
            if kw.arg == "name" and isinstance(val, str):
                name = val
            elif kw.arg == "schema" and isinstance(val, dict):
                schema = val
            elif kw.arg == "is_code_tool":
                is_code_tool = bool(val)
            elif kw.arg == "timeout_sec":
                try:
                    timeout_sec = int(val)
                except Exception:
                    pass

        if not name:
            continue
        if not isinstance(schema, dict):
            schema = {}

        description = schema.get("description", "") if isinstance(schema, dict) else ""
        params = schema.get("parameters", {}) if isinstance(schema, dict) else {}

        tool_entries.append({
            "name": name,
            "description": description,
            "parameters": params,
            "module": str(py_path.relative_to(REPO_ROOT)),
            "line": node.lineno,
            "is_code_tool": is_code_tool,
            "timeout_sec": timeout_sec,
        })

    return tool_entries


def _collect_tools() -> List[Dict[str, Any]]:
    tools_dir = REPO_ROOT / "ouroboros" / "tools"
    tools: List[Dict[str, Any]] = []
    for py in sorted(tools_dir.glob("*.py")):
        if py.name.startswith("_") or py.name == "registry.py":
            continue
        tools.extend(_extract_tool_entries(py))
    # Dedup by name — keep first occurrence (matches registry behavior)
    seen = set()
    deduped: List[Dict[str, Any]] = []
    for t in tools:
        if t["name"] in seen:
            continue
        seen.add(t["name"])
        deduped.append(t)
    return sorted(deduped, key=lambda t: t["name"])


def _collect_core_tool_names() -> List[str]:
    """Parse registry.py to get CORE_TOOL_NAMES."""
    src = (REPO_ROOT / "ouroboros" / "tools" / "registry.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "CORE_TOOL_NAMES":
                    val = _literal(node.value)
                    if isinstance(val, (set, frozenset, list, tuple)):
                        return sorted(val)
    return []


def _collect_consciousness_whitelist() -> List[str]:
    """Parse consciousness.py to find _BG_TOOL_WHITELIST frozenset literal."""
    src = (REPO_ROOT / "ouroboros" / "consciousness.py").read_text(encoding="utf-8")
    # Walk the AST
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "_BG_TOOL_WHITELIST":
                    # rhs is frozenset({...})
                    val = node.value
                    if isinstance(val, ast.Call):
                        if val.args:
                            try:
                                inner = ast.literal_eval(val.args[0])
                                if isinstance(inner, (set, list, tuple, frozenset)):
                                    return sorted(inner)
                            except Exception:
                                pass
    return []


# ---------------------------------------------------------------------------
# FILE_ZONES.yaml — zone classification
# ---------------------------------------------------------------------------

def _collect_file_zones() -> Dict[str, Any]:
    """Parse FILE_ZONES.yaml WITHOUT a yaml dep (simple hand-rolled)."""
    path = REPO_ROOT / "config" / "FILE_ZONES.yaml"
    lines = path.read_text(encoding="utf-8").splitlines()
    zones: Dict[str, Dict[str, Any]] = {}
    current_zone: Optional[str] = None
    current_list_key: Optional[str] = None
    for raw in lines:
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if indent == 2 and stripped.endswith(":") and not stripped.startswith("-"):
            key = stripped[:-1].strip()
            if key in ("red", "yellow", "green"):
                current_zone = key
                current_list_key = None
                zones[current_zone] = {"description": "", "paths": [], "patterns": []}
        elif indent == 4 and stripped.endswith(":"):
            key = stripped[:-1].strip()
            if key in ("paths", "patterns"):
                current_list_key = key
            else:
                current_list_key = None
        elif stripped.startswith("- ") and current_zone and current_list_key:
            val = stripped[2:].strip().strip('"').strip("'")
            zones[current_zone][current_list_key].append(val)
        elif indent == 4 and stripped.startswith("description:") and current_zone:
            desc = stripped[len("description:"):].strip().strip('"').strip("'")
            zones[current_zone]["description"] = desc
    return zones


# ---------------------------------------------------------------------------
# ARCHITECTURE_MAP.md parser
# ---------------------------------------------------------------------------

def _split_by_heading(text: str, level: int) -> List[Tuple[str, str]]:
    """Split markdown by N-hash headings. Returns [(heading, body), ...]."""
    pattern = re.compile(r"^#{" + str(level) + r"}\s+(.+?)$", re.MULTILINE)
    matches = list(pattern.finditer(text))
    result = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        result.append((m.group(1).strip(), text[start:end].strip()))
    return result


def _parse_dark_zones(md: str) -> List[Dict[str, Any]]:
    """Extract D1..D25 sections from the 'Known Dark Zones' heading."""
    # Find the "## 7. Known Dark Zones" section
    top_sections = _split_by_heading(md, 2)
    dz_body = ""
    for h, body in top_sections:
        if "Dark Zone" in h:
            dz_body = body
            break
    if not dz_body:
        return []

    zones: List[Dict[str, Any]] = []
    # Each zone is "### D1. title" then paragraphs
    zone_pattern = re.compile(r"^###\s+(D\d+)\.\s*(.+?)$", re.MULTILINE)
    matches = list(zone_pattern.finditer(dz_body))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(dz_body)
        zid = m.group(1)
        title = m.group(2).strip()
        body = dz_body[start:end].strip()
        # Extract file:line references from body
        refs = sorted(set(re.findall(r"`([a-zA-Z0-9_/.\-]+\.(?:py|md|json|yaml|yml|jsonl|sqlite3|sh))(?::\d+(?:-\d+)?)?`", body)))
        # Also pull raw file:line pairs
        filelines = sorted(set(re.findall(r"([a-zA-Z0-9_/.\-]+\.py):(\d+(?:-\d+)?)", body)))
        zones.append({
            "id": zid,
            "title": title,
            "body_md": body,
            "files": refs,
            "file_lines": [f"{f}:{l}" for f, l in filelines],
        })
    return zones


def _parse_modules_table(md: str) -> List[Dict[str, Any]]:
    """Extract §1.3 modules table. Format: | module | file:line | role |."""
    # Find section by heading
    sections = _split_by_heading(md, 3)
    body = ""
    for h, b in sections:
        if "Key module responsibilities" in h or "module responsibilities" in h.lower():
            body = b
            break
    if not body:
        return []

    modules: List[Dict[str, Any]] = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        # Skip header and separator
        if "---" in line or "File:line" in line or "Module" in line and "Role" in line:
            continue
        parts = [p.strip() for p in line.split("|")[1:-1]]
        if len(parts) != 3:
            continue
        name, fileline, role = parts
        # Clean backticks
        name = name.strip("` ")
        fileline_clean = fileline.strip("` ")
        modules.append({
            "name": name,
            "file_line": fileline_clean,
            "role": role,
        })
    return modules


def _parse_ownership_matrix(md: str) -> List[Dict[str, Any]]:
    """Extract §3.2 per-file ownership matrix."""
    sections = _split_by_heading(md, 3)
    body = ""
    for h, b in sections:
        if "ownership" in h.lower():
            body = b
            break
    if not body:
        return []
    rows: List[Dict[str, Any]] = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        parts = [p.strip() for p in line.split("|")[1:-1]]
        if len(parts) != 3:
            continue
        f, writers, readers = parts
        if f.lower() == "file" or "---" in f:
            continue
        rows.append({
            "file": f.strip("` "),
            "writers_md": writers,
            "readers_md": readers,
        })
    return rows


def _parse_flow_sink_matrix(md: str) -> List[Dict[str, Any]]:
    """Extract §2.2 flow-by-sink matrix."""
    sections = _split_by_heading(md, 3)
    body = ""
    for h, b in sections:
        if "flow-by-sink" in h.lower() or "sink matrix" in h.lower():
            body = b
            break
    if not body:
        return []
    rows: List[Dict[str, Any]] = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        parts = [p.strip() for p in line.split("|")[1:-1]]
        if len(parts) != 3:
            continue
        sink, path, writers = parts
        if sink.lower() == "sink" or "---" in sink:
            continue
        rows.append({
            "sink": sink.strip("` "),
            "path": path,
            "writers_md": writers,
        })
    return rows


# ---------------------------------------------------------------------------
# Node / edge synthesis for the helicopter view
# ---------------------------------------------------------------------------

def _build_topology_nodes(modules: List[Dict[str, Any]]) -> Tuple[List[Dict], List[Dict]]:
    """Return (nodes, edges) for the 3-layer topology graph.

    TOP (process):
      - telegram_api, colab_launcher, worker_pool, consciousness_thread,
        docker(chromadb, postgres, redis), openrouter

    MIDDLE (core modules):
      - agent, loop, context, memory, llm, skill_manager, experiment_engine,
        pattern_detector, strategic_planner, inner_critic, consciousness,
        self_evolution, budget, owner_inject, queue, workers, events, telegram,
        state, git_ops

    BOTTOM (memory backends):
      - scratchpad.md, identity.md, wisdom.md, knowledge/, episodic/,
        chat.jsonl, events.jsonl, supervisor.jsonl, task_results/,
        state/*.json, chromadb (thai_episodes, thai_skills, thai_history)
    """
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    # --- TOP layer: processes ---
    top = [
        ("telegram_api",          "Telegram API",            "external"),
        ("openrouter",            "OpenRouter (LLM)",        "external"),
        ("colab_launcher",        "colab_launcher.py",       "process"),
        ("worker_pool",           "Worker Pool (5 fork)",    "process"),
        ("consciousness_thread",  "Consciousness Thread",    "process"),
        ("docker_chromadb",       "ChromaDB (Docker)",       "infra"),
        ("docker_postgres",       "Postgres (idle)",         "infra"),
        ("docker_redis",          "Redis (idle)",            "infra"),
        ("fs_data",               "~/ouroboros-data/",       "infra"),
    ]
    for nid, label, kind in top:
        nodes.append({"id": nid, "label": label, "layer": "top", "kind": kind})

    # --- MIDDLE layer: core modules ---
    middle_modules = [
        ("agent",             "agent.py",              "ouroboros/agent.py",             876),
        ("loop",              "loop.py",               "ouroboros/loop.py",             1832),
        ("context",           "context.py",            "ouroboros/context.py",           992),
        ("memory",            "memory.py",             "ouroboros/memory.py",            404),
        ("llm",               "llm.py",                "ouroboros/llm.py",               297),
        ("consciousness",     "consciousness.py",      "ouroboros/consciousness.py",    1630),
        ("skill_manager",     "skill_manager.py",      "ouroboros/skill_manager.py",     311),
        ("experiment_engine", "experiment_engine.py",  "ouroboros/experiment_engine.py", 528),
        ("pattern_detector",  "pattern_detector.py",   "ouroboros/pattern_detector.py",  192),
        ("strategic_planner", "strategic_planner.py",  "ouroboros/strategic_planner.py", 335),
        ("inner_critic",      "inner_critic.py",       "ouroboros/inner_critic.py",      360),
        ("self_evolution",    "self_evolution.py",     "ouroboros/self_evolution.py",    659),
        ("budget",            "budget.py",             "ouroboros/budget.py",            110),
        ("owner_inject",      "owner_inject.py",       "ouroboros/owner_inject.py",      103),
        ("queue",             "supervisor/queue.py",   "supervisor/queue.py",            567),
        ("workers",           "supervisor/workers.py", "supervisor/workers.py",          647),
        ("events",            "supervisor/events.py",  "supervisor/events.py",           492),
        ("telegram",          "supervisor/telegram.py","supervisor/telegram.py",         532),
        ("state",             "supervisor/state.py",   "supervisor/state.py",            678),
        ("git_ops",           "supervisor/git_ops.py", "supervisor/git_ops.py",          434),
        ("registry",          "tools/registry.py",     "ouroboros/tools/registry.py",    196),
    ]
    for mid, label, path, loc in middle_modules:
        nodes.append({
            "id": mid, "label": label, "layer": "middle", "kind": "module",
            "path": path, "loc": loc,
        })

    # --- BOTTOM layer: memory backends (7 groups) ---
    bottom = [
        ("mem_scratchpad", "scratchpad.md",       "file_md",      "Working state, REPLACED per task"),
        ("mem_identity",   "identity.md",         "file_md",      "Persistent self-ID"),
        ("mem_wisdom",     "wisdom.md",           "file_md",      "Distilled strategy (28KB)"),
        ("mem_knowledge",  "knowledge/*.md",      "file_dir",     "Topic files + _index.md"),
        ("mem_episodic",   "episodic/*.jsonl",    "file_dir",     "Daily episodes + skills"),
        ("log_chat",       "logs/chat.jsonl",     "logfile",      "Telegram transcript"),
        ("log_events",     "logs/events.jsonl",   "logfile",      "ouroboros-side events (7 writers, 58 sites)"),
        ("log_supervisor", "logs/supervisor.jsonl","logfile",     "supervisor-side events"),
        ("log_tools",      "logs/tools.jsonl",    "logfile",      "tool args + results"),
        ("log_progress",   "logs/progress.jsonl", "logfile",      "progress heartbeats"),
        ("file_task_results","task_results/*.json","file_dir",   "One JSON per task"),
        ("state_main",     "state/state.json",    "state_json",   "budget, session, sha, owner"),
        ("state_queue",    "state/queue_snapshot.json","state_json","PENDING + RUNNING"),
        ("state_budget",   "state/daily_budget.json","state_json","daily auto cap"),
        ("state_directives","state/directives.json","state_json", "stop/pause/forget 24h"),
        ("state_commitments","state/commitments.json","state_json","announced deadlines"),
        ("state_experiments","state/experiments.json","state_json","active + completed experiments"),
        ("state_reflected","state/reflected_tasks.json","state_json","reflection dedup"),
        ("state_consciousness","state/consciousness_history.json","state_json","daily metric snapshots"),
        ("state_cooldown", "state/self_mod_cooldown.json","state_json","self-mod counter"),
        ("chroma_episodes","ChromaDB: thai_episodes","chromadb",  "137 items — insights/errors/decisions"),
        ("chroma_skills",  "ChromaDB: thai_skills","chromadb",    "25 items — two writer formats (D4)"),
        ("chroma_history", "ChromaDB: thai_history","chromadb",   "488 items — chat+events chunks"),
    ]
    for bid, label, kind, desc in bottom:
        nodes.append({
            "id": bid, "label": label, "layer": "bottom", "kind": kind,
            "description": desc,
        })

    # ---- Edges ----
    def E(src, tgt, **kw):
        e = {"source": src, "target": tgt, "kind": kw.get("kind", "flow")}
        if "label" in kw:
            e["label"] = kw["label"]
        if "style" in kw:
            e["style"] = kw["style"]
        edges.append(e)

    # External → launcher
    E("telegram_api", "colab_launcher", label="poll updates")
    E("colab_launcher", "telegram_api", label="send messages", style="dashed")

    # Launcher → workers + consciousness
    E("colab_launcher", "worker_pool", label="enqueue → fork")
    E("colab_launcher", "consciousness_thread", label="spawn thread")
    E("worker_pool", "agent", label="handle_task")
    E("consciousness_thread", "consciousness", label="_loop")

    # Core module wiring
    E("agent", "loop", label="run_llm_loop")
    E("agent", "context", label="_prepare_task_context")
    E("agent", "memory", label="ensure_memory_core")
    E("loop", "llm", label="completions")
    E("loop", "registry", label="dispatch tool")
    E("loop", "inner_critic", label="checkpoint (40%/75%)")
    E("loop", "skill_manager", label="post-task extract")
    E("loop", "experiment_engine", label="record_task")
    E("consciousness", "llm", label="think cycle")
    E("consciousness", "strategic_planner", label="maybe_plan (killed)", style="dashed")
    E("consciousness", "experiment_engine", label="run_full_cycle")
    E("consciousness", "skill_manager", label="auto_reflection")
    E("consciousness", "pattern_detector", label="scan task_results", style="dashed")
    E("llm", "openrouter", label="HTTP", style="dashed")

    # Core → supervisor
    E("colab_launcher", "queue", label="PENDING + RUNNING")
    E("colab_launcher", "telegram", label="log_chat + send_with_budget")
    E("colab_launcher", "git_ops", label="checkout_and_reset")
    E("colab_launcher", "workers", label="worker_main pool")
    E("workers", "agent", label="worker_main → handle_task")
    E("telegram", "memory", label="extract_directive")

    # Docker
    E("registry", "docker_chromadb", label="semantic/episodic writes")
    E("consciousness", "docker_chromadb", label="auto_reflection writes")

    # Memory writes (middle → bottom)
    E("loop", "mem_scratchpad", label="REPLACE post-task", style="unsafe")
    E("agent", "mem_scratchpad", label="placeholder if missing (R1)")
    E("agent", "mem_identity", label="placeholder if missing (R1)")
    E("registry", "mem_identity", label="update_identity tool")
    E("experiment_engine", "mem_wisdom", label="append confirmed exp")
    E("registry", "mem_knowledge", label="knowledge_write")
    E("registry", "mem_episodic", label="record_memory / save_skill")
    E("skill_manager", "mem_episodic", label="via callback")
    E("telegram", "log_chat", label="log_chat append")
    E("agent", "log_events", label="worker_boot, task_received, task_done")
    E("loop", "log_events", label="llm_round, stuck_model_escalation")
    E("consciousness", "log_events", label="thought, stuck, reflection")
    E("workers", "log_supervisor", label="crash events")
    E("queue", "log_supervisor", label="queue_restored")
    E("git_ops", "log_supervisor", label="safe_restart, rescue")
    E("telegram", "log_supervisor", label="outbound notes")
    E("colab_launcher", "log_supervisor", label="launcher_start")
    E("registry", "log_tools", label="tool args + results")
    E("telegram", "log_progress", label="is_progress heartbeats")
    E("loop", "file_task_results", label="per-task JSON write")
    E("state", "state_main", label="budget/session/sha/owner")
    E("git_ops", "state_main", label="current_sha on reset", style="conditional")
    E("queue", "state_queue", label="persist_queue_snapshot")
    E("budget", "state_budget", label="load/save daily spend")
    E("memory", "state_directives", label="save_directive")
    E("queue", "state_commitments", label="CommitmentTracker")
    E("experiment_engine", "state_experiments", label="_save_json")
    E("consciousness", "state_reflected", label="dedup")
    E("self_evolution", "state_cooldown", label="3-task cooldown")

    # ChromaDB
    E("skill_manager", "chroma_skills", label="UUID ids (writer #1)")
    E("registry", "chroma_skills", label="ep_<ts>_<slug> (writer #2) — D4", style="unsafe")
    E("consciousness", "chroma_episodes", label="auto_reflection upsert")
    E("registry", "chroma_episodes", label="record_memory upsert")
    E("registry", "chroma_history", label="recall tool read", style="dashed")

    # Process → filesystem
    E("worker_pool", "fs_data", label="tools / memory writes")
    E("consciousness_thread", "fs_data", label="state / memory / logs")

    return nodes, edges


# ---------------------------------------------------------------------------
# Tool → dark-zone association
# ---------------------------------------------------------------------------

# Tools with known destructive/unsafe surface (from ARCHITECTURE_MAP §6.3)
_DESTRUCTIVE_TOOLS = {
    "run_shell", "claude_code_edit", "knowledge_delete",
    "request_restart", "promote_to_stable", "restart_service",
    "apply_change", "update_identity",
}

# Write-capable tools from §6.2
_WRITE_TOOLS = {
    "drive_write", "update_scratchpad", "update_identity",
    "record_memory", "save_skill", "knowledge_write", "knowledge_delete",
    "repo_write_commit", "repo_commit_push", "propose_change", "apply_change",
    "schedule_task", "cancel_task", "request_restart", "promote_to_stable",
    "toggle_evolution", "toggle_consciousness",
    "create_github_issue", "close_github_issue", "comment_on_issue",
    "restart_service", "send_owner_message", "send_photo",
}


def _associate_tools_with_zones(tools: List[Dict], dark_zones: List[Dict]) -> None:
    """Mutate tools[] adding .dark_zone_ids referencing zones whose body
    text mentions the tool or file."""
    for t in tools:
        hits = []
        name = t["name"]
        module = t["module"]
        for dz in dark_zones:
            body = dz["body_md"]
            if re.search(r"\b" + re.escape(name) + r"\b", body):
                hits.append(dz["id"])
                continue
            # File-level match
            short = module.split("/")[-1]
            if short in body or module in body:
                hits.append(dz["id"])
        t["dark_zone_ids"] = sorted(set(hits))


def _associate_nodes_with_zones(nodes: List[Dict], dark_zones: List[Dict]) -> None:
    """Add dark_zone_ids to topology nodes based on textual overlap.
    We use conservative keyword matching per node id."""
    NODE_KEYWORDS = {
        "agent": ["agent.py"],
        "loop": ["loop.py"],
        "context": ["context.py"],
        "memory": ["memory.py"],
        "consciousness": ["consciousness.py"],
        "skill_manager": ["skill_manager.py", "SkillManager"],
        "experiment_engine": ["experiment_engine.py", "ExperimentEngine"],
        "pattern_detector": ["pattern_detector.py", "pattern_detector"],
        "strategic_planner": ["strategic_planner.py", "StrategicPlanner"],
        "inner_critic": ["inner_critic.py", "inner_critic"],
        "self_evolution": ["self_evolution.py", "SelfEvolution"],
        "budget": ["budget.py"],
        "queue": ["queue.py", "CommitmentTracker"],
        "workers": ["workers.py"],
        "events": ["events.py"],
        "telegram": ["telegram.py"],
        "state": ["state.py", "state.json"],
        "git_ops": ["git_ops.py"],
        "registry": ["registry.py", "run_shell"],
        "mem_scratchpad": ["scratchpad.md"],
        "mem_identity": ["identity.md"],
        "mem_wisdom": ["wisdom.md"],
        "mem_knowledge": ["knowledge/"],
        "mem_episodic": ["episodic/"],
        "log_chat": ["chat.jsonl"],
        "log_events": ["events.jsonl"],
        "log_supervisor": ["supervisor.jsonl"],
        "log_tools": ["tools.jsonl"],
        "log_progress": ["progress.jsonl"],
        "file_task_results": ["task_results/"],
        "state_main": ["state.json"],
        "state_queue": ["queue_snapshot"],
        "state_budget": ["daily_budget"],
        "state_directives": ["directives.json"],
        "state_commitments": ["commitments.json"],
        "state_experiments": ["experiments.json"],
        "state_reflected": ["reflected_tasks"],
        "state_consciousness": ["consciousness_history"],
        "state_cooldown": ["self_mod_cooldown"],
        "chroma_episodes": ["thai_episodes"],
        "chroma_skills": ["thai_skills"],
        "chroma_history": ["thai_history"],
        "docker_chromadb": ["ChromaDB", "chromadb"],
    }
    for n in nodes:
        kws = NODE_KEYWORDS.get(n["id"], [])
        hits = []
        for dz in dark_zones:
            for kw in kws:
                if kw in dz["body_md"] or kw in dz["title"]:
                    hits.append(dz["id"])
                    break
        n["dark_zone_ids"] = sorted(set(hits))


# ---------------------------------------------------------------------------
# Hierarchy — 4-level progressive disclosure (L0 aggregate → L1 group →
# L2 leaf → L3 detail). The leaf IDs reference existing topology node IDs,
# tool names, or Dark Zone IDs depending on the aggregate.
# ---------------------------------------------------------------------------

def _build_hierarchy(topology_nodes: List[Dict], tools: List[Dict],
                     dark_zones: List[Dict]) -> Dict[str, Any]:
    """Produce the 5 L0 aggregates × their L1 groups × L2 leaf ids."""

    # Maps for reference resolution by consumer
    node_ids = {n["id"] for n in topology_nodes}
    tool_names = {t["name"] for t in tools}
    dz_ids = {d["id"] for d in dark_zones}

    def _filter(ids, valid):
        return [x for x in ids if x in valid]

    # -------- INTERFACE --------
    interface = {
        "id": "interface",
        "label": "INTERFACE",
        "tagline": "I/O surface — Telegram, launcher, worker supervision",
        "kind": "structural",
        "color": "#74b9ff",
        "l1": [
            {
                "id": "iface_external",
                "label": "External systems",
                "leaf_kind": "node",
                "leaves": _filter(["telegram_api", "openrouter"], node_ids),
            },
            {
                "id": "iface_launcher",
                "label": "Process supervision",
                "leaf_kind": "node",
                "leaves": _filter(["colab_launcher", "worker_pool", "consciousness_thread", "fs_data"], node_ids),
            },
            {
                "id": "iface_supervisor",
                "label": "Supervisor modules",
                "leaf_kind": "node",
                "leaves": _filter(["queue", "workers", "events", "telegram", "git_ops"], node_ids),
            },
            {
                "id": "iface_docker",
                "label": "Docker infra",
                "leaf_kind": "node",
                "leaves": _filter(["docker_chromadb", "docker_postgres", "docker_redis"], node_ids),
            },
        ],
    }

    # -------- BRAIN --------
    brain = {
        "id": "brain",
        "label": "BRAIN",
        "tagline": "Cognitive loop — task dispatch, reasoning, self-reflection",
        "kind": "structural",
        "color": "#6c5ce7",
        "l1": [
            {
                "id": "brain_taskloop",
                "label": "Task loop",
                "leaf_kind": "node",
                "leaves": _filter(["agent", "loop", "context", "memory"], node_ids),
            },
            {
                "id": "brain_consciousness",
                "label": "Consciousness & planning",
                "leaf_kind": "node",
                "leaves": _filter(["consciousness", "strategic_planner", "inner_critic"], node_ids),
            },
            {
                "id": "brain_learning",
                "label": "Learning",
                "leaf_kind": "node",
                "leaves": _filter(["skill_manager", "experiment_engine", "pattern_detector"], node_ids),
            },
            {
                "id": "brain_governance",
                "label": "Governance",
                "leaf_kind": "node",
                "leaves": _filter(["self_evolution", "budget", "owner_inject", "state"], node_ids),
            },
            {
                "id": "brain_llm",
                "label": "LLM client",
                "leaf_kind": "node",
                "leaves": _filter(["llm"], node_ids),
            },
        ],
    }

    # -------- MEMORY --------
    memory = {
        "id": "memory",
        "label": "MEMORY",
        "tagline": "7 storage backends — files, logs, state, ChromaDB",
        "kind": "structural",
        "color": "#fdcb6e",
        "l1": [
            {
                "id": "mem_working",
                "label": "Working memory",
                "leaf_kind": "node",
                "leaves": _filter(["mem_scratchpad", "mem_identity"], node_ids),
            },
            {
                "id": "mem_longterm",
                "label": "Long-term files",
                "leaf_kind": "node",
                "leaves": _filter(["mem_wisdom", "mem_knowledge", "mem_episodic"], node_ids),
            },
            {
                "id": "mem_logs",
                "label": "Append-only logs",
                "leaf_kind": "node",
                "leaves": _filter(["log_chat", "log_events", "log_supervisor", "log_tools", "log_progress"], node_ids),
            },
            {
                "id": "mem_state",
                "label": "State JSON",
                "leaf_kind": "node",
                "leaves": _filter([
                    "state_main", "state_queue", "state_budget", "state_directives",
                    "state_commitments", "state_experiments", "state_reflected",
                    "state_consciousness", "state_cooldown",
                ], node_ids),
            },
            {
                "id": "mem_chromadb",
                "label": "ChromaDB",
                "leaf_kind": "node",
                "leaves": _filter(["chroma_episodes", "chroma_skills", "chroma_history"], node_ids),
            },
            {
                "id": "mem_taskhistory",
                "label": "Task results",
                "leaf_kind": "node",
                "leaves": _filter(["file_task_results"], node_ids),
            },
        ],
    }

    # -------- TOOLS --------
    tools_groups = {
        "tools_files": ("Files & Repo", {
            "repo_read", "repo_list", "repo_write_commit", "repo_commit_push",
            "drive_read", "drive_list", "drive_write", "git_status", "git_diff",
        }),
        "tools_shell": ("Shell & Code editing", {"run_shell", "claude_code_edit"}),
        "tools_memory": ("Memory & Reflection", {
            "record_memory", "save_skill", "find_skills", "memory_search",
            "semantic_search", "semantic_find_skills", "recall",
            "chromadb_stats", "update_scratchpad", "update_identity",
            "compact_context", "summarize_dialogue", "deep_reflection",
            "knowledge_read", "knowledge_write", "knowledge_list",
        }),
        "tools_taskctl": ("Task & runtime control", {
            "schedule_task", "cancel_task", "wait_for_task", "get_task_result",
            "switch_model", "request_restart", "request_review", "promote_to_stable",
            "toggle_consciousness", "toggle_evolution", "enable_tools",
            "list_available_tools", "forward_to_worker", "propose_change",
            "apply_change", "check_evolution_status", "generate_evolution_stats",
        }),
        "tools_comm": ("Communication", {
            "send_owner_message", "send_photo", "chat_history", "recent_session",
        }),
        "tools_ops": ("Ops & Analysis", {
            "run_ops_check", "restart_service", "read_service_logs",
            "codebase_health", "codebase_digest", "multi_model_review",
        }),
        "tools_web": ("Web, Browser & GitHub", {
            "web_search", "browse_page", "browser_action", "analyze_screenshot",
            "vlm_query", "create_github_issue", "close_github_issue",
            "comment_on_issue", "get_github_issue", "list_github_issues",
        }),
    }
    # Verify every tool is placed exactly once
    placed = set()
    for _, (_, names) in tools_groups.items():
        for n in names:
            if n in placed:
                print(f"WARNING: tool {n} in multiple groups", file=sys.stderr)
            placed.add(n)
    unplaced = [t["name"] for t in tools if t["name"] not in placed]
    if unplaced:
        tools_groups["tools_other"] = ("Other", set(unplaced))

    tools_block = {
        "id": "tools",
        "label": "TOOLS",
        "tagline": f"{len(tools)} capabilities — LLM-accessible actions",
        "kind": "structural",
        "color": "#00b894",
        "l1": [
            {
                "id": gid,
                "label": label,
                "leaf_kind": "tool",
                "leaves": sorted([n for n in names if n in tool_names]),
            }
            for gid, (label, names) in tools_groups.items()
        ],
    }

    # -------- SAFETY --------
    # Group Dark Zones by theme. Each DZ lives in exactly one L1 group.
    safety_groups = [
        ("safety_observability", "Observability gaps",
         ["D1", "D2", "D5", "D15", "D18"]),
        ("safety_consistency", "Data consistency",
         ["D4", "D19", "D20", "D22", "D23"]),
        ("safety_configdrift", "Configuration drift",
         ["D8", "D11", "D12", "D13"]),
        ("safety_attack", "Attack surface",
         ["D14", "D16", "D17", "D25"]),
        ("safety_orphan", "Orphan / restart state",
         ["D3", "D6", "D7", "D10"]),
        ("safety_budget", "Budget & external",
         ["D9", "D21", "D24"]),
    ]

    safety = {
        "id": "safety",
        "label": "SAFETY",
        "tagline": f"{len(dark_zones)} Dark Zones — cross-cutting risk map",
        "kind": "overlay",
        "color": "#e17055",
        "l1": [
            {
                "id": gid,
                "label": label,
                "leaf_kind": "darkzone",
                "leaves": [d for d in ids if d in dz_ids],
            }
            for gid, label, ids in safety_groups
        ],
    }

    # Sanity: cover all DZs
    placed_dz = {d for g in safety["l1"] for d in g["leaves"]}
    missing_dz = sorted(dz_ids - placed_dz)
    if missing_dz:
        print(f"WARNING: unplaced Dark Zones in safety taxonomy: {missing_dz}", file=sys.stderr)
        safety["l1"].append({
            "id": "safety_other",
            "label": "Other",
            "leaf_kind": "darkzone",
            "leaves": missing_dz,
        })

    aggregates = [interface, brain, memory, tools_block, safety]

    # -------- Overlay: compute DZ count per structural aggregate --------
    # For each structural aggregate, count DZs that reference its member nodes.
    def _dz_count_for_nodes(member_ids):
        node_by_id = {n["id"]: n for n in topology_nodes}
        affected = set()
        for nid in member_ids:
            n = node_by_id.get(nid)
            if not n:
                continue
            for dz in n.get("dark_zone_ids", []):
                affected.add(dz)
        return sorted(affected)

    def _dz_count_for_tools(tool_names_set):
        affected = set()
        for t in tools:
            if t["name"] not in tool_names_set:
                continue
            for dz in t.get("dark_zone_ids", []):
                affected.add(dz)
        return sorted(affected)

    for agg in aggregates:
        if agg["id"] == "safety":
            continue
        all_leaves = []
        for l1 in agg["l1"]:
            all_leaves.extend(l1["leaves"])
            leaf_kind = l1.get("leaf_kind")
            if leaf_kind == "tool":
                dzs = _dz_count_for_tools(set(l1["leaves"]))
            elif leaf_kind == "node":
                dzs = _dz_count_for_nodes(l1["leaves"])
            else:
                dzs = []
            l1["dark_zone_ids"] = dzs
        if agg["id"] == "tools":
            agg["dark_zone_ids"] = _dz_count_for_tools(set(all_leaves))
        else:
            agg["dark_zone_ids"] = _dz_count_for_nodes(all_leaves)

    # Safety aggregate DZs = every DZ (its whole domain)
    safety["dark_zone_ids"] = sorted(dz_ids)

    # Simple inter-aggregate edges for L0 "helicopter" context
    l0_edges = [
        {"source": "interface", "target": "brain", "label": "dispatch tasks"},
        {"source": "brain", "target": "memory", "label": "read / write"},
        {"source": "brain", "target": "tools", "label": "invoke"},
        {"source": "tools", "target": "memory", "label": "mutate"},
        {"source": "tools", "target": "interface", "label": "git / telegram / restart"},
        {"source": "safety", "target": "brain", "label": "guards", "style": "dashed"},
        {"source": "safety", "target": "memory", "label": "guards", "style": "dashed"},
        {"source": "safety", "target": "tools", "label": "guards", "style": "dashed"},
    ]

    return {
        "aggregates": aggregates,
        "l0_edges": l0_edges,
    }


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------

def _git_head() -> Dict[str, str]:
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True,
        ).strip()
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=REPO_ROOT, text=True,
        ).strip()
        subj = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%s"], cwd=REPO_ROOT, text=True,
        ).strip()
        return {"sha": sha, "branch": branch, "subject": subj}
    except Exception:
        return {"sha": "", "branch": "", "subject": ""}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_snapshot() -> Dict[str, Any]:
    tools = _collect_tools()
    core_names = _collect_core_tool_names()
    consciousness_whitelist = _collect_consciousness_whitelist()
    file_zones = _collect_file_zones()

    if not ARCH_MAP.exists():
        print(f"WARNING: {ARCH_MAP} not found — dark zones empty.", file=sys.stderr)
        md = ""
    else:
        md = ARCH_MAP.read_text(encoding="utf-8")

    dark_zones = _parse_dark_zones(md)
    modules_table = _parse_modules_table(md)
    ownership_matrix = _parse_ownership_matrix(md)
    flow_sink = _parse_flow_sink_matrix(md)

    # Classify each tool
    for t in tools:
        t["is_core"] = t["name"] in core_names
        t["is_write"] = t["name"] in _WRITE_TOOLS
        t["is_destructive"] = t["name"] in _DESTRUCTIVE_TOOLS
        t["is_consciousness"] = t["name"] in consciousness_whitelist

    # Topology
    nodes, edges = _build_topology_nodes(modules_table)
    _associate_tools_with_zones(tools, dark_zones)
    _associate_nodes_with_zones(nodes, dark_zones)

    # Hierarchy — progressive drill-down structure (Phase 1.5)
    hierarchy = _build_hierarchy(nodes, tools, dark_zones)

    snapshot = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "git": _git_head(),
            "source_map": str(ARCH_MAP.name),
            "repo": str(REPO_ROOT),
            "schema_version": 1,
            "phase": 1,
        },
        "summary": {
            "tools_total": len(tools),
            "tools_core": sum(1 for t in tools if t["is_core"]),
            "tools_write": sum(1 for t in tools if t["is_write"]),
            "tools_destructive": sum(1 for t in tools if t["is_destructive"]),
            "tools_consciousness": sum(1 for t in tools if t["is_consciousness"]),
            "dark_zones": len(dark_zones),
            "modules": len(modules_table),
            "memory_files": len(ownership_matrix),
            "nodes": len(nodes),
            "edges": len(edges),
        },
        "tools": tools,
        "core_tool_names": core_names,
        "consciousness_whitelist": consciousness_whitelist,
        "file_zones": file_zones,
        "modules": modules_table,
        "memory_ownership": ownership_matrix,
        "flow_sink": flow_sink,
        "dark_zones": dark_zones,
        "topology": {
            "nodes": nodes,
            "edges": edges,
        },
        "hierarchy": hierarchy,
    }
    return snapshot


def main() -> int:
    ap = argparse.ArgumentParser(description="Build architecture.json snapshot.")
    ap.add_argument("-o", "--out", default=str(OUT_PATH),
                    help="Output path (default: %(default)s)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    snap = build_snapshot()
    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.quiet:
        s = snap["summary"]
        print(f"✓ snapshot → {out_path}")
        print(f"  tools={s['tools_total']} core={s['tools_core']} "
              f"write={s['tools_write']} destructive={s['tools_destructive']}")
        print(f"  dark_zones={s['dark_zones']} modules={s['modules']} "
              f"memory_files={s['memory_files']}")
        print(f"  topology: {s['nodes']} nodes, {s['edges']} edges")
        h = snap["hierarchy"]
        print(f"  hierarchy: {len(h['aggregates'])} L0 aggregates, "
              f"{sum(len(a['l1']) for a in h['aggregates'])} L1 groups")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
