"""Static pattern-based defensive layer for run_shell (D16).

Background — 2026-04-20 ChromaDB confabulation incident
--------------------------------------------------------
THAI bypassed every memory tool by invoking
``chromadb.PersistentClient(path="/home/deploy/ouroboros-data/chromadb")``
through ``run_shell``. PersistentClient silently created a fresh local
SQLite at that path (no warning, no error), all collection lookups
returned 0, and THAI reported "memory empty" to the Shareholder. The
real production data lived in the running Docker ChromaDB on
``localhost:8000`` and was untouched. See
``~/ouroboros-data/CHROMADB_MISMATCH_2026-04-21.md``.

Scope of this module
--------------------
This is *not* a sandbox or an allowlist. It is a static pattern matcher
that runs against the parsed ``cmd`` list before ``subprocess.run``.
On a match, ``run_shell`` returns ``SHELL_BLOCKED`` and emits a
``run_shell_blocked`` event — execution never happens.

Patterns are intentionally narrow: each one corresponds to a concrete
failure mode we have already paid for. Adding a new pattern here is a
one-line ``Pattern`` entry plus a matcher fn — that ergonomic is the
whole point of keeping the list in one place.

What this layer cannot catch
----------------------------
- Dangerous code hidden inside a Python script file (we do not read or
  AST-parse files referenced by ``python script.py``).
- Patterns expressed in unusual ways (``getattr(chromadb, "Persistent"
  + "Client")``). The class of attacker we are defending against here
  is THAI itself reaching for the obvious workaround under pressure,
  not a malicious actor crafting evasion.
- Anything in ``claude_code_edit`` — that path runs the Claude CLI,
  not arbitrary shell, and is out of scope for D16.
"""

from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

# Commands that evaluate code or invoke another shell. We only flag
# *language-level* dangerous patterns (PersistentClient, HttpClient with
# remote host) when one of these is at the head of the command — otherwise
# `grep "chromadb.PersistentClient" .` would self-block, which is silly.
_PYTHON_HEADS = {
    "python", "python2", "python3",
    "ipython", "ipython3",
    "uv", "uvx",
    "pytest",  # pytest -c '...' or running an inline test would still execute
}
_SHELL_HEADS = {"bash", "sh", "zsh", "dash", "ksh", "fish"}


def _basename(arg: str) -> str:
    return pathlib.PurePosixPath(arg).name


def _looks_like_code_executor(cmd: List[str]) -> bool:
    """Head of cmd is something that evaluates code we'd want to inspect."""
    if not cmd:
        return False
    head = _basename(cmd[0])
    if head.startswith("python"):
        return True
    return head in (_PYTHON_HEADS | _SHELL_HEADS)


def _joined(cmd: List[str]) -> str:
    return " ".join(cmd)


# --------------------------------------------------------------------------
# Matchers — each returns a short "what matched" string, or None.
# --------------------------------------------------------------------------

_PERSISTENT_CLIENT_RE = re.compile(r"\bPersistentClient\s*\(")


def _match_chromadb_persistent_client(cmd: List[str]) -> Optional[str]:
    if not _looks_like_code_executor(cmd):
        return None
    blob = _joined(cmd)
    if "chromadb" not in blob:
        return None
    if not _PERSISTENT_CLIENT_RE.search(blob):
        return None
    return "chromadb.PersistentClient(...) call"


_HTTP_CLIENT_RE = re.compile(r"\bHttpClient\s*\(")
_HTTP_HOST_RE = re.compile(r"""host\s*=\s*['"]([^'"]+)['"]""")
_LOCALHOST_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _match_chromadb_remote_http_client(cmd: List[str]) -> Optional[str]:
    if not _looks_like_code_executor(cmd):
        return None
    blob = _joined(cmd)
    if "chromadb" not in blob or not _HTTP_CLIENT_RE.search(blob):
        return None
    m = _HTTP_HOST_RE.search(blob)
    if not m:
        # No explicit host — chromadb default is localhost. Allow.
        return None
    host = m.group(1).strip()
    if host in _LOCALHOST_HOSTS:
        return None
    return f"chromadb.HttpClient(host={host!r}) — only localhost is permitted"


# Recursive rm against any of these tokens trips the guard. The `(^|/)…(/|$)`
# anchors are deliberate: we want `memory/` and `/memory` and bare `memory`
# in arg position, but not `src/memory_handler.py` or `_memory`.
_PROTECTED_PATH_RE = re.compile(
    r"(?:^|[\s/])"
    r"(?:"
    r"\.git"               # any .git dir (top-level or nested)
    r"|ouroboros-data"     # the entire data root
    r"|chroma_data"        # docker volume mount name
    r"|chromadb"           # legacy / on-disk chromadb dir
    r"|memory"             # THAI memory tree (we accept some false positives)
    r"|task_results"
    r"|state"              # ouroboros-data/state — only matched as a path component
    r")"
    r"(?:/|$|[\s'\"])"
)

_RECURSIVE_RM_FLAGS_RE = re.compile(
    r"-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*|-[a-zA-Z]*f[a-zA-Z]*r[a-zA-Z]*|--recursive"
)


def _is_recursive_rm_argv(cmd: List[str]) -> bool:
    """Direct ['rm', '-rf', ...] form."""
    if not cmd:
        return False
    if _basename(cmd[0]) != "rm":
        return False
    return any(_RECURSIVE_RM_FLAGS_RE.fullmatch(a) for a in cmd[1:])


