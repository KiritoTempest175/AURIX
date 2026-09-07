"""LUNA General-Purpose Synthetic Data Generator (v0.4.1 - Section 2.3).

Generates high-quality, diverse instruction-response pairs during IDLE/LOCKED states
to instill broad general competence in the student model (70% share of training).

Air-Gapped & File-Isolation Invariant:
- Operates entirely on-device with zero network calls.
- Pure model generation: does NOT read user project files, personal command history,
  or the security File Jail.
- Tagged with source = "synthetic_general".

Fix log (Phase 0.2):
- generate_batch() no longer trusts an optional `power_state` argument. Before, if
  `power_state` was omitted (None), the governor gate was skipped entirely and
  generation proceeded unconditionally -- a fail-OPEN default that could let this
  run during ACTIVE state and compete with the user's own foreground work for
  GPU/CPU, which is exactly what the idle-only design was supposed to prevent.
  It now queries the live governor state itself via `system_state_provider`
  (expected to be `core_engine.SystemState.get_power_state_name()` in production)
  when no explicit state is passed, and fails CLOSED (refuses to generate) if the
  live state can't be determined at all, rather than assuming it's safe to run.
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from typing import Any, Callable, Dict, List, Optional, Union

logger = logging.getLogger("luna.ai_engine.synthetic_generator")

# --- General-Purpose Categories & Seed Curriculum -----------------------------
CATEGORIES = [
    "common_coding_tasks",
    "everyday_troubleshooting",
    "file_system_operations",
    "technical_question_answering",
    "general_instruction_following",
]

# High-quality offline fallback curriculum ensuring broad competence across languages,
# systems, architectures, and debugging patterns without reading any user files.
# This is a SAFETY-NET fallback for when no live model_runner is available (e.g.
# model still loading, or a generation call failed) -- it intentionally is NOT the
# primary source of "diverse" data; that's the model_runner.generate_response() path
# in generate_single_sample() below. If you only ever see samples with these exact
# instructions in your training_pairs table, the live-generation path isn't being
# exercised and should be checked.
OFFLINE_GENERAL_CURRICULUM: List[Dict[str, str]] = [
    {
        "category": "common_coding_tasks",
        "instruction": "Implement an in-memory LRU Cache in Python with O(1) get and put operations.",
        "input": "Capacity constraint: max_size entries. Evict least recently used entry on overflow.",
        "output": (
            "from collections import OrderedDict\n\n"
            "class LRUCache:\n"
            "    def __init__(self, capacity: int):\n"
            "        self.capacity = capacity\n"
            "        self.cache = OrderedDict()\n\n"
            "    def get(self, key: int) -> int:\n"
            "        if key not in self.cache:\n"
            "            return -1\n"
            "        self.cache.move_to_end(key)\n"
            "        return self.cache[key]\n\n"
            "    def put(self, key: int, value: int) -> None:\n"
            "        if key in self.cache:\n"
            "            self.cache.move_to_end(key)\n"
            "        self.cache[key] = value\n"
            "        if len(self.cache) > self.capacity:\n"
            "            self.cache.popitem(last=False)\n"
        ),
    },
    {
        "category": "common_coding_tasks",
        "instruction": "Write a Rust function to safely parse an integer from a string slice without panicking.",
        "input": "Function signature: pub fn safe_parse_i64(input: &str) -> Result<i64, std::num::ParseIntError>",
        "output": (
            "use std::num::ParseIntError;\n\n"
            "pub fn safe_parse_i64(input: &str) -> Result<i64, ParseIntError> {\n"
            "    input.trim().parse::<i64>()\n"
            "}\n"
        ),
    },
    {
        "category": "everyday_troubleshooting",
        "instruction": "Diagnose this Python exception and explain how to prevent it: 'KeyError: 'database''",
        "input": "config = {'host': 'localhost', 'port': 5432}\ndb_name = config['database']",
        "output": (
            "The exception occurs because the key 'database' does not exist in the dictionary.\n"
            "To prevent the crash, either provide a default using `.get('database', 'default_db')`,\n"
            "or check for membership beforehand with `if 'database' in config:`."
        ),
    },
    {
        "category": "everyday_troubleshooting",
        "instruction": "Explain how to diagnose and resolve a 'fatal: refusing to merge unrelated histories' error in Git.",
        "input": "Occurred while pulling from a newly created remote repository.",
        "output": (
            "This happens when two repositories that do not share a common commit history are merged.\n"
            "To resolve it safely if you intend to merge them:\n"
            "git pull origin main --allow-unrelated-histories\n"
            "Ensure you resolve any resulting root conflict markers before committing."
        ),
    },
    {
        "category": "file_system_operations",
        "instruction": "Write a Python utility function to atomically write text to a file using a temporary file and atomic rename.",
        "input": "Target file path and text content.",
        "output": (
            "import os\nimport tempfile\n\n"
            "def atomic_write(filepath: str, content: str) -> None:\n"
            "    dirname = os.path.dirname(os.path.abspath(filepath))\n"
            "    os.makedirs(dirname, exist_ok=True)\n"
            "    with tempfile.NamedTemporaryFile('w', dir=dirname, delete=False, encoding='utf-8') as tf:\n"
            "        tf.write(content)\n"
            "        tf.flush()\n"
            "        os.fsync(tf.fileno())\n"
            "        temp_name = tf.name\n"
            "    os.replace(temp_name, filepath)\n"
        ),
    },
    {
        "category": "file_system_operations",
        "instruction": "How do you securely validate and prevent directory traversal attacks when receiving user-supplied file paths?",
        "input": "Base allowed folder: '/var/data', user input: '../../etc/passwd'",
        "output": (
            "1. Resolve the canonical absolute path of the target directory.\n"
            "2. Resolve the canonical absolute path of the requested relative path.\n"
            "3. Verify that the requested canonical path starts with the base directory path:\n\n"
            "import os\n\n"
            "def is_safe_path(base_dir: str, path: str) -> bool:\n"
            "    real_base = os.path.realpath(base_dir)\n"
            "    real_target = os.path.realpath(os.path.join(base_dir, path))\n"
            "    return os.path.commonpath([real_base]) == os.path.commonpath([real_base, real_target])\n"
        ),
    },
    {
        "category": "technical_question_answering",
        "instruction": "Explain the difference between concurrency and parallelism in computer systems.",
        "input": "Focus on OS threads, event loops, and multi-core CPU execution.",
        "output": (
            "Concurrency is about dealing with lots of things at once (structure), while parallelism is "
            "about doing lots of things at once (simultaneous execution).\n\n"
            "- Concurrency: Interleaving tasks through timeslicing or cooperative async event loops "
            "(can run on a single CPU core).\n"
            "- Parallelism: Physically executing multiple operations simultaneously across multiple hardware "
            "CPU cores or compute units."
        ),
    },
    {
        "category": "general_instruction_following",
        "instruction": "Given the following JSON object representing a server response, transform it into a CSV row.",
        "input": "{\"host\": \"prod-db-01\", \"cpu_percent\": 42.5, \"memory_gb\": 14.2, \"status\": \"nominal\"}",
        "output": (
            "host,cpu_percent,memory_gb,status\n"
            "prod-db-01,42.5,14.2,nominal"
        ),
    },
]

# Power states considered eligible for background generation.
_ELIGIBLE_STATES = frozenset({"IDLE", "LOCKED"})
_ELIGIBLE_STATE_CODES = frozenset({1, 2})  # 1=IDLE, 2=LOCKED per core_engine::governor::power_state


def load_training_weights_from_config(config_path: str = "config/luna.toml") -> Dict[str, float]:
    """Read live_interaction_weight and synthetic_general_weight from config."""
    defaults = {
        "live_interaction_weight": 0.3,
        "synthetic_general_weight": 0.7,
    }
    if not os.path.exists(config_path):
        return defaults

    try:
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore

        with open(config_path, "rb") as f:
            cfg = tomllib.load(f)
            training_sec = cfg.get("training", {})
            if "live_interaction_weight" in training_sec:
                defaults["live_interaction_weight"] = float(training_sec["live_interaction_weight"])
            if "synthetic_general_weight" in training_sec:
                defaults["synthetic_general_weight"] = float(training_sec["synthetic_general_weight"])
    except Exception as e:
        logger.warning(f"Could not parse training weights from {config_path}: {e}")

    return defaults


class GeneratorPowerStateUnknownError(RuntimeError):
    """Raised when generation is attempted with no explicit power_state and no
    working system_state_provider to query the live state from -- i.e. there is
    no safe way to confirm the system is actually IDLE/LOCKED, so generation
    must be refused (fail closed) rather than assumed safe."""
    pass


class GeneralSyntheticDataGenerator:
    """Orchestrates idle-time generation of general-purpose training pairs.

    Adheres strictly to the v0.4.1 design:
    - Never accesses private user files or command histories.
    - Runs only when system is IDLE or LOCKED (rejects ACTIVE state) -- and, as of
      the Phase 0.2 fix, refuses to run at all if it cannot positively confirm
      that (fail closed), rather than defaulting to "permitted" when no state
      was supplied.
    - Labels output with source = 'synthetic_general'.
    """

    def __init__(
        self,
        model_runner: Optional[Any] = None,
        config_path: str = "config/luna.toml",
        output_path: str = "data/synthetic_general.jsonl",
        system_state_provider: Optional[Callable[[], Union[str, int]]] = None,
    ) -> None:
        """
        Args:
            model_runner: Loaded Gemma 4 E4B inference wrapper. If it exposes
                is_loaded / model / is_fallback the same way gemma_e4b.py's
                runner does, live generation is used; otherwise the offline
                fallback curriculum is used.
            config_path: Path to luna.toml.
            output_path: Where generated samples are appended (JSONL).
            system_state_provider: Zero-arg callable returning the CURRENT live
                power state (e.g. `lambda: core_engine.SystemState().get_power_state_name()`).
                Used as the source of truth when generate_batch()/is_generation_permitted()
                are called without an explicit power_state. If not supplied, an
                explicit power_state MUST be passed on every call, or generation
                is refused (fail closed) -- see GeneratorPowerStateUnknownError.
        """
        self.model_runner = model_runner
        self.config_path = config_path
        self.output_path = output_path
        self.system_state_provider = system_state_provider
        self.weights = load_training_weights_from_config(config_path)

    @property
    def live_interaction_weight(self) -> float:
        return self.weights.get("live_interaction_weight", 0.3)

    @property
    def synthetic_general_weight(self) -> float:
        return self.weights.get("synthetic_general_weight", 0.7)

    def is_generation_permitted(self, power_state: Union[int, str]) -> bool:
        """Verify that system is in an eligible idle/locked state for background generation.

        State codes:
          0 / "ACTIVE"     -> False (User working; reserve all compute for UI/inference)
          1 / "IDLE"       -> True  (User inactive >= 300s; background synthetic generation allowed)
          2 / "LOCKED"     -> True  (Workstation locked; full background generation allowed)
          3 / "SUSPENDING" -> False (System shutting down)
        """
        if isinstance(power_state, int):
            return power_state in _ELIGIBLE_STATE_CODES
        state_str = str(power_state).strip().upper()
        return state_str in _ELIGIBLE_STATES

    def _resolve_power_state(self, power_state: Optional[Union[int, str]]) -> Union[int, str]:
        """Resolve the effective power state to gate against.

        FIX (Phase 0.2): this used to be implicit in generate_batch() as
        `if power_state is not None and not is_generation_permitted(power_state)`
        -- meaning an omitted power_state (None) skipped the check entirely and
        let generation proceed unconditionally (fail OPEN). Now:
          1. If an explicit power_state was passed, use it.
          2. Otherwise, if a system_state_provider was configured, query it live.
          3. Otherwise, refuse outright -- there is no safe default here.
        """
        if power_state is not None:
            return power_state

        if self.system_state_provider is not None:
            try:
                live_state = self.system_state_provider()
                logger.debug(f"Resolved live power state via provider: {live_state!r}")
                return live_state
            except Exception as e:
                logger.error(
                    f"system_state_provider raised while resolving live power state: {e}. "
                    f"Refusing to generate (fail closed)."
                )
                raise GeneratorPowerStateUnknownError(
                    f"Could not determine live power state: {e}"
                ) from e

        raise GeneratorPowerStateUnknownError(
            "No power_state was provided and no system_state_provider is configured. "
            "Refusing to generate rather than assuming it's safe to run (fail closed)."
        )

    def generate_single_sample(self, category: Optional[str] = None) -> Dict[str, Any]:
        """Generate a single general-purpose synthetic pair.

        NOTE: this method does not itself gate on power state -- callers should
        go through generate_batch(), which enforces the fail-closed gate before
        ever calling this. generate_single_sample() is exposed directly mainly
        for tests and manual/offline curriculum inspection.
        """
        cat = category or random.choice(CATEGORIES)

        # If model runner is loaded with real weights, generate dynamically
        if (
            self.model_runner is not None
            and hasattr(self.model_runner, "is_loaded")
            and self.model_runner.is_loaded
            and getattr(self.model_runner, "model", None) is not None
            and not getattr(self.model_runner, "is_fallback", False)
        ):
            prompt = (
                f"You are a master software engineering and systems educator. "
                f"Generate a self-contained general coding, troubleshooting, or system instruction "
                f"and its authoritative solution in category: '{cat}'. Do not refer to any specific private codebase. "
                f"Format as: INSTRUCTION: <task>\\nINPUT: <optional context>\\nRESPONSE: <solution>"
            )
            try:
                chat_prompt = self.model_runner.format_chat_prompt(prompt)
                raw_response = self.model_runner.generate_response(chat_prompt, max_new_tokens=400)
                # Parse generated response
                parsed = self._parse_generated_response(raw_response, cat)
                if parsed:
                    return parsed
            except Exception as e:
                logger.warning(f"Dynamic generation failed ({e}), using verified general curriculum.")

        # Fallback to high-quality general curriculum
        matching = [item for item in OFFLINE_GENERAL_CURRICULUM if item["category"] == cat]
        choice = random.choice(matching if matching else OFFLINE_GENERAL_CURRICULUM)

        return {
            "instruction": choice["instruction"],
            "input": choice.get("input", ""),
            "output": choice["output"],
            "source": "synthetic_general",
            "category": cat,
            "timestamp": time.time(),
        }

    def generate_batch(
        self,
        count: int = 5,
        power_state: Optional[Union[int, str]] = None,
        persist: bool = True,
    ) -> List[Dict[str, Any]]:
        """Generate a batch of general-purpose training pairs during IDLE/LOCKED states.

        Args:
            count: Number of samples to generate.
            power_state: Current PowerState (must be IDLE or LOCKED). If omitted,
                the live state is queried via system_state_provider (if configured);
                if neither is available, generation is refused -- see
                GeneratorPowerStateUnknownError. (Phase 0.2 fix: previously an
                omitted power_state skipped the gate entirely.)
            persist: If True, appends samples to output_path.

        Returns:
            List of generated sample dictionaries. Empty list if generation was
            not permitted for the resolved power state.

        Raises:
            GeneratorPowerStateUnknownError: If power_state is omitted and no
                live state could be determined.
        """
        resolved_state = self._resolve_power_state(power_state)

        if not self.is_generation_permitted(resolved_state):
            logger.info(
                f"Skipping synthetic generation: resolved power state is '{resolved_state}' "
                f"(generation only permitted in IDLE or LOCKED)."
            )
            return []

        samples: List[Dict[str, Any]] = []
        for _ in range(count):
            cat = random.choice(CATEGORIES)
            sample = self.generate_single_sample(category=cat)
            samples.append(sample)

        if persist and samples:
            os.makedirs(os.path.dirname(os.path.abspath(self.output_path)), exist_ok=True)
            with open(self.output_path, "a", encoding="utf-8") as f:
                for s in samples:
                    f.write(json.dumps(s) + "\n")
            logger.info(f"Persisted {len(samples)} synthetic_general samples to {self.output_path}")

        return samples

    def _parse_generated_response(self, raw: str, category: str) -> Optional[Dict[str, Any]]:
        """Extract instruction, input, and output blocks from generated text."""
        if "INSTRUCTION:" in raw and "RESPONSE:" in raw:
            try:
                parts = raw.split("RESPONSE:")
                resp = parts[1].strip()
                instr_part = parts[0].split("INSTRUCTION:")[1]
                input_part = ""
                if "INPUT:" in instr_part:
                    instr, input_part = instr_part.split("INPUT:")
                else:
                    instr = instr_part
                return {
                    "instruction": instr.strip(),
                    "input": input_part.strip(),
                    "output": resp,
                    "source": "synthetic_general",
                    "category": category,
                    "timestamp": time.time(),
                }
            except Exception:
                pass
        return None