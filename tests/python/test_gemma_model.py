"""Unit tests for Gemma 3n E4B / E2B Inference Engine."""

import pytest
from ai_engine.inference.gemma_e4b import GemmaModelRunner


def test_gemma_runner_initialization():
    runner = GemmaModelRunner(effective_params="E4B", force_fallback=True)
    assert runner.effective_params == "E4B"
    assert runner.is_loaded is True


def test_gemma_runner_effective_params_toggle():
    runner = GemmaModelRunner(effective_params="E4B", force_fallback=True)
    runner.set_effective_parameters("E2B")
    assert runner.effective_params == "E2B"
    runner.set_effective_parameters("E4B")
    assert runner.effective_params == "E4B"

    with pytest.raises(ValueError):
        runner.set_effective_parameters("INVALID_MODE")


def test_gemma_chat_prompt_formatting():
    runner = GemmaModelRunner(effective_params="E4B", force_fallback=True)
    prompt = runner.format_chat_prompt(
        user_message="Inspect system status",
        ui_state={"focused_element": "Visual Studio Code"},
        terminal_context="cargo check --workspace: exit 0",
    )
    assert "Inspect system status" in prompt
    assert "Visual Studio Code" in prompt
    assert "cargo check" in prompt


def test_gemma_fallback_generation():
    runner = GemmaModelRunner(effective_params="E4B", force_fallback=True)
    response = runner.generate_response("Check hardware status")
    assert len(response) > 0
    assert "Governor" in response or "LUNA" in response or "Hardware" in response
