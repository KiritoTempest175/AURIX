# ─────────────────────────────────────────────────────────────────────────────
# tests/test_qwen_model.py
# ─────────────────────────────────────────────────────────────────────────────
# Pytest suite verifying Qwen 3:4B LLM integration, prompt formatting,
# configuration loading, and inference runner lifecycle.
# ─────────────────────────────────────────────────────────────────────────────

import os
import pytest
from ai_engine.llm_inference import QwenModelRunner, load_config_llm_settings
from ai_engine.training.qlora_loop import MODEL_NAME, MAX_SEQ_LENGTH, LOAD_IN_4BIT


def test_llm_config_parsing():
    """Verify that load_config_llm_settings parses [llm] settings from config.toml."""
    cfg = load_config_llm_settings("./config.toml")
    assert cfg["model_name"] == "unsloth/Qwen3-4B"
    assert cfg["model_alias"] == "Qwen 3 4B"
    assert cfg["max_seq_length"] == 2048
    assert cfg["load_in_4bit"] is True
    assert cfg["quantization"] == "nf4"
    assert cfg["device"] == "cuda"


def test_qwen_prompt_formatting():
    """Verify QwenModelRunner formats instructions into proper prompt template."""
    runner = QwenModelRunner(config_path="./config.toml")
    prompt = runner.format_prompt(
        instruction="Refactor function to async",
        user_input="def foo(): pass",
        ui_context="VSCode open",
        terminal_output="Exit status 0",
    )
    assert "### Instruction:\nRefactor function to async" in prompt
    assert "### Input:\ndef foo(): pass\n[UI State] VSCode open\n[Terminal] Exit status 0" in prompt
    assert "### Response:" in prompt


def test_qwen_model_runner_fallback_generation():
    """Verify QwenModelRunner generates response in fallback/mock mode."""
    runner = QwenModelRunner(config_path="./config.toml")
    # Forcibly trigger fallback mode for fast testing without GPU weights download
    runner.is_fallback = True
    runner.is_loaded = True

    response = runner.generate(
        instruction="Build Rust file jail sandbox",
        user_input="",
    )

    assert "[Qwen 3:4B Offline Response]" in response
    assert "Build Rust file jail sandbox" in response


def test_qlora_loop_model_binding():
    """Verify qlora_loop binds to Qwen 3:4B model configuration."""
    assert MODEL_NAME == "unsloth/Qwen3-4B"
    assert MAX_SEQ_LENGTH == 2048
    assert LOAD_IN_4BIT is True
