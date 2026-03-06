"""
Operations Agent tools — service health checks and operational actions.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
from typing import List

from ouroboros.tools.registry import ToolContext, ToolEntry

REPO_DIR = pathlib.Path(os.environ.get("REPO_DIR", "/home/deploy/ouroboros"))
OPS_SCRIPT = REPO_DIR / "ops" / "check.py"


def _run_ops_check(ctx: ToolContext, service: str = "", format: str = "human") -> str:  # noqa: A002
    """Run operational health check on all services (or a specific one)."""
    cmd = ["python3", str(OPS_SCRIPT), "--format", format]
    if service:
        cmd += ["--service", service]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(REPO_DIR),
        )
        output = result.stdout.strip()
        if result.returncode not in (0, 1):  # 1 = some services down, still valid
            if result.stderr:
                output += f"\n\nSTDERR: {result.stderr[:500]}"
        return output if output else f"[No output, exit code: {result.returncode}]"
    except subprocess.TimeoutExpired:
        return "[ops check timed out after 30s]"
    except Exception as e:
        return f"[ops check error: {e}]"


def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry(
            name="run_ops_check",
            schema={
                "name": "run_ops_check",
                "description": (
                    "Run operational health check on production services. "
                    "Checks systemd status, HTTP health endpoints, disk, and memory. "
                    "Use this instead of manually running shell commands to diagnose service issues. "
                    "For 'service' param use: 'prism', 'vendorlens', 'caddy', or empty for all."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "service": {
                            "type": "string",
                            "description": "Service to check (partial name match). Empty = check all.",
                            "default": "",
                        },
                        "format": {
                            "type": "string",
                            "enum": ["human", "json"],
                            "description": "Output format. 'human' for readable, 'json' for structured.",
                            "default": "human",
                        },
                    },
                    "required": [],
                },
            },
            handler=_run_ops_check,
            timeout_sec=35,
        )
    ]
