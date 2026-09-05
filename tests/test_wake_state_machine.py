"""Test suite verifying Luna Voice Assistant State Machine and Wake Word pipeline."""

import pytest
from native_ui.audio.wake_state_machine import (
    AssistantState,
    WakeStateMachine,
    is_cancel_phrase,
    get_assistant_state_machine,
)
from native_ui.audio.wakeword_detector import WakeWordDetector


def test_assistant_state_values():
    """Verify all 5 assistant states exist according to specification."""
    assert AssistantState.SLEEPING.value == "SLEEPING"
    assert AssistantState.LISTENING.value == "LISTENING"
    assert AssistantState.THINKING.value == "THINKING"
    assert AssistantState.EXECUTING.value == "EXECUTING"
    assert AssistantState.SPEAKING.value == "SPEAKING"


def test_state_machine_transitions():
    """Verify normal state machine progression through the 5 states."""
    transitions = []

    def on_change(old_state, new_state):
        transitions.append((old_state, new_state))

    sm = WakeStateMachine(initial_state=AssistantState.SLEEPING, on_state_change=on_change)
    assert sm.is_sleeping()
    assert not sm.is_listening()

    # Step 1: Wake word detected -> LISTENING
    assert sm.transition_to(AssistantState.LISTENING)
    assert sm.is_listening()

    # Step 2: Audio recorded -> THINKING (Transcribing)
    assert sm.transition_to(AssistantState.THINKING)
    assert sm.is_thinking()

    # Step 3: Transcription ready -> EXECUTING (AI Inference)
    assert sm.transition_to(AssistantState.EXECUTING)
    assert sm.is_executing()

    # Step 4: AI response ready -> SPEAKING (TTS)
    assert sm.transition_to(AssistantState.SPEAKING)
    assert sm.is_speaking()

    # Step 5: TTS completed -> SLEEPING (Passive wake word listening)
    assert sm.transition_to(AssistantState.SLEEPING)
    assert sm.is_sleeping()

    # Verify callbacks fired in sequence
    assert transitions == [
        (AssistantState.SLEEPING, AssistantState.LISTENING),
        (AssistantState.LISTENING, AssistantState.THINKING),
        (AssistantState.THINKING, AssistantState.EXECUTING),
        (AssistantState.EXECUTING, AssistantState.SPEAKING),
        (AssistantState.SPEAKING, AssistantState.SLEEPING),
    ]


def test_state_machine_idempotent_transition():
    """Verify transitioning to current state is a no-op."""
    sm = WakeStateMachine(initial_state=AssistantState.SLEEPING)
    assert not sm.transition_to(AssistantState.SLEEPING)
    assert sm.is_sleeping()


def test_cancel_phrase_detection():
    """Verify cancel command detector catches standard cancellation phrases."""
    assert is_cancel_phrase("cancel")
    assert is_cancel_phrase("Cancel")
    assert is_cancel_phrase("cancel command")
    assert is_cancel_phrase("never mind")
    assert is_cancel_phrase("nevermind")
    assert is_cancel_phrase("stop")
    assert is_cancel_phrase("stop listening")
    assert is_cancel_phrase("abort")
    assert is_cancel_phrase("dismiss")
    assert is_cancel_phrase("exit")
    assert is_cancel_phrase("please cancel")
    assert is_cancel_phrase("cancel please")

    # Regular commands must NOT be flagged as cancellation
    assert not is_cancel_phrase("open notepad")
    assert not is_cancel_phrase("what is python")
    assert not is_cancel_phrase("who are you")
    assert not is_cancel_phrase("tell me a joke")
    assert not is_cancel_phrase("")


def test_wakeword_detector_defaults():
    """Verify WakeWordDetector is configured with Luna defaults."""
    detector = WakeWordDetector()
    assert detector.keyword == "Luna"
    assert detector.confirmation_echo == "Yes?"
    assert not detector.is_listening
