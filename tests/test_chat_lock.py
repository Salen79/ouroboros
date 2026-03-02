"""
Regression test: duplicate message processing (race condition).

Verifies that when two threads try to handle a chat message simultaneously,
only one succeeds. The second must be rejected (not queued, not processed).

This test exists because the bug was missed by unit tests that only tested
single-threaded execution. See: chat.jsonl 2026-03-01, duplicate responses.
"""

import threading
import time

from ouroboros.agent import OuroborosAgent, Env
import pathlib


def _make_agent():
    """Create a minimal agent instance (no LLM calls needed)."""
    env = Env(
        repo_dir=pathlib.Path("/tmp/test-repo"),
        drive_root=pathlib.Path("/tmp/test-drive"),
    )
    # Create required dirs so Memory/ToolRegistry don't crash
    (env.drive_root / "logs").mkdir(parents=True, exist_ok=True)
    (env.drive_root / "memory").mkdir(parents=True, exist_ok=True)
    (env.repo_dir / ".git").mkdir(parents=True, exist_ok=True)

    return OuroborosAgent(env)


def test_chat_lock_rejects_concurrent_access():
    """Two threads acquire _chat_lock — only one wins."""
    agent = _make_agent()

    results = {"acquired": 0, "rejected": 0}
    barrier = threading.Barrier(2)  # both threads start at the same moment

    def try_acquire():
        barrier.wait()  # sync start
        got_lock = agent._chat_lock.acquire(blocking=False)
        if got_lock:
            results["acquired"] += 1
            time.sleep(0.1)  # simulate work
            agent._chat_lock.release()
        else:
            results["rejected"] += 1

    t1 = threading.Thread(target=try_acquire)
    t2 = threading.Thread(target=try_acquire)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert results["acquired"] == 1, f"Expected 1 acquired, got {results['acquired']}"
    assert results["rejected"] == 1, f"Expected 1 rejected, got {results['rejected']}"


def test_chat_lock_releases_after_exception():
    """Lock must release even if handler crashes — no deadlock."""
    agent = _make_agent()

    # Simulate: first call crashes
    got = agent._chat_lock.acquire(blocking=False)
    assert got is True
    try:
        raise RuntimeError("simulated crash in handle_chat_direct")
    except RuntimeError:
        pass
    finally:
        agent._chat_lock.release()

    # Lock must be available again
    got_again = agent._chat_lock.acquire(blocking=False)
    assert got_again is True, "Lock stuck after exception — deadlock risk!"
    agent._chat_lock.release()


def test_chat_lock_status_check_non_blocking():
    """locked() check for /status must not block or acquire."""
    agent = _make_agent()

    # Lock is free
    assert agent._chat_lock.locked() is False

    # Lock is held
    agent._chat_lock.acquire()
    assert agent._chat_lock.locked() is True

    # locked() did not consume the lock
    assert agent._chat_lock.locked() is True  # still held
    agent._chat_lock.release()


if __name__ == "__main__":
    test_chat_lock_rejects_concurrent_access()
    print("✅ test_chat_lock_rejects_concurrent_access passed")

    test_chat_lock_releases_after_exception()
    print("✅ test_chat_lock_releases_after_exception passed")

    test_chat_lock_status_check_non_blocking()
    print("✅ test_chat_lock_status_check_non_blocking passed")

    print("\nAll concurrency tests passed.")
