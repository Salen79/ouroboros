from datetime import datetime
import json
import os
from typing import List, Dict, Any, Optional

from ouroboros.tools.drive import drive_write # drive_read is not yet implemented for loading

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
            # NOTE: drive_read is not yet implemented. This will raise FileNotFoundError.
            # In a real scenario, this would be replaced by proper drive_read logic.
            # For now, we'll handle FileNotFoundError as the expected outcome for a new day/file.
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
