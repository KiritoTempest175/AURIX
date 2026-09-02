"""LUNA General-Purpose Synthetic Data Generator (v0.4.1 — §2.3).

Generates high-quality, diverse instruction-response pairs during IDLE/LOCKED states
to instill broad general competence in the student model (70% share of training).

Air-Gapped & File-Isolation Invariant:
- Operates entirely on-device with zero network calls.
- Pure model generation: does NOT read user project files, personal command history,
  or the security File Jail.
- Tagged with source = "synthetic_general".
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from typing import Any, Callable, Dict, List, Optional, Union

logger = logging.getLogger("luna.ai_engine.synthetic_generator")

# ─── General-Purpose Categories & Seed Curriculum ─────────────────────────────
CATEGORIES = [
    "common_coding_tasks",
    "everyday_troubleshooting",
    "file_system_operations",
    "technical_question_answering",
    "general_instruction_following",
]

# High-quality offline fallback curriculum ensuring broad competence across languages,
# systems, architectures, and debugging patterns without reading any user files.
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
    {
        "category": "common_coding_tasks",
        "instruction": "Implement a retry decorator in Python with exponential backoff and jitter.",
        "input": "Parameters: max_retries: int, base_delay: float, exceptions: tuple",
        "output": (
            "import time\nimport random\nfrom functools import wraps\n\n"
            "def retry_with_backoff(max_retries=3, base_delay=1.0, exceptions=(Exception,)):\n"
            "    def decorator(func):\n"
            "        @wraps(func)\n"
            "        def wrapper(*args, **kwargs):\n"
            "            delay = base_delay\n"
            "            for attempt in range(1, max_retries + 1):\n"
            "                try:\n"
            "                    return func(*args, **kwargs)\n"
            "                except exceptions as e:\n"
            "                    if attempt == max_retries:\n"
            "                        raise\n"
            "                    sleep_time = delay * (1 + random.uniform(0, 0.5))\n"
            "                    time.sleep(sleep_time)\n"
            "                    delay *= 2\n"
            "        return wrapper\n"
            "    return decorator\n"
        ),
    },
    {
        "category": "everyday_troubleshooting",
        "instruction": "How do you investigate and fix a 'database connection pool exhausted' error in a high-throughput backend?",
        "input": "Symptoms: HTTP 500 errors after sustained traffic bursts; PostgreSQL active connection count hits max_connections.",
        "output": (
            "1. Audit connection lifecycle: ensure all acquired connections/sessions are strictly released via context managers (`with db.session()` / `try...finally`).\n"
            "2. Tune pool parameters: configure sensible pool_size (e.g. 20) and max_overflow, with a pool timeout to fail fast instead of hanging threads.\n"
            "3. Optimize slow queries: check pg_stat_activity for long-running transactions holding locks.\n"
            "4. Introduce connection pooling middleware: deploy PgBouncer in transaction-pooling mode to multiplex thousands of client connections onto a smaller set of backend Postgres connections."
        ),
    },
    {
        "category": "file_system_operations",
        "instruction": "Write a cross-platform Python function to find all files matching an extension within a directory without following cyclic symlinks.",
        "input": "Parameters: root_dir: str, extension: str",
        "output": (
            "import os\nfrom typing import List\n\n"
            "def find_files_by_ext(root_dir: str, extension: str) -> List[str]:\n"
            "    matched = []\n"
            "    ext = extension if extension.startswith('.') else f'.{extension}'\n"
            "    for root, dirs, files in os.walk(root_dir, followlinks=False):\n"
            "        for file in files:\n"
            "            if file.endswith(ext):\n"
            "                matched.append(os.path.join(root, file))\n"
            "    return matched\n"
        ),
    },
    {
        "category": "technical_question_answering",
        "instruction": "Explain ACID properties in relational database management systems with a concrete banking transfer example.",
        "input": "Example scenario: Transferring $100 from Account A to Account B.",
        "output": (
            "- Atomicity: Either both debit of $100 from A and credit of $100 to B happen, or neither happens. If the server crashes mid-transfer, rollback restores prior state.\n"
            "- Consistency: Account balances cannot violate constraints (e.g., negative balance if overdraft is disabled).\n"
            "- Isolation: Concurrent transfers on Account A see consistent intermediate states without dirty reads.\n"
            "- Durability: Once the transaction commits, the updated balances persist to non-volatile storage (WAL/disk) even if power fails immediately after."
        ),
    },
    {
        "category": "general_instruction_following",
        "instruction": "Construct a robust regular expression to validate Semantic Versioning 2.0.0 strings (e.g., 'v1.2.3', '0.4.1-alpha.1').",
        "input": "Support optional leading 'v', major.minor.patch digits, and optional prerelease suffixes.",
        "output": (
            "^v?(0|[1-9]\\d*)\\.(0|[1-9]\\d*)\\.(0|[1-9]\\d*)(?:-((?:0|[1-9]\\d*|\\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\\.(?:0|[1-9]\\d*|\\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\\+([0-9a-zA-Z-]+(?:\\.[0-9a-zA-Z-]+)*))?$\n"
        ),
    },
]


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


class GeneralSyntheticDataGenerator:
    """Orchestrates idle-time generation of general-purpose training pairs.
    
    Adheres strictly to the v0.4.1 design:
    - Never accesses private user files or command histories.
    - Runs only when system is verified in IDLE or LOCKED (rejects ACTIVE state, fails closed if unknown).
    - Labels output with source = 'synthetic_general'.
    - Drives generation from Gemma 4 E4B teacher model with offline curriculum backup.
    """

    def __init__(
        self,
        model_runner: Optional[Any] = None,
        config_path: str = "config/luna.toml",
        output_path: str = "data/synthetic_general.jsonl",
        get_power_state_fn: Optional[Callable[[], Union[int, str]]] = None,
    ) -> None:
        if model_runner is None:
            try:
                from ai_engine.inference.gemma_e4b import get_default_gemma_runner
                self.model_runner = get_default_gemma_runner()
            except Exception as e:
                logger.debug(f"Could not load default Gemma runner: {e}")
                self.model_runner = None
        else:
            self.model_runner = model_runner

        self.config_path = config_path
        self.output_path = output_path
        self.get_power_state_fn = get_power_state_fn
        self.weights = load_training_weights_from_config(config_path)

    @property
    def live_interaction_weight(self) -> float:
        return self.weights.get("live_interaction_weight", 0.3)

    @property
    def synthetic_general_weight(self) -> float:
        return self.weights.get("synthetic_general_weight", 0.7)

    def _resolve_current_power_state(self) -> Optional[Union[int, str]]:
        """Resolve current power state via injected callback, PyO3 SystemState, or None."""
        if self.get_power_state_fn is not None:
            try:
                return self.get_power_state_fn()
            except Exception as e:
                logger.debug(f"get_power_state_fn failed: {e}")
                return None

        try:
            from core_engine import SystemState
            ss = SystemState()
            return ss.get_power_state_name()
        except Exception:
            return None

    def is_generation_permitted(self, power_state: Optional[Union[int, str]]) -> bool:
        """Verify that system is in an eligible idle/locked state for background generation.

        State codes:
          0 / "ACTIVE"     -> False (User working; reserve all compute for UI/inference)
          1 / "IDLE"       -> True  (User inactive >= 300s; background synthetic generation allowed)
          2 / "LOCKED"     -> True  (Workstation locked; full background generation allowed)
          3 / "SUSPENDING" -> False (System shutting down)
          None / Unknown   -> False (Fail closed)
        """
        if power_state is None:
            return False

        if isinstance(power_state, int):
            return power_state in (1, 2)

        state_str = str(power_state).strip().upper()
        return state_str in ("IDLE", "LOCKED")

    def generate_single_sample(self, category: Optional[str] = None) -> Dict[str, Any]:
        """Generate a single general-purpose synthetic pair using model runner or fallback curriculum."""
        cat = category or random.choice(CATEGORIES)

        # 1. Live model generation path via Gemma 4 E4B
        if (
            self.model_runner is not None
            and hasattr(self.model_runner, "generate_response")
            and hasattr(self.model_runner, "format_chat_prompt")
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
                parsed = self._parse_generated_response(raw_response, cat)
                if parsed:
                    return parsed
            except Exception as e:
                logger.warning(f"Dynamic model generation failed ({e}), falling back to general curriculum.")

        # 2. Fallback to high-quality general curriculum bank
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

        FAILS CLOSED: If power state cannot be confirmed as IDLE or LOCKED, generation
        is refused and an empty list is returned.

        Args:
            count: Number of samples to generate.
            power_state: Optional explicit PowerState override. If None, queries live state.
            persist: If True, appends samples to output_path.

        Returns:
            List of generated sample dictionaries, or empty list if not idle/locked.
        """
        # Determine effective power state (passed or resolved live)
        effective_state = power_state if power_state is not None else self._resolve_current_power_state()

        # Fail closed if state is not confirmed IDLE or LOCKED
        if not self.is_generation_permitted(effective_state):
            logger.info(
                f"Refusing synthetic generation: System power state is '{effective_state}' "
                f"(fail-closed: generation only permitted in confirmed IDLE or LOCKED)."
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
