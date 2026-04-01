#!/usr/bin/env python3
"""Memory stats — shows ChromaDB collections, recent skills, and context window estimate."""

import json
import os
import pathlib
import sys


def main():
    drive_root = pathlib.Path(os.environ.get("OUROBOROS_DRIVE_ROOT", os.path.expanduser("~/ouroboros-data")))
    repo_dir = pathlib.Path(os.environ.get("OUROBOROS_REPO_DIR", os.path.expanduser("~/ouroboros")))

    print("=" * 60)
    print("THAI Memory Stats")
    print("=" * 60)

    # --- ChromaDB collections ---
    print("\n## ChromaDB Collections\n")
    try:
        import chromadb
        client = chromadb.HttpClient(host="localhost", port=8000)
        collections = client.list_collections()
        for col in collections:
            count = col.count()
            print(f"  {col.name}: {count} entries")

        if not collections:
            print("  (no collections found)")

    except ImportError:
        print("  chromadb not installed — pip install chromadb")
    except Exception as e:
        print(f"  ChromaDB error: {e}")

    # --- Recent skills ---
    print("\n## Recent Skills (last 5)\n")
    try:
        ep_dir = drive_root / "memory" / "episodic"
        if ep_dir.exists():
            skills = []
            for ep_file in sorted(ep_dir.glob("*.jsonl"), reverse=True):
                for line in reversed(ep_file.read_text(encoding="utf-8").strip().split("\n")):
                    if not line.strip():
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get("type") == "skill":
                            skills.append(entry)
                            if len(skills) >= 5:
                                break
                    except (json.JSONDecodeError, ValueError):
                        continue
                if len(skills) >= 5:
                    break

            if skills:
                for s in skills:
                    ts = s.get("ts", "")[:10]
                    title = s.get("title", "?")
                    tags = ", ".join(s.get("tags", [])[:5])
                    print(f"  [{ts}] {title}  (tags: {tags})")
            else:
                print("  (no skills found)")
        else:
            print("  (episodic dir not found)")
    except Exception as e:
        print(f"  Error reading skills: {e}")

    # --- Context window estimate ---
    print("\n## Context Window Estimate\n")
    files_to_check = {
        "SYSTEM.md": repo_dir / "prompts" / "SYSTEM.md",
        "BIBLE.md": repo_dir / "BIBLE.md",
        "identity.md": drive_root / "memory" / "identity.md",
        "scratchpad.md": drive_root / "memory" / "scratchpad.md",
        "wisdom.md": drive_root / "memory" / "wisdom.md",
        "dialogue_summary.md": drive_root / "memory" / "dialogue_summary.md",
        "knowledge/_index.md": drive_root / "memory" / "knowledge" / "_index.md",
        "state.json": drive_root / "state" / "state.json",
    }

    total_chars = 0
    total_tokens = 0
    for name, path in files_to_check.items():
        if path.exists():
            size = path.stat().st_size
            tokens_est = size // 4
            total_chars += size
            total_tokens += tokens_est
            print(f"  {name}: {size:,} chars (~{tokens_est:,} tokens)")
        else:
            print(f"  {name}: (not found)")

    print(f"\n  TOTAL: {total_chars:,} chars (~{total_tokens:,} tokens)")
    print(f"  (excludes dynamic sections: recent chat/progress/tools/events)")

    # --- Scratchpad size warning ---
    sp = drive_root / "memory" / "scratchpad.md"
    if sp.exists() and sp.stat().st_size > 8000:
        print(f"\n  ⚠️  Scratchpad is {sp.stat().st_size:,} chars — consolidation will trigger on next consciousness cycle")

    print()


if __name__ == "__main__":
    main()
