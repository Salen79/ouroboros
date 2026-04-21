"""R5 — chromadb_stats tool: unit tests + mock ChromaDB client.

Regression test for the 2026-04-20 incident where THAI bypassed its own memory
tools and ran ``chromadb.PersistentClient(path='/home/deploy/ouroboros-data/chromadb')``
via run_shell, silently creating an empty local SQLite and reporting "all
collections missing" to the owner. See
``~/ouroboros-data/CHROMADB_MISMATCH_2026-04-21.md``.

These tests cover the ``chromadb_stats`` handler in its unit form — every mock
matches the real ``chromadb.HttpClient.get_collection().get()`` return shape
(dict with ``ids`` / ``metadatas`` / ``documents`` / etc.) verified against a
live client before writing them.
"""
from unittest.mock import MagicMock, patch

from ouroboros.tools.semantic_memory import (
    _latest_ts_from_metadatas,
    _tool_chromadb_stats,
)


def _make_collection(count: int, metadatas: list):
    """Build a MagicMock that matches chromadb.api.models.Collection.

    Real shape verified via a live HttpClient:
      col.count() -> int
      col.get(limit=N, include=['metadatas']) -> {
          'ids': [...], 'embeddings': [...], 'metadatas': [...],
          'documents': [...], 'data': [...], 'uris': [...], 'included': [...]
      }
    """
    col = MagicMock()
    col.count.return_value = count
    col.get.return_value = {
        "ids": [f"id_{i}" for i in range(len(metadatas))],
        "embeddings": None,
        "metadatas": metadatas,
        "documents": [f"doc_{i}" for i in range(len(metadatas))],
        "data": None,
        "uris": None,
        "included": ["metadatas"],
    }
    return col


class _MockClient:
    """Matches chromadb.HttpClient surface that _tool_chromadb_stats touches.

    Missing collections are raised as ValueError('Collection [X] does not exist'),
    verbatim what chromadb returns — observed in tools.jsonl on 2026-04-20T19:46.
    """
    def __init__(self, collections: dict):
        self._collections = collections

    def get_collection(self, name: str):
        if name not in self._collections:
            raise ValueError(f"Collection [{name}] does not exist")
        return self._collections[name]


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

def test_latest_ts_per_record_prefers_ts_over_ts_end_over_date():
    """Within a single record, ts beats ts_end beats date."""
    metas = [
        {"ts": "2026-04-10T00:00:00Z",
         "ts_end": "2026-01-01T00:00:00Z",
         "date": "2025-12-31"},
    ]
    # Only `ts` should be consulted for this record.
    assert _latest_ts_from_metadatas(metas) == "2026-04-10T00:00:00Z"


def test_latest_ts_cross_record_picks_lexicographic_max():
    """Across records with different fields, return the largest ISO string."""
    metas = [
        {"ts": "2026-04-01T10:00:00Z"},        # -> "2026-04-01T10:00:00Z"
        {"ts_end": "2026-04-05T10:00:00Z"},    # -> "2026-04-05T10:00:00Z"
        {"date": "2026-04-07"},                 # -> "2026-04-07"
    ]
    # ISO 8601 lex order: "2026-04-07" > "2026-04-05T10:00:00Z" because
    # the bare date has no 'T' at position 10 (nothing < 'T') so the
    # comparison is decided at position 9: '7' > '5'. Good enough for
    # the "which day was last" question this tool answers.
    assert _latest_ts_from_metadatas(metas) == "2026-04-07"


def test_latest_ts_empty_list():
    assert _latest_ts_from_metadatas([]) == ""


def test_latest_ts_no_timestamp_fields():
    assert _latest_ts_from_metadatas([{"title": "foo"}, {"type": "skill"}]) == ""


def test_latest_ts_ignores_none_entries():
    metas = [None, {"ts": "2026-04-10T12:00:00Z"}, None]
    assert _latest_ts_from_metadatas(metas) == "2026-04-10T12:00:00Z"


