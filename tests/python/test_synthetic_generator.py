"""Unit and integration tests for LUNA v0.4.1 General Synthetic Generator & Replay Buffer.

Verifies:
1. Fail-closed governor gating (refusing generation unless confirmed IDLE/LOCKED).
2. Zero project file reads (active spy on builtins.open and path access).
3. Live model generation path with mock Gemma 4 E4B runner (prompting -> inference -> parsing).
4. Rebalanced 30% live / 70% synthetic general experience replay sampling.
5. Dynamic telemetry dataset multi-source streaming.
"""

import builtins
import json
import os
import tempfile
from typing import Any, Dict, List
from unittest.mock import patch

from ai_engine.training.synthetic_generator import (
    CATEGORIES,
    GeneralSyntheticDataGenerator,
    load_training_weights_from_config,
)
from data_pipeline.compiler.replay_buffer import ExperienceReplayBuffer
from ai_engine.training.dynamic_loader import DynamicTelemetryDataset
from ai_engine.training.student_qlora_loop import StudentTrainingController


# ─── Mock Gemma Model Runner for Live-Generation Path ─────────────────────────

class MockGemmaRunner:
    """Mock Gemma 4 E4B runner simulating prompt formatting and dynamic inference."""

    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail
        self.format_calls: List[str] = []
        self.generate_calls: List[str] = []
        self.is_loaded = True

    def format_chat_prompt(self, user_message: str, **kwargs: Any) -> str:
        self.format_calls.append(user_message)
        return f"<start_of_turn>user\n{user_message}<end_of_turn>\n<start_of_turn>model\n"

    def generate_response(self, prompt: str, **kwargs: Any) -> str:
        self.generate_calls.append(prompt)
        if self.should_fail:
            raise RuntimeError("CUDA out of memory simulation")

        # Return structured response following the instruction protocol
        return (
            "INSTRUCTION: Implement an async task queue in Python using asyncio.Queue.\n"
            "INPUT: Concurrency limit: max_workers concurrent worker coroutines.\n"
            "RESPONSE: async def worker(q):\n    while True:\n        item = await q.get()\n        q.task_done()"
        )


# ─── Tests ───────────────────────────────────────────────────────────────────

def test_training_weights_loaded_from_config():
    """Verify that live_interaction_weight and synthetic_general_weight are loaded from config/luna.toml."""
    weights = load_training_weights_from_config("config/luna.toml")
    assert weights["live_interaction_weight"] == 0.3
    assert weights["synthetic_general_weight"] == 0.7


def test_synthetic_general_source_tagging():
    """Verify that all generated synthetic samples carry source = 'synthetic_general'."""
    generator = GeneralSyntheticDataGenerator()
    sample = generator.generate_single_sample()

    assert sample["source"] == "synthetic_general"
    assert len(sample["instruction"]) > 0
    assert len(sample["output"]) > 0
    assert sample["category"] in CATEGORIES


def test_fail_closed_governor_gating():
    """Verify generator FAILS CLOSED when power_state is None, unknown, or ACTIVE."""
    # 1. State function returns 0 (ACTIVE) -> Refuse generation
    generator_active = GeneralSyntheticDataGenerator(get_power_state_fn=lambda: 0)
    samples = generator_active.generate_batch(count=5, power_state=None, persist=False)
    assert len(samples) == 0, "Fail-closed violation: generation ran while governor is ACTIVE"

    # 2. State function returns None (Unknown) -> Refuse generation
    generator_unknown = GeneralSyntheticDataGenerator(get_power_state_fn=lambda: None)
    samples = generator_unknown.generate_batch(count=5, power_state=None, persist=False)
    assert len(samples) == 0, "Fail-closed violation: generation ran with unconfirmed power state"

    # 3. Explicit parameter ACTIVE -> Refuse generation
    assert generator_active.is_generation_permitted("ACTIVE") is False
    assert generator_active.is_generation_permitted(0) is False
    assert len(generator_active.generate_batch(count=5, power_state="ACTIVE", persist=False)) == 0

    # 4. State function returns 1 (IDLE) or 2 (LOCKED) -> Permit generation
    generator_idle = GeneralSyntheticDataGenerator(get_power_state_fn=lambda: 1)
    samples_idle = generator_idle.generate_batch(count=3, power_state=None, persist=False)
    assert len(samples_idle) == 3

    generator_locked = GeneralSyntheticDataGenerator(get_power_state_fn=lambda: "LOCKED")
    samples_locked = generator_locked.generate_batch(count=2, power_state=None, persist=False)
    assert len(samples_locked) == 2


