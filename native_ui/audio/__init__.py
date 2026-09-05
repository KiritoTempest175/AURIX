"""LUNA Native Audio Subsystem."""

from native_ui.audio.luna_voice import record_audio, speak, get_voice, get_female_voice_model
from native_ui.audio.stt import transcribe_audio, get_stt_engine
from native_ui.audio.wakeword_detector import WakeWordDetector, get_default_wakeword_detector
from native_ui.audio.wake_state_machine import (
    AssistantState,
    WakeStateMachine,
    is_cancel_phrase,
    get_assistant_state_machine,
)

__all__ = [
    "record_audio",
    "transcribe_audio",
    "get_stt_engine",
    "speak",
    "get_voice",
    "get_female_voice_model",
    "WakeWordDetector",
    "get_default_wakeword_detector",
    "AssistantState",
    "WakeStateMachine",
    "is_cancel_phrase",
    "get_assistant_state_machine",
]
