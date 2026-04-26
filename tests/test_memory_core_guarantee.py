"""R1 — startup guarantee for identity.md and scratchpad.md.

Regression test for the 2026-04-12 distress spiral: THAI booted and started
asserting identity.md was missing, spent ~2h looping on the same complaint,
and was /panic-stopped at 13:43 UTC. The root cause was that no startup path
guaranteed the memory-core files existed before the first task ran.

These tests cover _ensure_memory_core() on OuroborosAgent:

  (a) files absent           → created with placeholder + restore event emitted
  (b) files present non-empty → untouched + no restore event
  (c) files zero-byte        → restored (treated identically to absent)

See also: ~/ouroboros-data/PRE_RESTART_INVESTIGATION_2026-04-20.md §1.
"""
import json
import pathlib
import shutil
import time

from ouroboros.agent import Env, OuroborosAgent


def _make_agent(tmp_path: pathlib.Path, *, clean: bool = True) -> OuroborosAgent:
    """Mirrors test_chat_lock._make_agent — minimal agent on tmp dirs.

    Agent construction triggers `_log_worker_boot_once` which runs the full
    `_verify_system_state` chain — including `_ensure_memory_core` — at most
    once per process (module-level guard). To give each test a deterministic
    starting state we wipe `memory/` and `logs/events.jsonl` after construction
    when ``clean=True``.
    """
    env = Env(
        repo_dir=tmp_path / "repo",
        drive_root=tmp_path / "drive",
    )
    (env.drive_root / "logs").mkdir(parents=True, exist_ok=True)
    (env.drive_root / "memory").mkdir(parents=True, exist_ok=True)
    (env.repo_dir / ".git").mkdir(parents=True, exist_ok=True)
    agent = OuroborosAgent(env)
    if clean:
        mem = env.drive_root / "memory"
        if mem.exists():
            shutil.rmtree(mem)
        mem.mkdir(parents=True, exist_ok=True)
        events = env.drive_root / "logs" / "events.jsonl"
        if events.exists():
            events.unlink()
    return agent


def _read_restore_events(drive_root: pathlib.Path) -> list:
    path = drive_root / "logs" / "events.jsonl"
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if obj.get("type") == "startup_memory_restore":
            events.append(obj)
    return events


def test_ensure_memory_core_creates_missing_files(tmp_path):
    """(a) Both files absent → created with placeholder, restore event emitted."""
    agent = _make_agent(tmp_path)
    identity = agent.env.drive_path("memory/identity.md")
    scratchpad = agent.env.drive_path("memory/scratchpad.md")
    assert not identity.exists()
    assert not scratchpad.exists()

    status, issues = agent._ensure_memory_core(git_sha="deadbeef")

    assert issues == 0
    assert status["identity_md_ok"] is True
    assert status["scratchpad_md_ok"] is True
    assert set(status["restored"]) == {"identity.md", "scratchpad.md"}
    assert status["ok"] == []

    # Files created, non-empty, contain placeholder markers
    assert identity.exists() and identity.stat().st_size > 0
    assert scratchpad.exists() and scratchpad.stat().st_size > 0
    assert "Identity not yet initialised" in identity.read_text(encoding="utf-8")
    assert "Scratchpad not yet initialised" in scratchpad.read_text(encoding="utf-8")

    # Exactly one startup_memory_restore event with the expected payload
    events = _read_restore_events(agent.env.drive_root)
    assert len(events) == 1
    evt = events[0]
    assert evt["type"] == "startup_memory_restore"
    assert set(evt["restored"]) == {"identity.md", "scratchpad.md"}
    assert evt["ok"] == []
    assert evt["git_sha"] == "deadbeef"
    assert "ts" in evt


def test_ensure_memory_core_leaves_existing_files_untouched(tmp_path):
    """(b) Both files present with real content → not overwritten.

    D15: event is now ALWAYS emitted (not only on restore), so audits can
    distinguish "files were healthy" from "no startup happened".
    """
    agent = _make_agent(tmp_path)
    identity = agent.env.drive_path("memory/identity.md")
    scratchpad = agent.env.drive_path("memory/scratchpad.md")

    real_identity = "# Identity\n\nI am THAI. Real content.\n"
    real_scratchpad = "# Scratchpad\n\nActive task state.\n"
    identity.write_text(real_identity, encoding="utf-8")
    scratchpad.write_text(real_scratchpad, encoding="utf-8")
    mtime_identity_before = identity.stat().st_mtime
    mtime_scratchpad_before = scratchpad.stat().st_mtime

    # Ensure a distinguishable mtime if restore were (wrongly) to happen
    time.sleep(0.01)

    status, issues = agent._ensure_memory_core(git_sha="cafebabe")

    assert issues == 0
    assert status["identity_md_ok"] is True
    assert status["scratchpad_md_ok"] is True
    assert status["restored"] == []
    assert set(status["ok"]) == {"identity.md", "scratchpad.md"}

    # Content and mtime unchanged
    assert identity.read_text(encoding="utf-8") == real_identity
    assert scratchpad.read_text(encoding="utf-8") == real_scratchpad
    assert identity.stat().st_mtime == mtime_identity_before
    assert scratchpad.stat().st_mtime == mtime_scratchpad_before

    # D15: healthy state still emits the event with the "ok" field populated
    events = _read_restore_events(agent.env.drive_root)
    assert len(events) == 1
    assert events[0]["restored"] == []
    assert set(events[0]["ok"]) == {"identity.md", "scratchpad.md"}
    assert events[0]["git_sha"] == "cafebabe"


