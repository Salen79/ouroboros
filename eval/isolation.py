"""Isolation primitives: temp DRIVE_ROOT, ChromaDB container, env handling.

Per Phase A design:
- O1: dedicated Docker ChromaDB container per run (alt port 8765).
- O2: subprocess-per-scenario (this module is imported by parent runner;
  the agent subprocess sets up its own state via a preamble).
- D29 closure: supervisor.state.init(drive_root) before any state I/O.
"""
from __future__ import annotations

import contextlib
import json
import logging
import pathlib
import shutil
import socket
import subprocess
import tempfile
import time
import uuid
from typing import Dict, Iterator, Optional

log = logging.getLogger(__name__)

EVAL_CHROMADB_IMAGE = "chromadb/chroma:latest"
EVAL_CHROMADB_NAME_PREFIX = "thai-eval-chroma-"
EVAL_CHROMADB_INTERNAL_PORT = 8000


def _free_tcp_port(start: int = 8765, end: int = 8800) -> int:
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"no free port in [{start}, {end})")


@contextlib.contextmanager
def chromadb_container(run_id: str) -> Iterator[Dict[str, object]]:
    """Spin a fresh ChromaDB container; tear it down on exit."""
    port = _free_tcp_port()
    name = f"{EVAL_CHROMADB_NAME_PREFIX}{run_id}"
    log.info("starting eval ChromaDB container %s on port %d", name, port)

    proc = subprocess.run(
        [
            "docker", "run", "-d", "--rm",
            "--name", name,
            "-p", f"127.0.0.1:{port}:{EVAL_CHROMADB_INTERNAL_PORT}",
            EVAL_CHROMADB_IMAGE,
        ],
        capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"docker run failed: {proc.stderr}")
    container_id = proc.stdout.strip()

    try:
        _wait_for_chromadb(port, timeout_sec=30.0)
        yield {"host": "127.0.0.1", "port": port, "container": container_id, "name": name}
    finally:
        log.info("tearing down ChromaDB container %s", name)
        subprocess.run(
            ["docker", "stop", "-t", "5", name],
            capture_output=True, timeout=20,
        )


def _wait_for_chromadb(port: int, timeout_sec: float) -> None:
    deadline = time.time() + timeout_sec
    last_err: Optional[Exception] = None
    import urllib.request
    while time.time() < deadline:
        for path in ("/api/v2/heartbeat", "/api/v1/heartbeat"):
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{port}{path}", timeout=2.0
                )
                return
            except Exception as e:
                last_err = e
        time.sleep(0.5)
    raise RuntimeError(f"ChromaDB did not become ready on :{port}: {last_err}")


@contextlib.contextmanager
def temp_drive_root(scenario_id: str, run_id: str,
                    snapshot_dir: Optional[pathlib.Path] = None) -> Iterator[pathlib.Path]:
    """Allocate temp DRIVE_ROOT, init standard subdirs, hand back path.

    If snapshot_dir is given, copy the relevant trace files into it
    before teardown (closes the eval observability gap that B-O1 hit —
    full per-round events were lost when temp dir was wiped).
    """
    base = pathlib.Path(tempfile.gettempdir()) / f"thai_eval_{run_id}_{scenario_id}_{uuid.uuid4().hex[:6]}"
    drive = base / "drive_root"
    for sub in ("logs", "state", "memory", "memory/knowledge", "memory/episodic",
                "task_results", "archive", "locks"):
        (drive / sub).mkdir(parents=True, exist_ok=True)
    log.info("temp drive_root: %s", drive)
    try:
        yield drive
    finally:
        if snapshot_dir is not None:
            try:
                _snapshot_drive(drive, snapshot_dir)
            except Exception:
                log.warning("snapshot failed", exc_info=True)
        try:
            shutil.rmtree(base, ignore_errors=True)
        except Exception:
            log.warning("failed to remove %s", base, exc_info=True)


def _snapshot_drive(drive: pathlib.Path, dest: pathlib.Path) -> None:
    """Copy trace-relevant subtrees: logs/, task_results/, memory/."""
    dest.mkdir(parents=True, exist_ok=True)
    for sub in ("logs", "task_results", "memory", "state"):
        src = drive / sub
        if src.exists():
            shutil.copytree(src, dest / sub, dirs_exist_ok=True)


def seed_drive(drive_root: pathlib.Path, drive_seed: Dict[str, object],
               fixtures_dir: pathlib.Path) -> None:
    """Write seed files into drive_root.

    drive_seed values:
      - str: literal content
      - dict with 'from_file': path under fixtures_dir, content copied
    """
    for rel, value in drive_seed.items():
        target = drive_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, str):
            target.write_text(value, encoding="utf-8")
        elif isinstance(value, dict) and "from_file" in value:
            src = fixtures_dir / value["from_file"]
            shutil.copyfile(src, target)
        elif isinstance(value, dict):
            target.write_text(json.dumps(value, indent=2), encoding="utf-8")
        else:
            raise ValueError(f"unsupported seed value for {rel}: {type(value).__name__}")


def shallow_clone_repo(repo_dir: pathlib.Path, sha: str, dest: pathlib.Path) -> pathlib.Path:
    """Clone the repo at a pinned SHA into dest. Remote unset to prevent push.

    B-O8: this is the isolation boundary. The eval subprocess runs the
    agent against this clone, so any auto-rescue self-commits or
    `repo_write_commit` calls land here and get torn down with the
    temp dir. The live working tree stays untouched.

    Note: clones the *committed* state. Uncommitted edits in repo_dir
    are intentionally NOT visible to the eval — this is by design
    (eval measures what's actually in git, not in the dev's WIP).
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"file://{repo_dir.resolve()}"
    subprocess.run(
        ["git", "clone", url, str(dest)],
        check=True, capture_output=True, timeout=60,
    )
    subprocess.run(
        ["git", "-C", str(dest), "checkout", sha],
        check=True, capture_output=True, timeout=20,
    )
    subprocess.run(
        ["git", "-C", str(dest), "remote", "remove", "origin"],
        check=True, capture_output=True, timeout=10,
    )
    # Make the clone identifiable in events.jsonl / git logs if anything leaks.
    subprocess.run(
        ["git", "-C", str(dest), "config", "user.name", "eval-sandbox"],
        check=True, capture_output=True, timeout=10,
    )
    subprocess.run(
        ["git", "-C", str(dest), "config", "user.email", "eval-sandbox@localhost"],
        check=True, capture_output=True, timeout=10,
    )
    return dest


def clone_path_for(drive_root: pathlib.Path) -> pathlib.Path:
    """Conventional location: sibling of drive_root inside the temp base.
    Cleaned up automatically when temp_drive_root teardown runs."""
    return drive_root.parent / "repo_clone"
