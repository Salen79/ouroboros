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

# Known services — maps short name to systemd unit name
KNOWN_SERVICES = {
    "prism": "prism-backend",
    "prism-backend": "prism-backend",
    "prism-frontend": "prism-frontend",
    "prism-front": "prism-frontend",
    "vendorlens": "vendorlens-backend",
    "vendorlens-backend": "vendorlens-backend",
    "caddy": "caddy",
}


def _resolve_service(name: str) -> str | None:
    """Resolve a short service name to systemd unit name."""
    name = name.strip().lower()
    return KNOWN_SERVICES.get(name, name if name else None)


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


def _restart_service(ctx: ToolContext, service: str) -> str:
    """Restart a systemd service by name."""
    unit = _resolve_service(service)
    if not unit:
        return f"[restart_service] Unknown service: '{service}'. Known: {', '.join(KNOWN_SERVICES.keys())}"

    try:
        result = subprocess.run(
            ["sudo", "systemctl", "restart", unit],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            # Verify it came back up
            status = subprocess.run(
                ["systemctl", "is-active", unit],
                capture_output=True, text=True, timeout=5,
            )
            active = status.stdout.strip()
            if active == "active":
                return f"✅ {unit} restarted successfully (status: active)"
            else:
                return f"⚠️ {unit} restarted but status is: {active}"
        else:
            err = result.stderr.strip() or result.stdout.strip()
            return f"❌ Failed to restart {unit}: {err[:500]}"
    except subprocess.TimeoutExpired:
        return f"[restart_service] Timed out restarting {unit}"
    except Exception as e:
        return f"[restart_service error: {e}]"


def _read_service_logs(ctx: ToolContext, service: str, lines: int = 50) -> str:
    """Read recent logs from a systemd service."""
    unit = _resolve_service(service)
    if not unit:
        return f"[read_service_logs] Unknown service: '{service}'. Known: {', '.join(KNOWN_SERVICES.keys())}"

    lines = min(max(int(lines), 1), 500)  # clamp 1..500

    try:
        result = subprocess.run(
            ["journalctl", "-u", unit, "-n", str(lines), "--no-pager", "--output=short-iso"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        output = result.stdout.strip()
        if not output:
            return f"[No log output for {unit}]"
        return output
    except subprocess.TimeoutExpired:
        return f"[read_service_logs] Timed out reading logs for {unit}"
    except Exception as e:
        return f"[read_service_logs error: {e}]"


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
        ),
        ToolEntry(
            name="restart_service",
            schema={
                "name": "restart_service",
                "description": (
                    "Restart a production systemd service. Use when a service is down or "
                    "needs a restart after config changes. Always run run_ops_check after "
                    "to verify the service came back up. "
                    "Known services: prism-backend, prism-frontend, vendorlens-backend, caddy."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "service": {
                            "type": "string",
                            "description": "Service name. Accepts short names: 'prism', 'vendorlens', 'caddy', etc.",
                        },
                    },
                    "required": ["service"],
                },
            },
            handler=_restart_service,
            timeout_sec=40,
        ),
        ToolEntry(
            name="read_service_logs",
            schema={
                "name": "read_service_logs",
                "description": (
                    "Read recent logs from a production systemd service. "
                    "Use to diagnose errors, crashes, or unexpected behavior. "
                    "Returns journalctl output with timestamps. "
                    "Known services: prism-backend, prism-frontend, vendorlens-backend, caddy."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "service": {
                            "type": "string",
                            "description": "Service name. Accepts short names: 'prism', 'vendorlens', 'caddy', etc.",
                        },
                        "lines": {
                            "type": "integer",
                            "description": "Number of log lines to return (default: 50, max: 500).",
                            "default": 50,
                        },
                    },
                    "required": ["service"],
                },
            },
            handler=_read_service_logs,
            timeout_sec=20,
        ),
    ]