def test_ensure_memory_core_restores_zero_byte_files(tmp_path):
    """(c) Zero-byte files are treated as missing and restored."""
    agent = _make_agent(tmp_path)
    identity = agent.env.drive_path("memory/identity.md")
    scratchpad = agent.env.drive_path("memory/scratchpad.md")
    identity.write_text("", encoding="utf-8")
    scratchpad.write_text("", encoding="utf-8")
    assert identity.stat().st_size == 0
    assert scratchpad.stat().st_size == 0

    status, issues = agent._ensure_memory_core(git_sha="abc12345")

    assert issues == 0
    assert set(status["restored"]) == {"identity.md", "scratchpad.md"}
    assert identity.stat().st_size > 0
    assert scratchpad.stat().st_size > 0

    events = _read_restore_events(agent.env.drive_root)
    assert len(events) == 1
    assert set(events[0]["restored"]) == {"identity.md", "scratchpad.md"}


def test_ensure_memory_core_partial_restore(tmp_path):
    """Only the missing file is listed in restored; the present one is left alone."""
    agent = _make_agent(tmp_path)
    identity = agent.env.drive_path("memory/identity.md")
    scratchpad = agent.env.drive_path("memory/scratchpad.md")

    real_identity = "# Identity\n\nI am THAI.\n"
    identity.write_text(real_identity, encoding="utf-8")
    # scratchpad intentionally absent

    status, issues = agent._ensure_memory_core(git_sha="sha")

    assert issues == 0
    assert status["restored"] == ["scratchpad.md"]
    assert status["ok"] == ["identity.md"]
    assert identity.read_text(encoding="utf-8") == real_identity
    assert "Scratchpad not yet initialised" in scratchpad.read_text(encoding="utf-8")

    events = _read_restore_events(agent.env.drive_root)
    assert len(events) == 1
    assert events[0]["restored"] == ["scratchpad.md"]
    assert events[0]["ok"] == ["identity.md"]


def test_d15_always_emits_event_even_when_healthy(tmp_path):
    """D15: every call emits exactly one startup_memory_restore.

    Pre-D15 the event was conditional on `restored` being non-empty, so
    audits could not distinguish "boot just rescued" from "boot saw
    healthy files". Now both cases produce a row, differentiated by the
    `ok` and `restored` fields.
    """
    agent = _make_agent(tmp_path)
    identity = agent.env.drive_path("memory/identity.md")
    scratchpad = agent.env.drive_path("memory/scratchpad.md")
    identity.write_text("# Identity\nreal\n", encoding="utf-8")
    scratchpad.write_text("# Scratchpad\nreal\n", encoding="utf-8")

    # First boot — healthy, should emit ok-only event
    agent._ensure_memory_core(git_sha="abc")
    events = _read_restore_events(agent.env.drive_root)
    assert len(events) == 1
    assert events[0]["restored"] == []
    assert set(events[0]["ok"]) == {"identity.md", "scratchpad.md"}

    # Second boot — also healthy, second event appended
    agent._ensure_memory_core(git_sha="def")
    events = _read_restore_events(agent.env.drive_root)
    assert len(events) == 2
    assert events[1]["git_sha"] == "def"
    assert events[1]["restored"] == []


def test_startup_verification_includes_memory_core(tmp_path):
    """_verify_system_state() payload now contains a memory_core entry."""
    agent = _make_agent(tmp_path)
    # Required support files for the other checks so they don't crash loudly.
    (agent.env.drive_root / "state").mkdir(parents=True, exist_ok=True)
    (agent.env.drive_root / "state" / "state.json").write_text("{}", encoding="utf-8")

    agent._verify_system_state(git_sha="testsha")

    events_path = agent.env.drive_path("logs") / "events.jsonl"
    lines = [json.loads(l) for l in events_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    startup_events = [e for e in lines if e.get("type") == "startup_verification"]
    assert len(startup_events) == 1
    checks = startup_events[0]["checks"]
    assert "memory_core" in checks
    assert checks["memory_core"]["identity_md_ok"] is True
    assert checks["memory_core"]["scratchpad_md_ok"] is True
    # Because tmp_path had no files, both were restored
    assert set(checks["memory_core"]["restored"]) == {"identity.md", "scratchpad.md"}
    assert checks["memory_core"]["ok"] == []
