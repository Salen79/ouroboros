"""
Semantic Memory tools for THAI — ChromaDB-backed vector search.

Tools:
1. semantic_search — search across all ChromaDB collections
2. semantic_find_skills — search thai_skills collection
3. recall — search thai_history (chat + events)

Requires ChromaDB server on localhost:8000.
Graceful fallback if unavailable.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from ouroboros.tools.registry import ToolContext, ToolEntry

log = logging.getLogger(__name__)

CHROMADB_HOST = "localhost"
CHROMADB_PORT = 8000

COLLECTIONS = ("thai_episodes", "thai_skills", "thai_history")


def _get_client():
    """Get ChromaDB HttpClient. Returns None if unavailable."""
    try:
        import chromadb
        client = chromadb.HttpClient(host=CHROMADB_HOST, port=CHROMADB_PORT)
        client.heartbeat()
        return client
    except Exception as e:
        log.debug("ChromaDB unavailable: %s", e)
        return None


def _query_collection(client, collection_name: str, query: str, max_results: int, where: dict = None):
    """Query a single collection. Returns list of formatted results."""
    try:
        col = client.get_or_create_collection(name=collection_name)
        kwargs = {
            "query_texts": [query],
            "n_results": min(max_results, col.count() or max_results),
        }
        if where:
            kwargs["where"] = where
        if col.count() == 0:
            return []
        results = col.query(**kwargs)
    except Exception as e:
        log.debug("Failed to query %s: %s", collection_name, e)
        return []

    items = []
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]
    ids = results.get("ids", [[]])[0]

    for i, doc in enumerate(docs):
        meta = metas[i] if i < len(metas) else {}
        dist = distances[i] if i < len(distances) else None
        entry_id = ids[i] if i < len(ids) else "?"
        items.append({
            "id": entry_id,
            "text": doc,
            "metadata": meta,
            "distance": dist,
            "collection": collection_name,
        })
    return items


def _format_results(items: list, query: str) -> str:
    """Format search results for display."""
    if not items:
        return f"No results found for '{query}'"

    lines = [f"Found {len(items)} result(s) for '{query}':\n"]
    for i, item in enumerate(items, 1):
        meta = item.get("metadata", {})
        dist = item.get("distance")
        col = item.get("collection", "?")
        date = meta.get("date", meta.get("ts", ""))[:10]
        entry_type = meta.get("type", "")

        header_parts = [f"--- {i}."]
        if date:
            header_parts.append(f"[{date}]")
        if entry_type:
            header_parts.append(f"({entry_type})")
        header_parts.append(f"[{col}]")
        if dist is not None:
            header_parts.append(f"dist={dist:.3f}")
        lines.append(" ".join(header_parts) + " ---")

        title = meta.get("title", "")
        if title:
            lines.append(f"  {title}")

        text = item.get("text", "")
        if text:
            # Truncate long texts
            if len(text) > 500:
                text = text[:500] + "..."
            lines.append(f"  {text}")

        tags = meta.get("tags", "")
        if tags:
            lines.append(f"  Tags: {tags}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def _tool_semantic_search(
    ctx: ToolContext,
    query: str,
    collection: str = "all",
    max_results: int = 5,
    **kwargs,
) -> str:
    """Semantic search across ChromaDB collections."""
    if not query or not query.strip():
        return "query is required"

    client = _get_client()
    if client is None:
        return "ChromaDB unavailable, use memory_search for keyword search"

    max_results = min(max(1, int(max_results)), 20)

    if collection == "all":
        collections_to_search = list(COLLECTIONS)
        per_col = max(2, max_results // len(collections_to_search))
    else:
        collections_to_search = [collection]
        per_col = max_results

    all_items = []
    for col_name in collections_to_search:
        all_items.extend(_query_collection(client, col_name, query, per_col))

    # Sort by distance (lower = better)
    all_items.sort(key=lambda x: x.get("distance", 999))
    all_items = all_items[:max_results]

    return _format_results(all_items, query)


def _tool_semantic_find_skills(
    ctx: ToolContext,
    query: str,
    max_results: int = 3,
    **kwargs,
) -> str:
    """Semantic search for skills in thai_skills collection."""
    if not query or not query.strip():
        return "query is required"

    client = _get_client()
    if client is None:
        return "ChromaDB unavailable, use find_skills for keyword search"

    max_results = min(max(1, int(max_results)), 10)
    items = _query_collection(client, "thai_skills", query, max_results)
    return _format_results(items, query)


def _tool_recall(
    ctx: ToolContext,
    query: str,
    source: str = "all",
    max_results: int = 5,
    **kwargs,
) -> str:
    """Search chat history and events via ChromaDB."""
    if not query or not query.strip():
        return "query is required"

    client = _get_client()
    if client is None:
        return "ChromaDB unavailable, use memory_search for keyword search"

    max_results = min(max(1, int(max_results)), 20)

    where = None
    if source in ("chat", "events"):
        where = {"type": source}

    items = _query_collection(client, "thai_history", query, max_results, where=where)
    return _format_results(items, query)


# ---------------------------------------------------------------------------
# ChromaDB upsert helpers (used by episodic_memory sync + index_history)
# ---------------------------------------------------------------------------

def upsert_episode(entry: dict, client=None) -> bool:
    """Upsert a single episodic memory entry to ChromaDB.
    Returns True on success, False on failure."""
    if client is None:
        client = _get_client()
    if client is None:
        return False

    try:
        ts = entry.get("ts", "")
        title = entry.get("title", "")
        content = entry.get("content", "")
        entry_type = entry.get("type", "insight")
        tags = entry.get("tags", [])
        importance = entry.get("importance", 1)

        doc_text = f"{title}\n{content}"
        doc_id = f"ep_{ts}_{title[:30]}".replace(" ", "_")

        metadata = {
            "ts": ts,
            "date": ts[:10],
            "type": entry_type,
            "title": title[:200],
            "importance": importance,
            "tags": ",".join(tags) if tags else "",
        }

        # Upsert to thai_episodes
        col = client.get_or_create_collection(name="thai_episodes")
        col.upsert(ids=[doc_id], documents=[doc_text], metadatas=[metadata])

        # Also upsert to thai_skills if type is skill
        if entry_type == "skill":
            skills_col = client.get_or_create_collection(name="thai_skills")
            skills_col.upsert(ids=[doc_id], documents=[doc_text], metadatas=[metadata])

        return True
    except Exception as e:
        log.debug("Failed to upsert episode to ChromaDB: %s", e)
        return False


def upsert_history_chunk(doc_id: str, text: str, metadata: dict, client=None) -> bool:
    """Upsert a history chunk (chat or event) to thai_history collection.
    Returns True on success."""
    if client is None:
        client = _get_client()
    if client is None:
        return False

    try:
        col = client.get_or_create_collection(name="thai_history")
        col.upsert(ids=[doc_id], documents=[text], metadatas=[metadata])
        return True
    except Exception as e:
        log.debug("Failed to upsert history chunk to ChromaDB: %s", e)
        return False


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def get_tools() -> List[ToolEntry]:
    """Return tool definitions for semantic memory."""
    return [
        ToolEntry(
            name="semantic_search",
            schema={
                "name": "semantic_search",
                "description": (
                    "Semantic search across ChromaDB memory collections. "
                    "Finds entries by meaning, not just keywords. "
                    "Collections: thai_episodes, thai_skills, thai_history, or 'all'. "
                    "Example: semantic_search('how to deploy vendorlens') "
                    "Falls back gracefully if ChromaDB is down."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Natural language search query"
                        },
                        "collection": {
                            "type": "string",
                            "enum": ["all", "thai_episodes", "thai_skills", "thai_history"],
                            "description": "Which collection to search (default: all)",
                            "default": "all"
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Max results to return (default: 5)",
                            "default": 5
                        }
                    },
                    "required": ["query"]
                },
            },
            handler=_tool_semantic_search,
        ),
        ToolEntry(
            name="semantic_find_skills",
            schema={
                "name": "semantic_find_skills",
                "description": (
                    "Semantic search for learned skills/procedures in ChromaDB. "
                    "Finds skills by meaning — better than keyword match for 'how to' queries. "
                    "Example: semantic_find_skills('restart crashed service') "
                    "Falls back gracefully if ChromaDB is down."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Natural language query describing what skill you need"
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Max results to return (default: 3)",
                            "default": 3
                        }
                    },
                    "required": ["query"]
                },
            },
            handler=_tool_semantic_find_skills,
        ),
        ToolEntry(
            name="recall",
            schema={
                "name": "recall",
                "description": (
                    "Search conversation history and event logs via ChromaDB. "
                    "Use to recall past conversations, task results, and system events. "
                    "Example: recall('what did sergey say about budget') "
                    "source: 'chat' for conversations, 'events' for system events, 'all' for both."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Natural language query about past events or conversations"
                        },
                        "source": {
                            "type": "string",
                            "enum": ["all", "chat", "events"],
                            "description": "Source to search (default: all)",
                            "default": "all"
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Max results to return (default: 5)",
                            "default": 5
                        }
                    },
                    "required": ["query"]
                },
            },
            handler=_tool_recall,
        ),
    ]
