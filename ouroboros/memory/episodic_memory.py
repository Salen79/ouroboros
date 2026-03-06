from datetime import datetime
import json
import os
from typing import List, Dict, Any, Optional

from ouroboros.tools.drive import drive_write, drive_read # Assuming drive_read will be implemented for loading

# Define the path for storing episodic memories in Drive
# Memories will be stored daily for better organization
EPISODIC_MEMORY_BASE_DIR = "memory/episodic"

class EpisodicMemory:
    def __init__(self, base_dir: str = EPISODIC_MEMORY_BASE_DIR):
        self.base_dir = base_dir
        self.current_day_file = self._get_daily_filename()
        self.memories = self._load_memories()

    def _get_daily_filename(self) -> str:
        """Generates the filename for the current day's memory log."""
        today = datetime.now().strftime("%Y-%m-%d")
        return os.path.join(self.base_dir, f"{today}.jsonl")

    def _load_memories(self) -> List[Dict[str, Any]]:
        """Loads memories from the current day's file. If file not found, returns empty list."""
        try:
            content = drive_read(path=self.current_day_file)
            memories = [json.loads(line) for line in content.strip().split('\n') if line]
            return memories
        except FileNotFoundError:
            # If the file doesn't exist, start fresh for the day
            return []
        except Exception as e:
            # Handle other potential errors during file reading
            print(f"Error loading memories from {self.current_day_file}: {e}")
            return []

    def _save_memories(self) -> None:
        """Saves the current list of memories to the daily file in Drive."""
        content = "\n".join([json.dumps(mem) for mem in self.memories])
        try:
            drive_write(path=self.current_day_file, content=content, mode="overwrite")
        except Exception as e:
            print(f"Error saving memories to {self.current_day_file}: {e}")

    def add_memory(self, event_type: str, content: Dict[str, Any], significance: float = 0.5, context: Optional[Dict[str, Any]] = None) -> None:
        """
        Adds a new memory entry to the Episodic Memory.
        
        Args:
            event_type: A string categorizing the event (e.g., "task_start", "tool_error", "dialogue_turn").
            content: The main data/payload of the memory.
            significance: A score (0.0 to 1.0) indicating how important this memory is. Higher is more significant.
            context: Optional dictionary providing additional context (e.g., task_id, parent_task_id, user_id, model_used).
        """
        if datetime.now().strftime("%Y-%m-%d") != self.current_day_file.split('/')[-1].split('.')[0]:
            # If the day has changed, reset to the new file
            self.current_day_file = self._get_daily_filename()
            self.memories = self._load_memories()

        memory_entry = {
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "content": content,
            "significance": significance,
            "context": context or {},
            "thread_id": context.get("thread_id", "") # convenience for single-threaded access
        }
        self.memories.append(memory_entry)
        self._save_memories()

    def search_memories(self, query: Dict[str, Any], limit: int = 10) -> List[Dict[str, Any]]:
        """
        Searches memories based on a query dictionary.
        This is a basic implementation; full semantic search would be more complex.
        """
        results = []
        for mem in reversed(self.memories): # Search from most recent
            match = True
            for key, value in query.items():
                if key not in mem or mem[key] != value:
                    # Simple key-value match. A more advanced search would handle partial matches, regex, etc.
                    match = False
                    break
            if match:
                results.append(mem)
                if len(results) >= limit:
                    break
        return results

    def get_recent_memories(self, count: int = 5) -> List[Dict[str, Any]]:
        """Returns the most recent memories."""
        return self.memories[-count:]

# Example usage (for testing/demonstration, not for production integration)
if __name__ == "__main__":
    # Mocking drive_read and drive_write for local testing
    # In actual execution, these would interact with Google Drive
    MOCK_DRIVE_STORAGE = {}

    def mock_drive_read(path: str):
        if path in MOCK_DRIVE_STORAGE:
            return MOCK_DRIVE_STORAGE[path]
        else:
            raise FileNotFoundError(f"Mock file not found: {path}")

    def mock_drive_write(path: str, content: str, mode: str):
        MOCK_DRIVE_STORAGE[path] = content
        print(f"Mock drive write: {path} ({mode})")

    # Monkey patch the drive functions for this example
    drive_read = mock_drive_read
    drive_write = mock_drive_write

    print("Testing EpisodicMemory...")
    
    # Create an instance
    memory = EpisodicMemory()
    
    # Add some memories
    memory.add_memory(
        event_type="task_start",
        content={"task_id": "abc123", "description": "Finalize architecture spec"},
        context={"thread_id": "thread_x", "task_name": "Memory Arch Spec"}
    )
    memory.add_memory(
        event_type="tool_call",
        content={"tool_name": "drive_write", "args": {"path": "memory/memory_architecture_spec.md"}},
        significance=0.7,
        context={"thread_id": "thread_x", "task_id": "abc123"}
    )
    memory.add_memory(
        event_type="tool_response",
        content={"tool_name": "drive_write", "result": "OK: wrote overwrite memory/memory_architecture_spec.md (5149 chars)"},
        context={"thread_id": "thread_x", "task_id": "abc123"}
    )
    memory.add_memory(
        event_type="dialogue_turn",
        content={"speaker": "user", "text": "What's the plan?"},
        context={"thread_id": "thread_x"},
        significance=0.3
    )
    memory.add_memory(
        event_type="agent_response",
        content={"speaker": "agent", "text": "I'm implementing the memory architecture..."},
        context={"thread_id": "thread_x", "task_name": "Memory Arch Spec"}
    )

    print(f"\nAdded {len(memory.memories)} memories for today.")

    # Retrieve recent memories
    print("\nRecent memories:")
    for mem in memory.get_recent_memories(count=3):
        print(f"- [{mem['timestamp']}] {mem['event_type']} - {mem['content']}")

    # Search memories
    print("\nSearching for 'drive_write' tool calls:")
    search_results = memory.search_memories(query={"tool_name": "drive_write"})
    for mem in search_results:
        print(f"- [{mem['timestamp']}] {mem['event_type']} - {mem['content']}")

    print(f"\nMock drive storage content for {memory.current_day_file}:")
    print(MOCK_DRIVE_STORAGE.get(memory.current_day_file))

    print("\nE2E test finished.")
