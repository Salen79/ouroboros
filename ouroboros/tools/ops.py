"""
Operations Agent — internal functions for health checks and service management.
These are called both by background consciousness (deterministic) and
exposed as LLM tools via get_tools().
"""
from __future__ import annotations

import subprocess
import time
from typing import Any, Dict, List

from ouroboros.utils import utc_now_iso
from ouroboros.tools.registry import ToolContext, ToolEntry


# ---------------------------------------------------------------------------
# Internal (non-tool) functions — used by consciousness directly
# ---------------------------------------------------------------------------

def run_ops_check_internal(service: str = "") -> Dict[str, Any]:
    """
    Run health check on production services.
    Returns structured dict with service statuses.
    """
    result: Dict[str, Any] = {
        "ts": utc_now_iso(),
        "services": {},
        "disk_pct": None,
        "mem_pct": None,
        "summary": "",
    }

    # Service map: short name -> systemd unit
    service_map = {
        "prism-backend": "prism-backend",
        "prism-frontend": "prism-frontend",
        "vendorlens-backend": "vendorlens-backend",
        "caddy": "caddy",
    }

    # Filter if specific service requested
    if service:
        service_map = {
            k: v for k, v in service_map.items()
            if service.lower() in k.lower()
        }

    # Check each service via systemctl
    for svc_name, unit in service_map.items():
        try:
            r = subprocess.run(
                ["systemctl", "is-active", unit],
                capture_output=True, text=True, timeout=5
            )
            status = r.stdout.strip()
            is_active = status == "active"
            result["services"][svc_name] = {
                "status": "up" if is_active else "down",
                "systemctl": status,
            }
        except Exception as e:
            result["services"][svc_name] = {
                "status": "unknown",
                "error": str(e),
            }

    # Disk usage
    try:
        r = subprocess.run(
            ["df", "-h", "--output=pcent", "/"],
            capture_output=True, text=True, timeout=5
        )
        lines = r.stdout.strip().split("\n")
        if len(lines) >= 2:
            pct_str = lines[1].strip().rstrip("%")
            result["disk_pct"] = int(pct_str)
    except Exception:
        pass

    # Memory usage
    try:
        r = subprocess.run(
            ["free", "-m"],
            capture_output=True, text=True, timeout=5
        )
        lines = r.stdout.strip().split("\n")
        if len(lines) >= 2:
            parts = lines[1].split()
            if len(parts) >= 3:
                total = int(parts[1])
                used = int(parts[2])
                if total > 0:
                    result["mem_pct"] = round(used / total * 100)
    except Exception:
        pass

    # Build summary
    down = [n for n, i in result["services"].items()
            if isinstance(i, dict) and i.get("status") == "down"]
    up = [n for n, i in result["services"].items()
          if isinstance(i, dict) and i.get("status") == "up"]

    parts = []
    if up:
        parts.append(f"✅ {len(up)} up")
    if down:
        parts.append(f"❌ {len(down)} down: {', '.join(down)}")
    if result["disk_pct"] is not None:
        parts.append(f"💾 disk {result['disk_pct']}%")
    if result["mem_pct"] is not None:
        parts.append(f"🧠 mem {result['mem_pct']}%")

    result["summary"] = " | ".join(parts)
    return result


def restart_service_internal(service: str) -> Dict[str, Any]:
    """Restart a systemd service. Returns success/failure."""
    # Build unit name
    unit = service
    if not service.endswith(".service") and not service.endswith("-backend") and \
       not service.endswith("-frontend") and service not in ("caddy",):
        # Try to resolve short names
        name_map = {
            "prism": "prism-backend",
            "vendorlens": "vendorlens-backend",
        }
        unit = name_map.get(service.lower(), service)

    try:
        r = subprocess.run(
            ["systemctl", "restart", unit],
            capture_output=True, text=True, timeout=30
        )
        # Wait a moment and check if it came up
        time.sleep(3)
        check = subprocess.run(
            ["systemctl", "is-active", unit],
            capture_output=True, text=True, timeout=5
        )
        success = check.stdout.strip() == "active"
        return {
            "success": success,
            "unit": unit,
            "status_after": check.stdout.strip(),
            "stderr": r.stderr[:500] if r.stderr else "",
        }
    except Exception as e:
        return {"success": False, "unit": unit, "error": str(e)}


# ---------------------------------------------------------------------------
# LLM Tool wrappers — these are exposed via get_tools()
# ---------------------------------------------------------------------------

def _run_ops_check(ctx: ToolContext, service: str = "", format: str = "human") -> str:  # noqa: A002
    """
    Run operational health check on production services.
    Checks systemd status, disk, and memory.

    Args:
        service: Service to check (partial name match). Empty = check all.
        format: 'human' for readable text, 'json' for structured data.
    """
    result = run_ops_check_internal(service)

    if format == "json":
        import json
        return json.dumps(result, indent=2)

    # Human-readable format
    lines = [f"## Ops Check — {result['ts']}", ""]

    for svc, info in result["services"].items():
        if isinstance(info, dict):
            icon = "✅" if info.get("status") == "up" else "❌"
            lines.append(f"{icon} **{svc}**: {info.get('systemctl', info.get('status', '?'))}")

    lines.append("")
    if result["disk_pct"] is not None:
        disk_icon = "⚠️" if result["disk_pct"] > 85 else "💾"
        lines.append(f"{disk_icon} Disk: {result['disk_pct']}%")
    if result["mem_pct"] is not None:
        mem_icon = "⚠️" if result["mem_pct"] > 85 else "🧠"
        lines.append(f"{mem_icon} Memory: {result['mem_pct']}%")

    lines.append("")
    lines.append(f"Summary: {result['summary']}")

    return "\n".join(lines)


def _restart_service(ctx: ToolContext, service: str) -> str:
    """
    Restart a production systemd service.

    Args:
        service: Service name. Accepts short names: 'prism', 'vendorlens', 'caddy', etc.
    """
    result = restart_service_internal(service)

    if result.get("success"):
        return f"✅ Service '{result['unit']}' restarted successfully (status: {result.get('status_after', 'active')})"
    else:
        msg = f"❌ Failed to restart '{result['unit']}'"
        if result.get("error"):
            msg += f": {result['error']}"
        if result.get("stderr"):
            msg += f"\nStderr: {result['stderr']}"
        return msg


def _read_service_logs(ctx: ToolContext, service: str, lines: int = 50) -> str:
    """
    Read recent logs from a production systemd service.

    Args:
        service: Service name. Accepts short names: 'prism', 'vendorlens', 'caddy', etc.
        lines: Number of log lines to return (default: 50, max: 500).
    """
    # Resolve short names
    name_map = {
        "prism": "prism-backend",
        "vendorlens": "vendorlens-backend",
    }
    unit = name_map.get(service.lower(), service)
    lines = min(int(lines), 500)

    try:
        r = subprocess.run(
            ["journalctl", "-u", unit, f"-n{lines}", "--no-pager"],
            capture_output=True, text=True, timeout=10
        )
        output = r.stdout or r.stderr
        if not output.strip():
            return f"No logs found for service '{unit}'"
        return f"## Logs: {unit} (last {lines} lines)\n\n{output}"
    except Exception as e:
        return f"Error reading logs for '{unit}': {e}"


def get_tools() -> List[ToolEntry]:
    """Return tool definitions for auto-discovery by the registry."""
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
