"""Subprocess entry point: runs ONE scenario inside its own Python process.

Invoked by execute.py via:
    python -m eval._subprocess_runner <invocation_json_path>

Reads invocation spec from JSON file (avoids huge argv); writes result
to a sibling JSON file. This is the only place that imports the
production agent — keeps the parent runner light.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time
import traceback


def _patch_chromadb_target(host: str, port: int) -> None:
    """Redirect semantic_memory module-level constants to eval container.

    Per Phase A note: semantic_memory hardcodes localhost:8000. Rather
    than refactor the agent (out of scope), we patch the module-level
    globals BEFORE any agent code imports the tool — same address space,
    same effect, zero production code change.
    """
    import ouroboros.tools.semantic_memory as sm
    sm.CHROMADB_HOST = host
    sm.CHROMADB_PORT = port


def _drain_event_queue(q) -> list:
    out = []
    try:
        while not q.empty():
            out.append(q.get_nowait())
    except Exception:
        pass
    return out


def main() -> int:
    invocation_path = pathlib.Path(sys.argv[1])
    invocation = json.loads(invocation_path.read_text(encoding="utf-8"))

    drive_root = pathlib.Path(invocation["drive_root"])
    repo_dir = pathlib.Path(invocation["repo_dir"])
    chroma_host = invocation["chroma_host"]
    chroma_port = int(invocation["chroma_port"])
    task = invocation["task"]
    result_path = pathlib.Path(invocation["result_path"])

    # Apply env overrides from scenario.
    for k, v in (invocation.get("env_overrides") or {}).items():
        os.environ[k] = str(v)

    # CRITICAL: redirect supervisor.state BEFORE any agent import touches it.
    # Closes D29 leak for eval.
    sys.path.insert(0, str(repo_dir))
    import supervisor.state as state
    state.init(drive_root)
    assert state.STATE_PATH.parent == drive_root / "state", \
        f"D29 isolation broken: STATE_PATH={state.STATE_PATH}"

    # Patch ChromaDB target before importing agent.
    _patch_chromadb_target(chroma_host, chroma_port)

    # Import agent and build instance.
    from ouroboros.agent import make_agent
    import multiprocessing
    event_queue = multiprocessing.Manager().Queue()

    started_at = time.time()
    error: dict | None = None
    events: list = []
    final_text = ""
    usage = {}

    try:
        agent = make_agent(
            repo_dir=str(repo_dir),
            drive_root=str(drive_root),
            event_queue=event_queue,
        )
        result_events = agent.handle_task(task)
        # handle_task returns a list of event dicts (mailbox-style)
        for e in result_events or []:
            events.append(e)
            if e.get("type") == "task_done":
                final_text = e.get("text") or ""
                usage = e.get("usage") or {}
        # Also drain the multiprocessing queue (some events emitted there).
        events.extend(_drain_event_queue(event_queue))
    except Exception as e:
        error = {
            "exception_type": type(e).__name__,
            "message": str(e),
            "traceback": traceback.format_exc(),
        }

    ended_at = time.time()

    result = {
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_sec": ended_at - started_at,
        "events": events,
        "final_text": final_text,
        "usage": usage,
        "error": error,
    }
    result_path.write_text(json.dumps(result, default=str, indent=2), encoding="utf-8")
    return 0 if error is None else 2


if __name__ == "__main__":
    sys.exit(main())
