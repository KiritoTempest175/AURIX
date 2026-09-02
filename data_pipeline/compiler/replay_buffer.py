import json
import logging
import os
import random
from typing import Any, Dict, List, Optional

logger = logging.getLogger("luna.data_pipeline.replay_buffer")


def _read_weights_from_config(config_path: str) -> tuple[float, float]:
    """Read live_interaction_weight and synthetic_general_weight from TOML config."""
    live_w = 0.3
    gen_w = 0.7
    if not os.path.exists(config_path):
        return live_w, gen_w

    try:
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore

        with open(config_path, "rb") as f:
            cfg = tomllib.load(f)
            t_sec = cfg.get("training", {})
            if "live_interaction_weight" in t_sec:
                live_w = float(t_sec["live_interaction_weight"])
            if "synthetic_general_weight" in t_sec:
                gen_w = float(t_sec["synthetic_general_weight"])
    except Exception as e:
        logger.warning(f"Failed to read training weights from {config_path}: {e}")

    return live_w, gen_w


class ExperienceReplayBuffer:
    """Experience replay buffer balancing live user interactions with general-purpose synthetic data.

    v0.4.1 Configuration:
      - live_interaction_weight = 0.3 (30% share: real user usage telemetry)
      - synthetic_general_weight = 0.7 (70% share: general competence)
    """

    def __init__(
        self,
        base_dataset_path: str = "./databases/storage/base_coding_pairs.json",
        synthetic_general_path: str = "./data/synthetic_general.jsonl",
        buffer_capacity: int = 1000,
        config_path: str = "config/luna.toml",
        live_interaction_weight: Optional[float] = None,
        synthetic_general_weight: Optional[float] = None,
    ):
        self.base_dataset_path = base_dataset_path
        self.synthetic_general_path = synthetic_general_path
        self.buffer_capacity = buffer_capacity
        self.config_path = config_path

        # Resolve weights from config if not explicitly passed
        cfg_live, cfg_gen = _read_weights_from_config(config_path)
        self.live_interaction_weight = live_interaction_weight if live_interaction_weight is not None else cfg_live
        self.synthetic_general_weight = synthetic_general_weight if synthetic_general_weight is not None else cfg_gen

        self.user_experience_buffer: List[Dict[str, Any]] = []
        self.synthetic_buffer: List[Dict[str, Any]] = []
        self._base_dataset_cache: Optional[List[Dict[str, Any]]] = None

    def _load_base_dataset(self) -> List[Dict[str, Any]]:
        """Load foundational/synthetic general dataset from storage and cache."""
        if self._base_dataset_cache is not None:
            return self._base_dataset_cache

        records: List[Dict[str, Any]] = []

        # 1. Load from base_dataset_path if available
        if os.path.exists(self.base_dataset_path):
            try:
                with open(self.base_dataset_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        records.extend(data)
                    elif isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
                        records.extend(data["data"])
            except (FileNotFoundError, json.JSONDecodeError):
                pass

        # 2. Load from synthetic_general_path if available
        if os.path.exists(self.synthetic_general_path):
            try:
                with open(self.synthetic_general_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                item = json.loads(line)
                                records.append(item)
                            except json.JSONDecodeError:
                                pass
            except Exception:
                pass

        # 3. Incorporate in-memory synthetic buffer
        if self.synthetic_buffer:
            records.extend(self.synthetic_buffer)

        # Ensure all general records carry source = 'synthetic_general'
        for rec in records:
            if "source" not in rec:
                rec["source"] = "synthetic_general"

        self._base_dataset_cache = records
        return self._base_dataset_cache

    def add_user_experience(
        self,
        instruction: str,
        action: str,
        outcome: str,
        source: str = "live_interaction",
    ) -> None:
        """Add real interaction trace to the user experience replay buffer."""
        entry = {
            "instruction": instruction,
            "action": action,
            "outcome": outcome,
            "source": source,
        }
        if len(self.user_experience_buffer) >= self.buffer_capacity:
            self.user_experience_buffer.pop(0)

        self.user_experience_buffer.append(entry)

    def add_synthetic_general_experience(
        self,
        instruction: str,
        output: str,
        input: str = "",
        category: str = "common_coding_tasks",
    ) -> None:
        """Add a general-purpose synthetic example to the buffer."""
        entry = {
            "instruction": instruction,
            "input": input,
            "output": output,
            "source": "synthetic_general",
            "category": category,
        }
        self.synthetic_buffer.append(entry)
        # Invalidate cache so newly added synthetic items are included
        self._base_dataset_cache = None

    def sample_training_batch(self, batch_size: int = 32) -> List[Dict[str, Any]]:
        """Sample a training batch balanced by configured live vs synthetic weights.

        Target distribution:
          live_interaction_weight (e.g. 30%)
          synthetic_general_weight (e.g. 70%)
        """
        base_dataset = self._load_base_dataset()

        user_avail = len(self.user_experience_buffer)
        base_avail = len(base_dataset)

        if user_avail == 0 and base_avail == 0:
            return []

        # Calculate target counts based on rebalanced weights
        target_user = min(int(round(batch_size * self.live_interaction_weight)), user_avail)
        target_base = min(batch_size - target_user, base_avail)

        # Backfill from whichever pool has capacity if one pool cannot meet target
        if target_user + target_base < batch_size:
            if base_avail > target_base:
                target_base = min(batch_size - target_user, base_avail)
            elif user_avail > target_user:
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
        outcome="SUCCESS",
    )

    buffer.add_synthetic_general_experience(
        instruction="Explain Rust ownership",
        output="Each value in Rust has an owner...",
    )

    print(f"User buffer items buffered: {len(buffer.user_experience_buffer)}")
    print(f"Weights: live={buffer.live_interaction_weight}, synthetic={buffer.synthetic_general_weight}")
    batch = buffer.sample_training_batch(batch_size=2)
    print(f"Sampled batch size: {len(batch)}, sources: {[item.get('source') for item in batch]}")