#!/usr/bin/env python3
"""
build_architecture_snapshot.py — Phase 1 architecture snapshot generator.

Reads:
  - ouroboros/tools/*.py       (AST parse → ToolEntry name + description + schema)
  - ouroboros/tools/registry.py (CORE_TOOL_NAMES)
  - ouroboros/consciousness.py  (_BG_TOOL_WHITELIST, near line 1284)
  - config/FILE_ZONES.yaml
  - docs/architecture/ARCHITECTURE_MAP.md (Dark Zones D1-D27,
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
ARCH_MAP = REPO_ROOT / "docs" / "architecture" / "ARCHITECTURE_MAP.md"
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
# Phase 1.7 — Functional block classification (organ → block → nodes).
#
# Blocks are hand-curated groupings with a Russian label, a guiding
# question, and either a list of topology-node IDs (nodes-based organs)
# or tool names / abstract safety items (for TOOLS / SAFETY).
#
# Edges are block-level, with only two kinds for display: "control"
# (invocations, guards, commands) and "data" (reads, writes, observations).
# The fine-grained 5-kind taxonomy stays in the `subtype` field so Phase
# 2 can still filter by "governs" vs "reads_from" if needed.
# ---------------------------------------------------------------------------

# --- BRAIN: 5 functional blocks ---
BRAIN_BLOCKS = [
    {
        "id": "brain_perception",
        "organ": "brain",
        "label": "Восприятие",
        "label_en": "Perception",
        "question": "Что пришло? Какого это типа? Что я знаю про это?",
        "question_en": "What arrived? What type is it? What do I know about it?",
        "nodes": ["agent", "context", "memory", "owner_inject"],
    },
    {
        "id": "brain_thinking",
        "organ": "brain",
        "label": "Мышление",
        "label_en": "Thinking",
        "question": "Раунд за раундом: думаю → действую → наблюдаю",
        "question_en": "Round by round: think → act → observe",
        "nodes": ["loop", "llm"],
    },
    {
        "id": "brain_selfcontrol",
        "organ": "brain",
        "label": "Самоконтроль",
        "label_en": "Self-Control",
        "question": "Правильно ли я делаю? Можно ли мне это делать?",
        "question_en": "Am I doing it right? Am I allowed to do this?",
        "nodes": ["inner_critic", "self_evolution", "budget"],
    },
    {
        "id": "brain_reflection",
        "organ": "brain",
        "label": "Рефлексия",
        "label_en": "Reflection",
        "question": "Что я могу извлечь из того, что было?",
        "question_en": "What can I extract from what happened?",
        "nodes": ["skill_manager", "experiment_engine", "pattern_detector"],
    },
    {
        "id": "brain_continuous",
        "organ": "brain",
        "label": "Фоновое сознание",
        "label_en": "Background Consciousness",
        "question": "Что происходит между задачами? К чему я иду?",
        "question_en": "What happens between tasks? Where am I headed?",
        "nodes": ["consciousness", "strategic_planner"],
    },
]

# --- INTERFACE: 3 blocks ---
INTERFACE_BLOCKS = [
    {
        "id": "iface_comm",
        "organ": "interface",
        "label": "Связь с внешним миром",
        "label_en": "External Comms",
        "question": "Что мне говорят? Что я отвечаю?",
        "question_en": "What am I told? What do I reply?",
        "nodes": ["colab_launcher", "telegram"],
    },
    {
        "id": "iface_dispatch",
        "organ": "interface",
        "label": "Диспетчеризация",
        "label_en": "Dispatch",
        "question": "Кто это сделает? Когда? В какой последовательности?",
        "question_en": "Who will do this? When? In what sequence?",
        "nodes": ["queue", "workers", "events", "worker_pool", "consciousness_thread"],
    },
    {
        "id": "iface_infra",
        "organ": "interface",
        "label": "Жизнеобеспечение",
        "label_en": "Infrastructure",
        "question": "Что со мной было? На какой версии я работаю?",
        "question_en": "What happened to me? Which version am I running?",
        "nodes": ["state", "git_ops", "fs_data",
                  "docker_chromadb", "docker_postgres", "docker_redis"],
    },
]

# --- EXTERNAL (not a functional organ proper — rendered as periphery) ---
EXTERNAL_NODES = ["telegram_api", "openrouter"]

# --- MEMORY: 3 lifetime levels, with 4 sub-blocks inside Долговременная ---
MEMORY_BLOCKS = [
    {
        "id": "mem_working",
        "organ": "memory",
        "level": "working",
        "label": "Рабочая",         "label_en": "Working",
        "tagline": "per-task — теряется в конце задачи",
        "tagline_en": "per-task — discarded at task end",
        "question": "Что происходит прямо сейчас?",
        "question_en": "What's happening right now?",
        "nodes": ["mem_scratchpad"],
        "virtual_items": ["messages[]", "owner_mailbox/"],
    },
    {
        "id": "mem_operational",
        "organ": "memory",
        "level": "short",
        "label": "Оперативная",     "label_en": "Short-term",
        "tagline": "день / сессия — медленно устаревает",
        "tagline_en": "session / day — ages out",
        "question": "Что было недавно? Что меня попросили 24 часа назад?",
        "question_en": "What happened recently? What was I asked 24h ago?",
        "nodes": ["log_chat", "log_events", "log_supervisor", "log_tools",
                  "log_progress",
                  "state_directives", "state_budget", "state_queue"],
    },
    {
        "id": "mem_identity",
        "organ": "memory",
        "level": "long", "sub": "identity",
        "label": "Идентичность",    "label_en": "Identity",
        "question": "Кто я? Что я знаю про себя?",
        "question_en": "Who am I? What do I know about myself?",
        "nodes": ["mem_identity", "mem_wisdom"],
    },
    {
        "id": "mem_knowledge",
        "organ": "memory",
        "level": "long", "sub": "knowledge",
        "label": "Знания",          "label_en": "Knowledge",
        "question": "Что я выучил про предметную область?",
        "question_en": "What have I learned about the domain?",
        "nodes": ["mem_knowledge"],
    },
    {
        "id": "mem_experience",
        "organ": "memory",
        "level": "long", "sub": "experience",
        "label": "Опыт",            "label_en": "Experience",
        "question": "Что я пробовал? Что сработало?",
        "question_en": "What have I tried? What worked?",
        "nodes": ["mem_episodic", "chroma_episodes", "chroma_skills", "chroma_history"],
    },
    {
        "id": "mem_service",
        "organ": "memory",
        "level": "long", "sub": "service",
        "label": "Служебная",       "label_en": "Service",
        "question": "В каком я состоянии? Что я пообещал?",
        "question_en": "What state am I in? What did I commit to?",
        "nodes": ["state_main", "state_experiments", "state_commitments",
                  "state_reflected", "state_cooldown", "state_consciousness"],
    },
    {
        "id": "mem_archive",
        "organ": "memory",
        "level": "archive",
        "label": "Архив задач",     "label_en": "Task Archive",
        "tagline": "append-only — 645+ файлов",
        "tagline_en": "append-only — 645+ files",
        "question": "Что я делал раньше и как это прошло?",
        "question_en": "What did I do before and how did it go?",
        "nodes": ["file_task_results"],
    },
]

# --- TOOLS: 6 functional blocks (Phase 1.7) ---
TOOLS_BLOCKS = [
    {
        "id": "tools_read",
        "organ": "tools",
        "label": "Чтение мира",     "label_en": "World Read",
        "question": "Что есть?",    "question_en": "What's there?",
        "tools": [
            "repo_read", "repo_list", "git_status", "git_diff",
            "codebase_digest", "codebase_health",
            "drive_read", "drive_list",
            "chat_history", "recent_session", "summarize_dialogue",
            "recall", "memory_search", "semantic_search",
            "find_skills", "semantic_find_skills",
            "knowledge_read", "knowledge_list",
            "web_search", "browse_page", "vlm_query", "analyze_screenshot",
            "read_service_logs", "run_ops_check", "chromadb_stats",
            "list_github_issues", "get_github_issue",
            "wait_for_task", "get_task_result",
        ],
    },
    {
        "id": "tools_write",
        "organ": "tools",
        "label": "Изменение мира",  "label_en": "World Write",
        "question": "Что сделать?", "question_en": "What to do?",
        "tools": [
            "drive_write", "repo_write_commit", "repo_commit_push",
            "propose_change", "apply_change", "claude_code_edit",
            "update_scratchpad", "update_identity",
            "record_memory", "save_skill", "knowledge_write",
            "send_owner_message", "send_photo",
            "create_github_issue", "close_github_issue", "comment_on_issue",
        ],
    },
    {
        "id": "tools_selfctl",
        "organ": "tools",
        "label": "Управление собой", "label_en": "Self-Control",
        "question": "Как мне изменить свой режим работы?",
        "question_en": "How do I change my own operating mode?",
        "tools": [
            "schedule_task", "cancel_task", "forward_to_worker",
            "request_restart", "restart_service", "promote_to_stable",
            "switch_model", "toggle_consciousness", "toggle_evolution",
            "compact_context",
        ],
    },
    {
        "id": "tools_reflection",
        "organ": "tools",
        "label": "Саморефлексия",   "label_en": "Self-Reflection",
        "question": "Как мне оценить своё поведение?",
        "question_en": "How do I evaluate my own behavior?",
        "tools": [
            "deep_reflection", "multi_model_review", "request_review",
            "check_evolution_status", "generate_evolution_stats",
        ],
    },
    {
        "id": "tools_danger",
        "organ": "tools",
        "label": "Опасная сила",    "label_en": "Dangerous Powers",
        "question": "Что могу сломать одним вызовом?",
        "question_en": "What can I break with one call?",
        "tools": ["run_shell", "browser_action"],
    },
    {
        "id": "tools_meta",
        "organ": "tools",
        "label": "Мета",            "label_en": "Meta",
        "question": "Какие у меня вообще есть инструменты?",
        "question_en": "What tools do I even have?",
        "tools": ["list_available_tools", "enable_tools"],
    },
]

# --- SAFETY: 5 functional blocks ---
# Items are abstract safety mechanisms (not topology nodes), each with
# a RU title and a code reference (file:line or concept).
SAFETY_BLOCKS = [
    {
        "id": "safety_prevent",
        "organ": "safety",
        "label": "Предотвращение",  "label_en": "Prevention",
        "question": "Что агенту запрещено делать?",
        "question_en": "What is the agent forbidden from doing?",
        "items": [
            {"title": "FILE_ZONES (red / yellow / green)", "ref": "config/FILE_ZONES.yaml"},
            {"title": "Destructive-keyword guard",          "ref": "supervisor/workers.py:320-351"},
            {"title": "Consciousness whitelist",            "ref": "ouroboros/consciousness.py:1273-1300"},
            {"title": "Budget caps (task + daily)",         "ref": "ouroboros/budget.py + loop.py:465"},
        ],
    },
    {
        "id": "safety_observe",
        "organ": "safety",
        "label": "Наблюдение",      "label_en": "Observation",
        "question": "Что идёт не так прямо сейчас?",
        "question_en": "What's going wrong right now?",
        "items": [
            {"title": "Inner Critic (checkpoints 40% / 75%)", "ref": "ouroboros/inner_critic.py"},
            {"title": "Stuck Detector (3 similar thoughts)",  "ref": "ouroboros/consciousness.py:44-78"},
            {"title": "Action-first nudge",                   "ref": "ouroboros/loop.py:1217-1241"},
            {"title": "Budget drift alert",                   "ref": "context.py:369 (live OR credits)"},
        ],
    },
    {
        "id": "safety_contain",
        "organ": "safety",
        "label": "Сдерживание",     "label_en": "Containment",
        "question": "Как остановить до того, как станет хуже?",
        "question_en": "How to stop before it gets worse?",
        "items": [
            {"title": "MAX_ROUNDS = 12",         "ref": "ouroboros/loop.py:1050"},
            {"title": "Per-task cost cap $3",    "ref": "ouroboros/loop.py:465"},
            {"title": "Circuit breaker (3×empty)","ref": "ouroboros/loop.py:1034"},
            {"title": "/panic handler",          "ref": "colab_launcher.py:391-479"},
        ],
    },
    {
        "id": "safety_recover",
        "organ": "safety",
        "label": "Восстановление",  "label_en": "Recovery",
        "question": "Как вернуться в рабочее состояние?",
        "question_en": "How to return to a working state?",
        "items": [
            {"title": "git reset on startup",         "ref": "supervisor/git_ops.py:208-315"},
            {"title": "R1 memory restore",            "ref": "ouroboros/agent.py:423-468"},
            {"title": "Queue snapshot restore",       "ref": "supervisor/queue.py:177-215"},
            {"title": "Self-mod cooldown (3 tasks)",  "ref": "ouroboros/self_evolution.py:601-660"},
        ],
    },
    {
        "id": "safety_weaknesses",
        "organ": "safety",
        "label": "Известные слабости", "label_en": "Known Weaknesses",
        "question": "Что мы знаем, что плохо, но пока не починили?",
        "question_en": "What do we know is bad but haven't fixed yet?",
        "items": [],  # filled programmatically from SAFETY_DZ_GROUPS
    },
]

# --- Phase 1.8: semantic (role-based) labels for every topology node ---
# Principle: short Russian name (1-3 words) that conveys the node's role in
# the system, not its technology. The original `label` (file path) remains
# available as a secondary caption.
SEMANTIC_LABELS = {
    # ВНЕШНЕЕ
    "telegram_api":          "Мессенджер",
    "openrouter":            "Облако моделей",

    # ИНТЕРФЕЙС — Связь с внешним миром
    "colab_launcher":        "Главный процесс",
    "telegram":              "Канал сообщений",
    # ИНТЕРФЕЙС — Диспетчеризация
    "queue":                 "Очередь задач",
    "workers":               "Работники",
    "events":                "Шина событий",
    "worker_pool":           "Пул работников",
    "consciousness_thread":  "Фоновый поток",
    # ИНТЕРФЕЙС — Жизнеобеспечение
    "state":                 "Хранитель состояния",
    "git_ops":               "Git-операции",
    "fs_data":               "Файловое хранилище",
    "docker_chromadb":       "Семантическая БД",
    "docker_postgres":       "Реляционная БД",
    "docker_redis":          "Кеш",

    # МОЗГ — Восприятие
    "agent":                 "Диспетчер задачи",
    "context":               "Сборщик контекста",
    "memory":                "Работа с памятью",
    "owner_inject":          "Почтовый ящик задачи",
    # МОЗГ — Мышление
    "loop":                  "Цикл мышления",
    "llm":                   "Клиент модели",
    # МОЗГ — Самоконтроль
    "inner_critic":          "Внутренний критик",
    "self_evolution":        "Самоэволюция",
    "budget":                "Учёт бюджета",
    # МОЗГ — Рефлексия
    "skill_manager":         "Жизненный цикл навыков",
    "experiment_engine":     "Движок экспериментов",
    "pattern_detector":      "Детектор паттернов",
    # МОЗГ — Фоновое сознание
    "consciousness":         "Сознание",
    "strategic_planner":     "Стратег",

    # ИНСТРУМЕНТЫ
    "registry":              "Реестр инструментов",

    # ПАМЯТЬ — Рабочая
    "mem_scratchpad":        "Блокнот задачи",
    # ПАМЯТЬ — Оперативная
    "log_chat":              "История чатов",
    "log_events":            "Лента событий",
    "log_supervisor":        "Лог супервизора",
    "log_tools":             "Журнал вызовов",
    "log_progress":          "Прогресс задач",
    "state_directives":      "Директивы",
    "state_budget":          "Дневной бюджет",
    "state_queue":           "Снимок очереди",
    # ПАМЯТЬ — Идентичность
    "mem_identity":          "Идентичность",
    "mem_wisdom":            "Мудрость",
    # ПАМЯТЬ — Знания
    "mem_knowledge":         "База знаний",
    # ПАМЯТЬ — Опыт
    "mem_episodic":          "Эпизоды дня",
    "chroma_episodes":       "Семантические эпизоды",
    "chroma_skills":         "Навыки (RAG)",
    "chroma_history":        "Архив диалогов (RAG)",
    # ПАМЯТЬ — Служебная
    "state_main":            "Общее состояние",
    "state_experiments":     "Эксперименты",
    "state_commitments":     "Обязательства",
    "state_reflected":       "Отрефлексированные задачи",
    "state_cooldown":        "Кулдаун самомодификаций",
    "state_consciousness":   "Метрики сознания",
    # ПАМЯТЬ — Архив
    "file_task_results":     "Архив задач",
}


# English counterparts (compact, tech-doc style).
SEMANTIC_LABELS_EN = {
    # ВНЕШНЕЕ / EXTERNAL
    "telegram_api":          "Messenger",
    "openrouter":             "Model Cloud",
    # ИНТЕРФЕЙС / INTERFACE
    "colab_launcher":        "Main Process",
    "telegram":               "Message Channel",
    "queue":                  "Task Queue",
    "workers":                "Workers",
    "events":                 "Event Bus",
    "worker_pool":            "Worker Pool",
    "consciousness_thread":   "Background Thread",
    "state":                  "State Keeper",
    "git_ops":                "Git Operations",
    "fs_data":                "File Storage",
    "docker_chromadb":        "Semantic DB",
    "docker_postgres":        "Relational DB",
    "docker_redis":           "Cache",
    # МОЗГ / BRAIN
    "agent":                  "Task Dispatcher",
    "context":                "Context Builder",
    "memory":                 "Memory I/O",
    "owner_inject":           "Task Mailbox",
    "loop":                   "Thinking Loop",
    "llm":                    "Model Client",
    "inner_critic":           "Inner Critic",
    "self_evolution":         "Self-Evolution",
    "budget":                 "Budget Ledger",
    "skill_manager":          "Skill Lifecycle",
    "experiment_engine":      "Experiment Engine",
    "pattern_detector":       "Pattern Detector",
    "consciousness":          "Consciousness",
    "strategic_planner":      "Strategist",
    # ИНСТРУМЕНТЫ / TOOLS
    "registry":               "Tool Registry",
    # ПАМЯТЬ / MEMORY
    "mem_scratchpad":         "Task Scratchpad",
    "log_chat":               "Chat History",
    "log_events":             "Event Stream",
    "log_supervisor":         "Supervisor Log",
    "log_tools":              "Call Journal",
    "log_progress":           "Task Progress",
    "state_directives":       "Directives",
    "state_budget":           "Daily Budget",
    "state_queue":            "Queue Snapshot",
    "mem_identity":           "Identity",
    "mem_wisdom":             "Wisdom",
    "mem_knowledge":          "Knowledge Base",
    "mem_episodic":           "Daily Episodes",
    "chroma_episodes":        "Semantic Episodes",
    "chroma_skills":          "Skills (RAG)",
    "chroma_history":         "Dialogue Archive (RAG)",
    "state_main":             "Core State",
    "state_experiments":      "Experiments",
    "state_commitments":      "Commitments",
    "state_reflected":        "Reflected Tasks",
    "state_cooldown":         "Self-Mod Cooldown",
    "state_consciousness":    "Consciousness Metrics",
    "file_task_results":      "Task Archive",
}


# Dark-Zone taxonomy (RU + EN labels).
SAFETY_DZ_GROUPS = [
    # (label_ru, label_en, ids)
    ("Наблюдаемость",   "Observability",   ["D1", "D2", "D5", "D15", "D18"]),
    ("Согласованность", "Consistency",     ["D4", "D19", "D20", "D22", "D23"]),
    ("Конфигурация",    "Configuration",   ["D8", "D11", "D12", "D13"]),
    ("Атаки",           "Attack Surface",  ["D14", "D16", "D17", "D25", "D26", "D27"]),
    ("Артефакты",       "Artifacts",       ["D3", "D6", "D7", "D10"]),
    ("Внешнее",         "External",        ["D9", "D21", "D24"]),
]


# --- Typed edges (block-level, control/data) ---
# Only the ~17 most-significant cross-organ flows. Everything else is in
# drill-down at L1 zoom.
TYPED_EDGES = [
    # --- ПАМЯТЬ internal ---
    {"source": "mem_working", "target": "mem_experience",
     "kind": "data", "subtype": "writes_to", "visibility": "l0",
     "label":    "следы в episodic/skills после задачи",
     "label_en": "traces into episodic/skills after task"},
    {"source": "mem_operational", "target": "mem_experience",
     "kind": "data", "subtype": "writes_to", "visibility": "l0",
     "label":    "offline indexing chat+events → ChromaDB",
     "label_en": "offline indexing chat+events → ChromaDB"},
    {"source": "mem_experience", "target": "mem_working",
     "kind": "data", "subtype": "reads_from", "visibility": "l0",
     "label":    "recall / find_skills в новый контекст",
     "label_en": "recall / find_skills into new context"},

    # --- ПАМЯТЬ → МОЗГ ---
    {"source": "mem_identity", "target": "brain_perception",
     "kind": "data", "subtype": "reads_from", "visibility": "l0",
     "label":    "identity.md в каждый prompt",
     "label_en": "identity.md into every prompt"},
    {"source": "mem_operational", "target": "brain_perception",
     "kind": "data", "subtype": "reads_from", "visibility": "l0",
     "label":    "directives 24h в контекст",
     "label_en": "directives 24h into context"},

    # --- ИНТЕРФЕЙС ↔ МОЗГ ---
    {"source": "iface_comm", "target": "brain_perception",
     "kind": "control", "subtype": "invokes", "visibility": "l0",
     "label":    "входящая задача → handle_task",
     "label_en": "incoming task → handle_task"},

    # --- МОЗГ Мышление ↔ ИНСТРУМЕНТЫ ---
    {"source": "brain_thinking", "target": "tools_read",
     "kind": "control", "subtype": "invokes", "visibility": "l0",
     "label":    "tool call (чтение)",
     "label_en": "tool call (read)"},
    {"source": "brain_thinking", "target": "tools_write",
     "kind": "control", "subtype": "invokes", "visibility": "l0",
     "label":    "tool call (запись)",
     "label_en": "tool call (write)"},
    {"source": "brain_thinking", "target": "tools_selfctl",
     "kind": "control", "subtype": "invokes", "visibility": "l0",
     "label":    "tool call (управление)",
     "label_en": "tool call (self-control)"},
    {"source": "brain_thinking", "target": "tools_danger",
     "kind": "control", "subtype": "invokes", "visibility": "l0",
     "label":    "tool call (опасное)",
     "label_en": "tool call (dangerous)"},
    {"source": "tools_read", "target": "brain_thinking",
     "kind": "data", "subtype": "reads_from", "visibility": "l0",
     "label":    "результаты чтения",
     "label_en": "read results"},
    {"source": "tools_write", "target": "brain_thinking",
     "kind": "data", "subtype": "writes_to", "visibility": "l0",
     "label":    "подтверждения изменений",
     "label_en": "write confirmations"},

    # --- МОЗГ → ПАМЯТЬ ---
    {"source": "brain_thinking", "target": "mem_working",
     "kind": "data", "subtype": "writes_to", "visibility": "l0",
     "label":    "scratchpad writes, event emits",
     "label_en": "scratchpad writes, event emits"},
    {"source": "brain_reflection", "target": "mem_experience",
     "kind": "data", "subtype": "writes_to", "visibility": "l0",
     "label":    "skills, episodes",
     "label_en": "skills, episodes"},

    # --- БЕЗОПАСНОСТЬ → МОЗГ Самоконтроль ---
    {"source": "safety_observe", "target": "brain_selfcontrol",
     "kind": "control", "subtype": "governs", "visibility": "l0",
     "label":    "inner_critic / stuck / drift",
     "label_en": "inner_critic / stuck / drift"},
    {"source": "safety_contain", "target": "brain_selfcontrol",
     "kind": "control", "subtype": "governs", "visibility": "l0",
     "label":    "MAX_ROUNDS / cost cap / circuit breaker",
     "label_en": "MAX_ROUNDS / cost cap / circuit breaker"},

    # --- БЕЗОПАСНОСТЬ Восстановление → ИНТЕРФЕЙС Жизнеобеспечение ---
    {"source": "safety_recover", "target": "iface_infra",
     "kind": "control", "subtype": "governs", "visibility": "l0",
     "label":    "git reset, queue snapshot restore",
     "label_en": "git reset, queue snapshot restore"},
]


# --- LAYOUT (SVG user-space coordinates) ---
# The viewBox is expanded to 2000×1780 to host the new SAFETY organ.
LAYOUT = {
    "viewbox": {"x": 0, "y": 0, "w": 2000, "h": 1780},
    "organs": {
        "external":  {"x": 0,    "y": 20,   "w": 2000, "h": 120,
                      "label_x": 1000, "label_y": 40,
                      "label": "ВНЕШНЕЕ",     "label_en": "EXTERNAL"},
        "interface": {"x": 0,    "y": 170,  "w": 2000, "h": 240,
                      "label_x": 1000, "label_y": 185,
                      "label": "ИНТЕРФЕЙС",    "label_en": "INTERFACE"},
        "brain":     {"x": 440,  "y": 440,  "w": 1110, "h": 580,
                      "label_x": 990, "label_y": 455,
                      "label": "МОЗГ",         "label_en": "BRAIN"},
        "tools":     {"x": 1560, "y": 440,  "w": 410,  "h": 580,
                      "label_x": 1765, "label_y": 455,
                      "label": "ИНСТРУМЕНТЫ",  "label_en": "TOOLS"},
        "memory":    {"x": 30,   "y": 1050, "w": 1940, "h": 330,
                      "label_x": 1000, "label_y": 1065,
                      "label": "ПАМЯТЬ",       "label_en": "MEMORY"},
        "safety":    {"x": 30,   "y": 1400, "w": 1940, "h": 360,
                      "label_x": 1000, "label_y": 1415,
                      "label": "БЕЗОПАСНОСТЬ", "label_en": "SAFETY"},
    },
    "blocks": {
        # INTERFACE
        "iface_comm":     {"x": 40,  "y": 210, "w": 580, "h": 190,
                           "label_x": 330, "label_y": 227},
        "iface_dispatch": {"x": 640, "y": 210, "w": 620, "h": 190,
                           "label_x": 950, "label_y": 227},
        "iface_infra":    {"x": 1280,"y": 210, "w": 680, "h": 190,
                           "label_x": 1620,"label_y": 227},

        # BRAIN
        "brain_perception":  {"x": 460,  "y": 480, "w": 210, "h": 530,
                              "label_x": 565, "label_y": 497},
        "brain_thinking":    {"x": 680,  "y": 480, "w": 210, "h": 530,
                              "label_x": 785, "label_y": 497},
        "brain_selfcontrol": {"x": 900,  "y": 480, "w": 210, "h": 530,
                              "label_x": 1005,"label_y": 497},
        "brain_reflection":  {"x": 1120, "y": 480, "w": 210, "h": 530,
                              "label_x": 1225,"label_y": 497},
        "brain_continuous":  {"x": 1340, "y": 480, "w": 210, "h": 530,
                              "label_x": 1445,"label_y": 497},

        # TOOLS (6 stacked)
        "tools_read":        {"x": 1580, "y": 480, "w": 380, "h": 80,
                              "label_x": 1770,"label_y": 495},
        "tools_write":       {"x": 1580, "y": 570, "w": 380, "h": 80,
                              "label_x": 1770,"label_y": 585},
        "tools_selfctl":     {"x": 1580, "y": 660, "w": 380, "h": 80,
                              "label_x": 1770,"label_y": 675},
        "tools_reflection":  {"x": 1580, "y": 750, "w": 380, "h": 70,
                              "label_x": 1770,"label_y": 765},
        "tools_danger":      {"x": 1580, "y": 830, "w": 380, "h": 60,
                              "label_x": 1770,"label_y": 845},
        "tools_meta":        {"x": 1580, "y": 900, "w": 380, "h": 60,
                              "label_x": 1770,"label_y": 915},

        # MEMORY
        "mem_working":      {"x": 40,   "y": 1100, "w": 220, "h": 260,
                             "label_x": 150, "label_y": 1117},
        "mem_operational":  {"x": 280,  "y": 1100, "w": 500, "h": 260,
                             "label_x": 530, "label_y": 1117},
        "mem_identity":     {"x": 810,  "y": 1100, "w": 180, "h": 260,
                             "label_x": 900, "label_y": 1117},
        "mem_knowledge":    {"x": 1000, "y": 1100, "w": 170, "h": 260,
                             "label_x": 1085,"label_y": 1117},
        "mem_experience":   {"x": 1180, "y": 1100, "w": 310, "h": 260,
                             "label_x": 1335,"label_y": 1117},
        "mem_service":      {"x": 1500, "y": 1100, "w": 320, "h": 260,
                             "label_x": 1660,"label_y": 1117},
        "mem_archive":      {"x": 1830, "y": 1100, "w": 130, "h": 260,
                             "label_x": 1895,"label_y": 1117},

        # SAFETY
        "safety_prevent":    {"x": 40,   "y": 1430, "w": 380, "h": 320,
                              "label_x": 230, "label_y": 1450},
        "safety_observe":    {"x": 430,  "y": 1430, "w": 380, "h": 320,
                              "label_x": 620, "label_y": 1450},
        "safety_contain":    {"x": 820,  "y": 1430, "w": 380, "h": 320,
                              "label_x": 1010,"label_y": 1450},
        "safety_recover":    {"x": 1210, "y": 1430, "w": 380, "h": 320,
                              "label_x": 1400,"label_y": 1450},
        "safety_weaknesses": {"x": 1600, "y": 1430, "w": 360, "h": 320,
                              "label_x": 1780,"label_y": 1450},
    },
    # Explicit per-node placements in SVG user-space
    "nodes": {
        # EXTERNAL
        "telegram_api":          {"cx":  180, "cy":   80, "w": 180, "h": 52},
        "openrouter":            {"cx": 1820, "cy":   80, "w": 180, "h": 52},

        # INTERFACE — Связь
        "colab_launcher":        {"cx":  180, "cy":  310, "w": 200, "h": 50},
        "telegram":              {"cx":  460, "cy":  310, "w": 220, "h": 50},
        # INTERFACE — Диспетчеризация
        "queue":                 {"cx":  740, "cy":  280, "w": 130, "h": 40},
        "workers":               {"cx":  900, "cy":  280, "w": 130, "h": 40},
        "events":                {"cx": 1060, "cy":  280, "w": 130, "h": 40},
        "worker_pool":           {"cx":  820, "cy":  350, "w": 160, "h": 36},
        "consciousness_thread":  {"cx": 1060, "cy":  350, "w": 190, "h": 36},
        # INTERFACE — Жизнеобеспечение
        "state":                 {"cx": 1370, "cy":  280, "w": 130, "h": 40},
        "git_ops":                {"cx": 1520, "cy":  280, "w": 130, "h": 40},
        "fs_data":                {"cx": 1680, "cy":  280, "w": 130, "h": 40},
        "docker_chromadb":       {"cx": 1370, "cy":  350, "w": 130, "h": 32},
        "docker_postgres":       {"cx": 1520, "cy":  350, "w": 130, "h": 32},
        "docker_redis":          {"cx": 1680, "cy":  350, "w": 130, "h": 32},

        # BRAIN — Восприятие (col 1)
        "agent":                 {"cx":  565, "cy":  605, "w": 170, "h": 46},
        "context":               {"cx":  565, "cy":  665, "w": 170, "h": 46},
        "memory":                {"cx":  565, "cy":  725, "w": 170, "h": 46},
        "owner_inject":          {"cx":  565, "cy":  785, "w": 170, "h": 46},
        # BRAIN — Мышление (col 2)
        "loop":                  {"cx":  785, "cy":  620, "w": 170, "h": 46},
        "llm":                   {"cx":  785, "cy":  690, "w": 170, "h": 46},
        # BRAIN — Самоконтроль (col 3)
        "inner_critic":          {"cx": 1005, "cy":  605, "w": 170, "h": 46},
        "self_evolution":        {"cx": 1005, "cy":  665, "w": 170, "h": 46},
        "budget":                {"cx": 1005, "cy":  725, "w": 170, "h": 46},
        # BRAIN — Рефлексия (col 4)
        "skill_manager":         {"cx": 1225, "cy":  605, "w": 170, "h": 46},
        "experiment_engine":     {"cx": 1225, "cy":  665, "w": 180, "h": 46},
        "pattern_detector":      {"cx": 1225, "cy":  725, "w": 180, "h": 46},
        # BRAIN — Фоновое сознание (col 5)
        "consciousness":         {"cx": 1445, "cy":  620, "w": 170, "h": 46},
        "strategic_planner":     {"cx": 1445, "cy":  690, "w": 180, "h": 46},

        # TOOLS registry — kept so edges from/to TOOLS still resolve
        "registry":              {"cx": 1770, "cy":  980, "w": 300, "h": 30},

        # MEMORY — Рабочая
        "mem_scratchpad":        {"cx":  150, "cy": 1175, "w": 180, "h": 40},
        # MEMORY — Оперативная (2 rows × 4 cols)
        "log_chat":              {"cx":  345, "cy": 1175, "w": 105, "h": 36},
        "log_events":            {"cx":  465, "cy": 1175, "w": 105, "h": 36},
        "log_supervisor":        {"cx":  585, "cy": 1175, "w": 115, "h": 36},
        "log_tools":             {"cx":  705, "cy": 1175, "w": 105, "h": 36},
        "log_progress":          {"cx":  345, "cy": 1230, "w": 115, "h": 36},
        "state_directives":      {"cx":  475, "cy": 1230, "w": 125, "h": 36},
        "state_budget":          {"cx":  600, "cy": 1230, "w": 115, "h": 36},
        "state_queue":           {"cx":  715, "cy": 1230, "w": 115, "h": 36},
        # MEMORY — Идентичность
        "mem_identity":          {"cx":  900, "cy": 1200, "w": 160, "h": 38},
        "mem_wisdom":            {"cx":  900, "cy": 1260, "w": 160, "h": 38},
        # MEMORY — Знания
        "mem_knowledge":         {"cx": 1085, "cy": 1230, "w": 150, "h": 42},
        # MEMORY — Опыт (2 rows × 2 cols)
        "mem_episodic":          {"cx": 1255, "cy": 1200, "w": 140, "h": 36},
        "chroma_episodes":       {"cx": 1410, "cy": 1200, "w": 150, "h": 36},
        "chroma_skills":         {"cx": 1255, "cy": 1260, "w": 140, "h": 36},
        "chroma_history":        {"cx": 1410, "cy": 1260, "w": 150, "h": 36},
        # MEMORY — Служебная (3 rows × 2 cols)
        "state_main":            {"cx": 1570, "cy": 1190, "w": 125, "h": 32},
        "state_experiments":     {"cx": 1700, "cy": 1190, "w": 140, "h": 32},
        "state_commitments":     {"cx": 1570, "cy": 1230, "w": 140, "h": 32},
        "state_reflected":       {"cx": 1720, "cy": 1230, "w": 140, "h": 32},
        "state_cooldown":        {"cx": 1570, "cy": 1270, "w": 130, "h": 32},
        "state_consciousness":   {"cx": 1720, "cy": 1270, "w": 170, "h": 32},
        # MEMORY — Архив
        "file_task_results":     {"cx": 1895, "cy": 1230, "w": 110, "h": 40},
    },
    "zoom_states": {
        "l0":           {"x": 0,    "y": 0,    "w": 2000, "h": 1780},
        "l1-interface": {"x": 20,   "y": 170,  "w": 1960, "h": 260},
        "l1-brain":     {"x": 430,  "y": 450,  "w": 1130, "h": 590},
        "l1-tools":     {"x": 1570, "y": 460,  "w": 410,  "h": 560},
        "l1-memory":    {"x": 20,   "y": 1060, "w": 1960, "h": 330},
        "l1-safety":    {"x": 20,   "y": 1410, "w": 1960, "h": 360},
    },
    # Lifetime band backgrounds inside MEMORY (decorative)
    "memory_bands": {
        "working":    {"x": 30,   "y": 1095, "w": 230, "h": 270,
                       "label": "Рабочая",        "label_en": "Working",
                       "label_x": 145, "label_y": 1087},
        "short_term": {"x": 270,  "y": 1095, "w": 520, "h": 270,
                       "label": "Оперативная",    "label_en": "Short-term",
                       "label_x": 525, "label_y": 1087},
        "long_term":  {"x": 800,  "y": 1095, "w": 1020,"h": 270,
                       "label": "Долговременная", "label_en": "Long-term",
                       "label_x": 1315,"label_y": 1087},
        "archive":    {"x": 1825, "y": 1095, "w": 140, "h": 270,
                       "label": "Архив",          "label_en": "Archive",
                       "label_x": 1895,"label_y": 1087},
    },
}


# ---------------------------------------------------------------------------
# Phase 1.7 annotations + SAFETY DZ taxonomy
# ---------------------------------------------------------------------------

def _annotate_functional_roles(topology_nodes: List[Dict], tools: List[Dict]) -> None:
    """Attach organ, block_id, and any legacy role fields to each
    topology_node + tool. Uses the BLOCKS tables as source of truth."""
    node_block = {}
    node_organ = {}
    for b in BRAIN_BLOCKS + INTERFACE_BLOCKS + MEMORY_BLOCKS:
        for nid in b.get("nodes", []):
            node_block[nid] = b["id"]
            node_organ[nid] = b["organ"]

    for n in topology_nodes:
        nid = n["id"]
        if nid in node_block:
            n["organ"] = node_organ[nid]
            n["block_id"] = node_block[nid]
        elif nid in EXTERNAL_NODES:
            n["organ"] = "external"
            n["block_id"] = "external"
        elif nid == "registry":
            n["organ"] = "tools"
            n["block_id"] = "tools_meta"
        else:
            # Anything unplaced: default to memory/service so it still
            # shows up somewhere in the panel view.
            n["organ"] = "memory"
            n["block_id"] = "mem_service"

        # Keep a legacy functional_role for Phase 1.6 consumers
        if nid in {"strategic_planner"}:
            n["paused"] = True

        # Phase 1.8: semantic label (role-based, Russian) + EN counterpart
        sem = SEMANTIC_LABELS.get(nid)
        sem_en = SEMANTIC_LABELS_EN.get(nid)
        n["semantic_label"]    = sem    if sem    else n.get("label", nid)
        n["semantic_label_en"] = sem_en if sem_en else n["semantic_label"]

    tool_block = {}
    for tb in TOOLS_BLOCKS:
        for tname in tb["tools"]:
            tool_block[tname] = tb["id"]
    for t in tools:
        t["block_id"] = tool_block.get(t["name"], "tools_read")


def _populate_safety_prevent_counts() -> None:
    """D17: stamp activation counters onto safety_prevent items.

    Reads `events.jsonl` + `supervisor.jsonl` (D1 dual-log compatibility) and
    counts `task_refused_by_guard` / `worker_destructive_blocked` to surface
    how often the destructive-keyword guard has fired. The frontend renders
    `count` as a small chip next to the item title.
    """
    prevent = next(b for b in SAFETY_BLOCKS if b["id"] == "safety_prevent")
    keyword_guard_count = 0
    for log_name, evt_type in (
        ("events.jsonl", "task_refused_by_guard"),
        ("supervisor.jsonl", "worker_destructive_blocked"),
    ):
        log_path = DATA_ROOT / "logs" / log_name
        if not log_path.exists():
            continue
        try:
            with log_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        evt = json.loads(line)
                    except Exception:
                        continue
                    if evt.get("type") == evt_type:
                        keyword_guard_count += 1
        except Exception:
            continue
    for it in prevent.get("items", []):
        ref = str(it.get("ref") or "")
        if ref.startswith("supervisor/workers.py:320-351"):
            it["count"] = keyword_guard_count
            it["count_source"] = "task_refused_by_guard + worker_destructive_blocked"


def _populate_safety_weaknesses(dark_zones: List[Dict]) -> None:
    """Fill the 5th SAFETY block with DZ taxonomy items (keyed to DZ IDs)."""
    weaknesses = next(b for b in SAFETY_BLOCKS if b["id"] == "safety_weaknesses")
    items = []
    dz_by_id = {d["id"]: d for d in dark_zones}
    for (group_ru, group_en, ids) in SAFETY_DZ_GROUPS:
        for dz_id in ids:
            dz = dz_by_id.get(dz_id)
            if not dz:
                continue
            items.append({
                "title":    f"{dz_id} — {dz['title']}",
                "title_en": f"{dz_id} — {dz['title']}",  # DZ title is sourced EN
                "group":    group_ru,
                "group_en": group_en,
                "dz_id":    dz_id,
                "ref":      None,
            })
    weaknesses["items"] = items


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
         ["D14", "D16", "D17", "D25", "D26", "D27"]),
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

    # Phase 1.7 — block-level functional classification
    _annotate_functional_roles(nodes, tools)
    _populate_safety_weaknesses(dark_zones)
    _populate_safety_prevent_counts()

    # Filter typed edges — Phase 1.7 edges are BLOCK-level so we validate
    # against the set of known block IDs (plus node IDs for any legacy
    # edges that still reference specific files).
    all_block_ids = {b["id"] for b in
                     (BRAIN_BLOCKS + INTERFACE_BLOCKS + MEMORY_BLOCKS
                      + TOOLS_BLOCKS + SAFETY_BLOCKS)}
    node_id_set = {n["id"] for n in nodes}
    valid_endpoints = all_block_ids | node_id_set
    typed_edges = [
        e for e in TYPED_EDGES
        if e["source"] in valid_endpoints and e["target"] in valid_endpoints
    ]

    # Hierarchy — still emitted for the Dark-Zones taxonomy used by the
    # existing SAFETY view + side panel cross-links.
    hierarchy = _build_hierarchy(nodes, tools, dark_zones)

    # Phase 1.7 block tables for the frontend
    phase17_blocks = {
        "interface": INTERFACE_BLOCKS,
        "brain":     BRAIN_BLOCKS,
        "tools":     TOOLS_BLOCKS,
        "memory":    MEMORY_BLOCKS,
        "safety":    SAFETY_BLOCKS,
    }

    snapshot = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "git": _git_head(),
            "source_map": str(ARCH_MAP.name),
            "repo": str(REPO_ROOT),
            "schema_version": 2,
            "phase": "1.7",
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
        "typed_edges": typed_edges,
        "layout": LAYOUT,
        "blocks": phase17_blocks,
        "external_nodes": EXTERNAL_NODES,
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
        print(f"  typed_edges: {len(snap['typed_edges'])} (block-level, hand-curated)")
        print(f"  layout: {len(snap['layout']['nodes'])} positioned nodes, "
              f"{len(snap['layout']['blocks'])} blocks")
        blocks = snap["blocks"]
        print(f"  blocks: brain={len(blocks['brain'])} interface={len(blocks['interface'])} "
              f"memory={len(blocks['memory'])} tools={len(blocks['tools'])} "
              f"safety={len(blocks['safety'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
