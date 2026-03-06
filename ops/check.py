#!/usr/bin/env python3
"""
Operations Agent — Service Health Check

Usage:
    python3 ops/check.py
    python3 ops/check.py --service prism
    python3 ops/check.py --json   # output JSON only (default)

Output: JSON with service statuses, logs tail, and summary.
"""

import argparse
import json
import os
import subprocess
import sys
import datetime
from typing import Dict, Any, List, Optional

SERVICES = {
    "prism-backend": {
        "systemd_unit": "prism-backend",
        "health_url": "http://localhost:8888/health",
        "log_lines": 20,
    },
    "prism-frontend": {
        "systemd_unit": "prism-frontend",
        "health_url": "http://localhost:3001",
        "log_lines": 10,
    },
    "vendorlens-backend": {
        "systemd_unit": "vendorlens-backend",
        "health_url": "http://localhost:8080/health",
        "log_lines": 10,
    },
    "caddy": {
        "systemd_unit": "caddy",
        "health_url": None,
        "log_lines": 5,
    },
}


def check_systemd(unit: str) -> Dict[str, Any]:
    """Check systemd unit status."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", unit],
            capture_output=True, text=True, timeout=5
        )
        active = result.stdout.strip()
        
        # Get more details
        detail = subprocess.run(
            ["systemctl", "show", unit, "--property=ActiveState,SubState,MainPID,ExecMainStartTimestamp"],
            capture_output=True, text=True, timeout=5
        )
        props = {}
        for line in detail.stdout.strip().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                props[k] = v
        
        return {
            "active": active,
            "ok": active == "active",
            "pid": props.get("MainPID", ""),
            "started_at": props.get("ExecMainStartTimestamp", ""),
        }
    except Exception as e:
        return {"active": "error", "ok": False, "error": str(e)}


def check_http(url: str) -> Dict[str, Any]:
    """Check HTTP endpoint health."""
    try:
        import urllib.request
        import urllib.error
        req = urllib.request.urlopen(url, timeout=5)
        return {"status_code": req.status, "ok": req.status < 400}
    except urllib.error.HTTPError as e:
        return {"status_code": e.code, "ok": e.code < 500}
    except Exception as e:
        return {"status_code": None, "ok": False, "error": str(e)[:100]}


def get_logs(unit: str, lines: int) -> List[str]:
    """Get recent logs from journald."""
    try:
        result = subprocess.run(
            ["journalctl", "-u", unit, "-n", str(lines), "--no-pager", "--output=short"],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip().splitlines()[-lines:]
    except Exception as e:
        return [f"[log error: {e}]"]


def check_disk() -> Dict[str, Any]:
    """Check disk usage."""
    try:
        result = subprocess.run(
            ["df", "-h", "/"],
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.strip().splitlines()
        if len(lines) >= 2:
            parts = lines[1].split()
            return {
                "total": parts[1] if len(parts) > 1 else "?",
                "used": parts[2] if len(parts) > 2 else "?",
                "available": parts[3] if len(parts) > 3 else "?",
                "use_pct": parts[4] if len(parts) > 4 else "?",
            }
    except Exception as e:
        return {"error": str(e)}
    return {}


def check_memory() -> Dict[str, Any]:
    """Check memory usage."""
    try:
        result = subprocess.run(
            ["free", "-m"],
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.strip().splitlines()
        if len(lines) >= 2:
            parts = lines[1].split()
            total = int(parts[1]) if len(parts) > 1 else 0
            used = int(parts[2]) if len(parts) > 2 else 0
            available = int(parts[6]) if len(parts) > 6 else (total - used)
            return {
                "total_mb": total,
                "used_mb": used,
                "available_mb": available,
                "use_pct": f"{int(used/total*100)}%" if total > 0 else "?",
            }
    except Exception as e:
        return {"error": str(e)}
    return {}


def run_check(service_filter: Optional[str] = None) -> Dict[str, Any]:
    """Run full health check and return structured result."""
    results = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "services": {},
        "system": {},
        "summary": {"total": 0, "ok": 0, "failed": []},
    }
    
    services_to_check = SERVICES
    if service_filter:
        services_to_check = {k: v for k, v in SERVICES.items() if service_filter.lower() in k.lower()}
    
    for name, config in services_to_check.items():
        svc = {}
        
        # Systemd check
        svc["systemd"] = check_systemd(config["systemd_unit"])
        
        # HTTP check
        if config.get("health_url"):
            svc["http"] = check_http(config["health_url"])
        
        # Logs (only on failure or explicitly requested)
        if not svc["systemd"].get("ok"):
            svc["recent_logs"] = get_logs(config["systemd_unit"], config.get("log_lines", 10))
        
        # Overall status
        svc["status"] = "ok" if svc["systemd"].get("ok") else "failed"
        
        results["services"][name] = svc
        results["summary"]["total"] += 1
        if svc["status"] == "ok":
            results["summary"]["ok"] += 1
        else:
            results["summary"]["failed"].append(name)
    
    # System resources
    results["system"]["disk"] = check_disk()
    results["system"]["memory"] = check_memory()
    
    # Overall health
    results["summary"]["all_ok"] = len(results["summary"]["failed"]) == 0
    
    return results


def format_human(data: Dict[str, Any]) -> str:
    """Format check result for human reading."""
    lines = [f"🔍 Health Check — {data['timestamp'][:19]} UTC", ""]
    
    # Services
    for name, svc in data["services"].items():
        icon = "✅" if svc["status"] == "ok" else "❌"
        lines.append(f"{icon} {name}")
        if svc["status"] != "ok" and "recent_logs" in svc:
            for log_line in svc["recent_logs"][-3:]:
                lines.append(f"   {log_line}")
    
    lines.append("")
    
    # System
    disk = data["system"].get("disk", {})
    mem = data["system"].get("memory", {})
    if disk:
        lines.append(f"💾 Disk: {disk.get('used','?')}/{disk.get('total','?')} ({disk.get('use_pct','?')})")
    if mem:
        lines.append(f"🧠 Memory: {mem.get('used_mb','?')}MB/{mem.get('total_mb','?')}MB ({mem.get('use_pct','?')})")
    
    lines.append("")
    summary = data["summary"]
    if summary["all_ok"]:
        lines.append(f"✅ All {summary['total']} services healthy")
    else:
        lines.append(f"⚠️ {len(summary['failed'])}/{summary['total']} services failed: {', '.join(summary['failed'])}")
    
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Operations Agent — Health Check")
    parser.add_argument("--service", help="Check specific service (partial name match)")
    parser.add_argument("--format", choices=["json", "human"], default="json")
    args = parser.parse_args()
    
    data = run_check(service_filter=args.service)
    
    if args.format == "human":
        print(format_human(data))
    else:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    
    # Exit code: 0 if all ok, 1 if any failed
    sys.exit(0 if data["summary"]["all_ok"] else 1)