"""Execute a scenario in a subprocess + collect its trace."""
from __future__ import annotations

import json
import logging
import os
import pathlib
import shutil
import subprocess
import sys
import uuid
from typing import Any, Dict

log = logging.getLogger(__name__)

# B-O2: the THAI agent depends on `chromadb`, `openai`, `anthropic`, etc.
# These live in ~/.ouroboros-venv. If eval is invoked under a different
# Python (e.g. system /usr/bin/python3), the agent subprocess silently
# loses access to ChromaDB and emits "unreachable" — the bug B-O2
# initially mis-diagnosed as a v1/v2 API mismatch. Use the venv Python
# explicitly when it exists.
def _resolve_agent_python() -> str:
    override = os.environ.get("EVAL_AGENT_PYTHON")
    if override and pathlib.Path(override).exists():
        return override
    venv = pathlib.Path.home() / ".ouroboros-venv" / "bin" / "python"
    if venv.exists():
        return str(venv)
    return sys.executable


def execute_direct(
    scenario_id: str,
    task: Dict[str, Any],
    drive_root: pathlib.Path,
    repo_dir: pathlib.Path,
    chroma_host: str,
    chroma_port: int,
    env_overrides: Dict[str, str],
    timeout_sec: float = 300.0,
) -> Dict[str, Any]:
    """Run agent.handle_task in a fresh subprocess. Returns trace dict."""
    invocation_path = drive_root / f"_invocation_{uuid.uuid4().hex[:6]}.json"
    result_path = drive_root / f"_subprocess_result_{uuid.uuid4().hex[:6]}.json"

    invocation = {
        "drive_root": str(drive_root),
        "repo_dir": str(repo_dir),
        "chroma_host": chroma_host,
        "chroma_port": chroma_port,
        "task": task,
        "result_path": str(result_path),
        "env_overrides": env_overrides or {},
    }
    invocation_path.write_text(json.dumps(invocation), encoding="utf-8")

    # Inherit current env (incl. OPENROUTER_API_KEY) plus PYTHONPATH for repo.
    child_env = os.environ.copy()
    child_env["PYTHONPATH"] = f"{repo_dir}:{child_env.get('PYTHONPATH', '')}"

    agent_python = _resolve_agent_python()
    cmd = [agent_python, "-m", "eval._subprocess_runner", str(invocation_path)]
    log.info("subprocess: %s", " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(repo_dir),
            env=child_env,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as e:
        return {
            "subprocess_status": "timeout",
            "subprocess_returncode": None,
            "stderr": (e.stderr or "")[-4000:] if e.stderr else "",
            "stdout": (e.stdout or "")[-2000:] if e.stdout else "",
            "result": None,
        }

    if result_path.exists():
        result = json.loads(result_path.read_text(encoding="utf-8"))
    else:
        result = None

    # Capture log files written into drive_root for downstream checks.
    captured = _snapshot_logs(drive_root)

    return {
        "subprocess_status": "ok" if proc.returncode == 0 else "agent_error",
        "subprocess_returncode": proc.returncode,
        "stdout": proc.stdout[-2000:],
        "stderr": proc.stderr[-4000:],
        "result": result,
        "captured_logs": captured,
    }


def _snapshot_logs(drive_root: pathlib.Path) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for fname in ("events.jsonl", "supervisor.jsonl", "tools.jsonl", "progress.jsonl"):
        p = drive_root / "logs" / fname
        if p.exists():
            try:
                lines = p.read_text(encoding="utf-8").splitlines()
                out[fname] = [json.loads(line) for line in lines if line.strip()]
            except Exception as e:
                out[fname] = {"_parse_error": str(e)}
        else:
            out[fname] = []
    # task_results
    tr_dir = drive_root / "task_results"
    out["task_results"] = []
    if tr_dir.exists():
        for f in sorted(tr_dir.glob("*.json")):
            try:
                out["task_results"].append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                pass
    return out