def test_chromadb_stats_happy_path():
    """All three collections present with real metadata shapes."""
    client = _MockClient({
        "thai_episodes": _make_collection(
            count=137,
            metadatas=[
                {"ts": "2026-03-06T09:19:00Z", "date": "2026-03-06",
                 "title": "old entry", "type": "milestone"},
                {"ts": "2026-04-07T08:13:28Z", "date": "2026-04-07",
                 "title": "newest", "type": "skill"},
            ],
        ),
        "thai_skills": _make_collection(
            count=25,
            metadatas=[
                {"ts": "2026-04-01T11:48:57Z", "date": "2026-04-01",
                 "title": "SKILL: check-all-services"},
                {"ts": "2026-04-07T13:11:59Z", "date": "2026-04-07",
                 "title": "SKILL: deep-reflection"},
            ],
        ),
        "thai_history": _make_collection(
            count=488,
            metadatas=[
                {"ts_start": "2026-03-06T14:37:13Z", "ts_end": "2026-03-06T15:04:44Z",
                 "date": "2026-03-06", "type": "chat"},
                {"ts_start": "2026-04-12T12:30:00Z", "ts_end": "2026-04-12T13:20:00Z",
                 "date": "2026-04-12", "type": "chat"},
            ],
        ),
    })
    with patch("ouroboros.tools.semantic_memory._get_client", return_value=client):
        out = _tool_chromadb_stats(ctx=None)

    assert "thai_episodes" in out
    assert "137 items" in out
    assert "thai_skills" in out
    assert "25 items" in out
    assert "thai_history" in out
    assert "488 items" in out
    # last-write timestamps from each collection
    assert "2026-04-07T08:13:28Z" in out   # thai_episodes latest ts
    assert "2026-04-07T13:11:59Z" in out   # thai_skills latest ts
    assert "2026-04-12T13:20:00Z" in out   # thai_history latest ts_end
    # totals line
    assert "TOTAL: 650 items" in out
    assert "3/3 expected collections" in out


def test_chromadb_stats_collection_missing():
    """If one collection is missing, it reports MISSING instead of crashing."""
    client = _MockClient({
        "thai_episodes": _make_collection(
            count=10,
            metadatas=[{"ts": "2026-04-10T00:00:00Z"}],
        ),
        "thai_skills": _make_collection(count=0, metadatas=[]),
        # thai_history deliberately absent
    })
    with patch("ouroboros.tools.semantic_memory._get_client", return_value=client):
        out = _tool_chromadb_stats(ctx=None)

    assert "thai_episodes" in out
    assert "10 items" in out
    assert "thai_skills" in out
    assert "thai_history" in out
    assert "MISSING" in out
    assert "Collection [thai_history] does not exist" in out
    assert "2/3 expected collections" in out


def test_chromadb_stats_dead_connection():
    """_get_client returns None -> explicit error, no silent empty report."""
    with patch("ouroboros.tools.semantic_memory._get_client", return_value=None):
        out = _tool_chromadb_stats(ctx=None)

    assert out.startswith("ERROR:")
    assert "localhost:8000" in out
    # Must also warn against the exact workaround that caused the 04-20 bug.
    assert "PersistentClient" in out
    assert "run_shell" in out.lower()


def test_chromadb_stats_empty_collection():
    """count=0 => reports 'no timestamped records' without crashing."""
    client = _MockClient({
        "thai_episodes": _make_collection(count=0, metadatas=[]),
        "thai_skills": _make_collection(count=0, metadatas=[]),
        "thai_history": _make_collection(count=0, metadatas=[]),
    })
    with patch("ouroboros.tools.semantic_memory._get_client", return_value=client):
        out = _tool_chromadb_stats(ctx=None)

    assert "0 items" in out
    assert "no timestamped records" in out
    assert "TOTAL: 0 items" in out


def test_chromadb_stats_is_registered_with_registry():
    """Tool must appear in get_tools() output with the correct schema."""
    from ouroboros.tools.semantic_memory import get_tools
    entries = {e.name: e for e in get_tools()}
    assert "chromadb_stats" in entries
    schema = entries["chromadb_stats"].schema
    assert schema["name"] == "chromadb_stats"
    # Takes no required arguments (self-contained safe-to-call check).
    params = schema["parameters"]
    assert params.get("type") == "object"
    assert params.get("properties") == {}
    assert "required" not in params or params["required"] == []
