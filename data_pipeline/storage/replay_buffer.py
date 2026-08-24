import json
import os
import random
from typing import List, Dict, Any

class ExperienceReplayBuffer:
    def __init__(
        self, 
        base_dataset_path: str = "./databases/storage/base_coding_pairs.json",
        buffer_capacity: int = 1000
    ):
        self.base_dataset_path = base_dataset_path
        self.buffer_capacity = buffer_capacity
        self.user_experience_buffer: List[Dict[str, Any]] = []
        self._base_dataset_cache: List[Dict[str, Any]] = None

    def _load_base_dataset(self) -> List[Dict[str, Any]]:
        if self._base_dataset_cache is not None:
            return self._base_dataset_cache

        if not os.path.exists(self.base_dataset_path):
            self._base_dataset_cache = []
            return self._base_dataset_cache

        try:
            with open(self.base_dataset_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    self._base_dataset_cache = data
                elif isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
                    self._base_dataset_cache = data["data"]
                else:
                    self._base_dataset_cache = []
        except (FileNotFoundError, json.JSONDecodeError):
            self._base_dataset_cache = []

        return self._base_dataset_cache

    def add_user_experience(self, instruction: str, action: str, outcome: str):

        entry = {
            "instruction": instruction,
            "action": action,
            "outcome": outcome
        }
        if len(self.user_experience_buffer) >= self.buffer_capacity:
            self.user_experience_buffer.pop(0)
            
        self.user_experience_buffer.append(entry)

    def sample_training_batch(self, batch_size: int = 32) -> List[Dict[str, Any]]:
        base_dataset = self._load_base_dataset()

        user_avail = len(self.user_experience_buffer)
        base_avail = len(base_dataset)

        if user_avail == 0 and base_avail == 0:
            return []

        target_user = min(int(batch_size * 0.20), user_avail)
        target_base = min(batch_size - target_user, base_avail)

        # If base dataset didn't fulfill remaining slot capacity, fill from user buffer if available
        if target_user + target_base < batch_size and user_avail > target_user:
            target_user = min(batch_size - target_base, user_avail)

        sampled_user = random.sample(self.user_experience_buffer, target_user) if target_user > 0 else []
        sampled_base = random.sample(base_dataset, target_base) if target_base > 0 else []

        batch = sampled_base + sampled_user
        random.shuffle(batch)
        
        return batch

# --- Local Verification ---
if __name__ == "__main__":
    buffer = ExperienceReplayBuffer()
    
    # Simulate incoming observer stream entries
    buffer.add_user_experience(
        instruction="Run dev server on port 3000",
        action="npm run dev --port 3000",
        outcome="SUCCESS"
    )
    
    print(f"User buffer items buffered: {len(buffer.user_experience_buffer)}")