def _is_recursive_rm_in_shell(cmd: List[str]) -> bool:
    """rm -rf hidden inside bash -c '...' or similar."""
    if not _looks_like_code_executor(cmd):
        return False
    blob = _joined(cmd)
    return bool(re.search(r"\brm\s+(?:-[a-zA-Z]*\s+)*-?[a-zA-Z]*r[a-zA-Z]*f", blob))


def _match_critical_rm(cmd: List[str]) -> Optional[str]:
    direct = _is_recursive_rm_argv(cmd)
    via_shell = _is_recursive_rm_in_shell(cmd)
    if not (direct or via_shell):
        return None
    blob = _joined(cmd)
    # rm -rf / or rm -rf "" — unconditional block
    if re.search(r"\brm\s+\S*r\S*f\S*\s+/(?:\s|$|'|\")", blob):
        return "recursive rm with root-like target"
    if _PROTECTED_PATH_RE.search(blob):
        return "recursive rm targeting a protected path"
    return None


# .env mutations. We allow reads (cat .env, grep KEY .env) but block any
# command that overwrites or rewrites it.
_ENV_REDIRECT_RE = re.compile(r"""[> ]>\s*['"]?(?:[\w./~-]*/)?\.env\b""")
_ENV_HEREDOC_RE = re.compile(r"""<<\s*['"]?\w+['"]?[\s\S]*?\.env""")


def _arg_targets_env(arg: str) -> bool:
    return arg == ".env" or arg.endswith("/.env")


def _match_env_mutation(cmd: List[str]) -> Optional[str]:
    if not cmd:
        return None
    head = _basename(cmd[0])

    # Direct mutator forms: sed -i .env / tee .env / dd of=.env / mv X .env / cp X .env
    if head == "sed" and "-i" in cmd and any(_arg_targets_env(a) for a in cmd[1:]):
        return "sed -i against .env"
    if head == "tee" and any(_arg_targets_env(a) for a in cmd[1:]):
        return "tee writing into .env"
    if head in ("mv", "cp") and cmd[-1:] and _arg_targets_env(cmd[-1]):
        return f"{head} overwriting .env"
    if head == "dd" and any(a.startswith("of=") and _arg_targets_env(a[3:]) for a in cmd[1:]):
        return "dd of=.env"
    if head == "rm" and any(_arg_targets_env(a) for a in cmd[1:]):
        return "rm against .env"
    if head == "truncate" and any(_arg_targets_env(a) for a in cmd[1:]):
        return "truncate against .env"

    # Shell wrappers — look inside the -c string.
    if _looks_like_code_executor(cmd):
        blob = _joined(cmd)
        if ".env" not in blob:
            return None
        if _ENV_REDIRECT_RE.search(blob):
            return "shell redirect into .env (>, >>)"
        if re.search(r"\bsed\s+-i\b[^|;]*\.env", blob):
            return "sed -i against .env (inside shell -c)"
        if re.search(r"\btee\b[^|;]*\.env", blob):
            return "tee writing into .env (inside shell -c)"
        if re.search(r"\b(?:mv|cp)\b[^|;]*\.env\b", blob):
            return "mv/cp overwriting .env (inside shell -c)"
    return None


# --------------------------------------------------------------------------
# Pattern table — single source of truth.
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Pattern:
    pattern_id: str
    reason: str
    matcher: Callable[[List[str]], Optional[str]]


PATTERNS: Tuple[Pattern, ...] = (
    Pattern(
        pattern_id="chromadb_persistent_client",
        reason=(
            "chromadb.PersistentClient(path=...) creates a fresh local SQLite "
            "instead of connecting to the running Docker ChromaDB. On "
            "2026-04-20 this produced a confabulated 'memory empty' report. "
            "Use the chromadb_stats tool, or chromadb.HttpClient(host="
            "'localhost', port=8000) if a raw client is genuinely needed."
        ),
        matcher=_match_chromadb_persistent_client,
    ),
    Pattern(
        pattern_id="chromadb_remote_http_client",
        reason=(
            "Production ChromaDB lives on localhost:8000 only. A non-localhost "
            "HttpClient host suggests pointing at the wrong instance or "
            "exfiltration; neither is a legitimate run_shell action."
        ),
        matcher=_match_chromadb_remote_http_client,
    ),
    Pattern(
        pattern_id="rm_rf_critical_path",
        reason=(
            "Recursive rm against memory/, chroma_data/, chromadb/, .git/, "
            "task_results/, state/, or the ouroboros-data root would destroy "
            "persistent state with no recovery. Use repo_write/repo_commit "
            "tools for tracked files; for transient cleanup, target a "
            "narrower path."
        ),
        matcher=_match_critical_rm,
    ),
    Pattern(
        pattern_id="env_shell_mutation",
        reason=(
            ".env stores API keys, the OpenRouter budget cap, and the daily "
            "autonomous spending cap. Edits must go through an explicit, "
            "reviewable flow (Shareholder + commit), not a shell redirect, "
            "sed -i, or mv/cp overwrite."
        ),
        matcher=_match_env_mutation,
    ),
)


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

def check_command(cmd: List[str]) -> Optional[Tuple[str, str, str]]:
    """Run all matchers against a parsed cmd list.

    Returns
    -------
    (pattern_id, reason, matched_detail) on the first hit, else None.

    The function is total — a matcher raising is treated as "no match" so a
    bug in one pattern cannot wedge run_shell.
    """
    for p in PATTERNS:
        try:
            detail = p.matcher(cmd)
        except Exception:
            continue
        if detail:
            return p.pattern_id, p.reason, detail
    return None


def pattern_ids() -> Tuple[str, ...]:
    """Stable list of pattern ids — for tests and tooling."""
    return tuple(p.pattern_id for p in PATTERNS)
