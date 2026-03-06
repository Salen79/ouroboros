from datetime import datetime
import json
import os
from typing import List, Dict, Any, Optional

# Removed drive_read import as it's not implemented for loading.
# drive_write import is removed; its availability will be checked at runtime.

# Define the path for storing episodic memories in Drive
# Memories will be stored daily for better organization
EPISODIC_MEMORY_BASE_DIR = "memory/episodic"

class EpisodicMemory:
    def __init__(self, base_dir: str = EPISODIC_MEMORY_BASE_DIR):
        self.base_dir = base_dir
        self.current_day_file = self._get_daily_filename()
        # Attempt to load memories, but gracefully handle if loading is not possible (e.g., drive_read not available)
        self.memories = self._load_memories()

    def _get_daily_filename(self) -> str:
        """Generates the filename for the current day's memory log."""
        today = datetime.now().strftime("%Y-%m-%d")
        return os.path.join(self.base_dir, f"{today}.jsonl")

    def _load_memories(self) -> List[Dict[str, Any]]:
        """
        Loads memories from the current day's file. 
        If drive_read is not available or the file is not found, returns an empty list.
        """
        # Since drive_read is not reliably available, and file access might not be
        # immediately functional for loading from Drive, we'll default to an empty list.
        # This ensures the class can be initialized without errors, and saving can still
        # be attempted if drive_write becomes available.
        # A proper implementation would require a working drive_read.
        print(f"INFO: _load_memories called. Due to potential unavailability of drive_read, returning empty list. File path attempted: {self.current_day_file}")
        return []

    def _save_memories(self) -> None:
        """Saves the current list of memories to the daily file in Drive if drive_write is available."""
        content = "\n".join([json.dumps(mem) for mem in self.memories])
        try:
            # Check if drive_write function is available in the global scope before calling it
            if 'drive_write' in globals() and callable(globals()['drive_write']):
                drive_write(path=self.current_day_file, content=content, mode="overwrite")
                print(f"INFO: Memories saved to {self.current_day_file}")
            else:
                print(f"WARNING: drive_write function is not available. Cannot save memories to {self.current_day_file}")
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
        today_str = datetime.now().strftime("%Y-%m-%d")
        file_date_str = self.current_day_file.split('/')[-1].split('.')[0]

        if today_str != file_date_str:
            self.current_day_file = self._get_daily_filename()
            # Attempt to load memories for the new day. If drive_read is unavailable, this will result in an empty list which is handled.
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
        self._save_memories() # Attempt to save, will warn if drive_write is not available

    def search_memories(self, query: Dict[str, Any], limit: int = 10) -> List[Dict[str, Any]]:
        """
        Searches memories based on a query dictionary.
        This is a basic implementation; full semantic search would be more complex.
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
        """Returns the most recent memories."""
        return self.memories[-count:]