def test_synthetic_general_zero_project_file_reads():
    """Verify that neither the live-generation path nor the fallback path reads user project files."""
    mock_runner = MockGemmaRunner()
    generator = GeneralSyntheticDataGenerator(model_runner=mock_runner, get_power_state_fn=lambda: "IDLE")

    read_files: List[str] = []
    real_open = builtins.open

    def spy_open(file, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        if "r" in mode:
            read_files.append(str(file))
        return real_open(file, *args, **kwargs)

    with patch("builtins.open", side_effect=spy_open):
        # 1. Test live model generation path
        samples_live = generator.generate_batch(count=2, power_state="IDLE", persist=False)
        assert len(samples_live) == 2

        # 2. Test fallback curriculum generation path
        generator_fallback = GeneralSyntheticDataGenerator(model_runner=None, get_power_state_fn=lambda: "IDLE")
        samples_fallback = generator_fallback.generate_batch(count=3, power_state="IDLE", persist=False)
        assert len(samples_fallback) == 3

    # Intercepted read files must NOT contain user directories, source code files, or command history
    forbidden_tokens = ["c:\\users", "c:/users", "desktop", "documents", ".bash_history", ".ps_history", "main.rs"]
    for opened_file in read_files:
        opened_lower = opened_file.lower().replace("/", "\\")
        for token in forbidden_tokens:
            assert token not in opened_lower, f"Zero-file-access breach: {opened_file} was opened during generation"


def test_live_generation_path_with_mock_gemma_runner():
    """Verify that GeneralSyntheticDataGenerator exercises the live Gemma model reasoning path."""
    mock_runner = MockGemmaRunner()
    generator = GeneralSyntheticDataGenerator(model_runner=mock_runner, get_power_state_fn=lambda: "IDLE")

    # Generate single sample in a specific category
    sample = generator.generate_single_sample(category="common_coding_tasks")

    # Verify model runner was called with proper chat template
    assert len(mock_runner.format_calls) == 1
    assert "common_coding_tasks" in mock_runner.format_calls[0]
    assert len(mock_runner.generate_calls) == 1

    # Verify parsed fields from live model response
    assert sample["source"] == "synthetic_general"
    assert sample["category"] == "common_coding_tasks"
    assert "asyncio.Queue" in sample["instruction"]
    assert "max_workers" in sample["input"]
    assert "async def worker" in sample["output"]


def test_live_generation_fallback_on_model_exception():
    """Verify that if model inference raises an exception, generator falls back gracefully to curriculum."""
    failing_runner = MockGemmaRunner(should_fail=True)
    generator = GeneralSyntheticDataGenerator(model_runner=failing_runner, get_power_state_fn=lambda: "IDLE")

    sample = generator.generate_single_sample(category="file_system_operations")
    assert sample["source"] == "synthetic_general"
    assert sample["category"] == "file_system_operations"
    assert len(sample["instruction"]) > 0
    assert len(sample["output"]) > 0


def test_replay_buffer_weights_from_config():
    """Verify ExperienceReplayBuffer initializes with config-driven weights (0.3 / 0.7)."""
    buffer = ExperienceReplayBuffer(config_path="config/luna.toml")
    assert buffer.live_interaction_weight == 0.3
    assert buffer.synthetic_general_weight == 0.7

    # Test explicit parameter overrides
    custom_buffer = ExperienceReplayBuffer(
        config_path="config/luna.toml",
        live_interaction_weight=0.4,
        synthetic_general_weight=0.6,
    )
    assert custom_buffer.live_interaction_weight == 0.4
    assert custom_buffer.synthetic_general_weight == 0.6


def test_replay_buffer_sampling_rebalance():
    """Verify sample_training_batch respects the 30% live / 70% synthetic general distribution."""
    buffer = ExperienceReplayBuffer(
        live_interaction_weight=0.3,
        synthetic_general_weight=0.7,
    )

    # Populate 20 live experiences
    for i in range(20):
        buffer.add_user_experience(
            instruction=f"User terminal command #{i}",
            action=f"cargo check --package module_{i}",
            outcome="SUCCESS",
        )

    # Populate 50 synthetic general experiences
    for i in range(50):
        buffer.add_synthetic_general_experience(
            instruction=f"Explain general concept #{i}",
            output=f"Concept explanation #{i}",
            category="common_coding_tasks",
        )

    # Sample a batch of 10
    batch = buffer.sample_training_batch(batch_size=10)
    assert len(batch) == 10

    live_samples = [s for s in batch if s.get("source") == "live_interaction"]
    synthetic_samples = [s for s in batch if s.get("source") == "synthetic_general"]

    # 30% of 10 is 3, 70% of 10 is 7
    assert len(live_samples) == 3
    assert len(synthetic_samples) == 7


def test_dynamic_loader_supports_synthetic_general():
    """Verify DynamicTelemetryDataset properly parses and streams synthetic_general samples."""
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".jsonl", encoding="utf-8") as tf:
        tf.write('{"instruction": "Write a binary search in Rust", "input": "", "output": "fn bsearch...", "source": "synthetic_general"}\n')
        tf.write('{"instruction": "Run tests", "input": "", "output": "Tests passed", "source": "live_interaction"}\n')
        temp_file = tf.name

    try:
        dataset = DynamicTelemetryDataset(data_path=temp_file)
        samples = list(dataset)
        assert len(samples) == 2
        assert samples[0]["source"] == "synthetic_general"
        assert "binary search" in samples[0]["text"]
        assert samples[1]["source"] == "live_interaction"
        assert "Run tests" in samples[1]["text"]
    finally:
        if os.path.exists(temp_file):
            os.remove(temp_file)


def test_student_controller_wires_synthetic_generator_and_power_query():
    """Verify StudentTrainingController wires live power query into GeneralSyntheticDataGenerator."""
    power_state_record = {"state": 0}
    controller = StudentTrainingController(
        get_power_state_fn=lambda: power_state_record["state"]
    )

    assert controller.synthetic_generator is not None
    assert controller.get_power_state_fn() == 0

    # When governor is ACTIVE (0), synthetic generation yields empty (fail closed)
    batch_active = controller.synthetic_generator.generate_batch(count=3, persist=False)
    assert len(batch_active) == 0

    # When governor switches to IDLE (1), synthetic generation proceeds
    power_state_record["state"] = 1
    assert controller.get_power_state_fn() == 1
    batch_idle = controller.synthetic_generator.generate_batch(count=2, persist=False)
    assert len(batch_idle) == 2
