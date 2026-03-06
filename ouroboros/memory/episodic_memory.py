from datetime import datetime
import json
import os
from typing import List, Dict, Any, Optional

# Removed `drive_write` import. The drive module/functions are not available and cause ModuleNotFoundError.
# Saving for EpisodicMemory will be a no-op until drive functions are available and implemented correctly.

# Define the path for storing episodic memories in Drive
# Memories will be stored daily for better organization
EPISODIC_MEMORY_BASE_DIR = "memory/episodic"

class EpisodicMemory:
    def __init__(self, base_dir: str = EPISODIC_MEMORY_BASE_DIR):
        self.base_dir = base_dir
        self.current_day_file = self._get_daily_filename()
        # Load memories. Since drive_read is unavailable, this will always return an empty list.
        # This ensures the class can be initialized without errors.
        self.memories = self._load_memories()

    def _get_daily_filename(self) -> str:
        """Generates the filename for the current day's memory log."""
        today = datetime.now().strftime("%Y-%m-%d")
        return os.path.join(self.base_dir, f"{today}.jsonl")

    def _load_memories(self) -> List[Dict[str, Any]]:
        """
        Loads memories from the current day's file. 
        Since drive_read is unavailable, this function will always return an empty list.
        """
        print(f"INFO: _load_memories called. drive_read is unavailable, returning empty list. Attempted path: {self.current_day_file}")
        return []

    def _save_memories(self) -> None:
        """
        Saves the current list of memories.
        This is a no-op because drive_write is unavailable.
        """
        print(f"INFO: _save_memories called. drive_write is unavailable, cannot save memories to {self.current_day_file}. Content would have been: {json.dumps([json.dumps(mem) for mem in self.memories])}")
        # No-op: Cannot save memories as drive_write is unavailable.

    def add_memory(self, event_type: str, content: Dict[str, Any], significance: float = 0.5, context: Optional[Dict[str, Any]] = None) -> None:
        """
        Adds a new memory entry to the Episodic Memory.
        Storage will be in-memory only until drive functions are available.
        
        Args:
            event_type: A string categorizing the event (e.g., "task_start", "tool_error", "dialogue_turn").
            content: The main data/payload of the memory.
            significance: A score (0.0 to 1.0) indicating how important this memory is. Higher is more significant.
            context: Optional dictionary providing additional context (e.g., task_id, parent_task_id, user_id, model_used).
        """
        today_str = datetime.now().strftime("%Y-%m-%d")
        # Dynamically determine the current day's filename and load memories if the day has changed
        current_day_str = self.current_day_file.split('/')[-1].split('.')[0] if self.current_day_file else ""

        if today_str != current_day_str:
            self.current_day_file = self._get_daily_filename()
            # _load_memories will return empty list as drive_read is not available.
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
        self._save_memories() # This will now be a no-op.

    def search_memories(self, query: Dict[str, Any], limit: int = 10) -> List[Dict[str, Any]]:
        """
        Searches memories currently loaded in memory.
        Does not persist across restarts without drive_read implementation.
        """
        results = []
        for mem in reversed(self.memories): # Search from most recent
            match = True
            for key, value in query.items():
                current_mem_value = mem
                query_value = value
                
                keys = key.split('.')
                for k in keys:
                    if isinstance(current_mem_value, dict) and k in current_mem_value:
                        current_mem_value = current_mem_value[k]
                    else:
                        match = False
                        break
                
                if not match:
                    break

                if current_mem_value != query_value:
                    match = False
                    break
            
            if match:
                results.append(mem)
                if len(results) >= limit:
                    break
        return results

    def get_recent_memories(self, count: int = 5) -> List[Dict[str, Any]]:
        """Returns the most recent memories currently loaded in memory."""
        return self.memories[-count:]
