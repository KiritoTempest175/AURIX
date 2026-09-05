"""LUNA Voice Assistant State Machine.

Coordinates the 5 core states of the voice assistant:
- State 1: SLEEPING (Passive background wake-word listening for 'Luna' / 'Hey Luna')
- State 2: LISTENING (Active microphone recording of user's command after 'Yes?')
- State 3: THINKING (Speech-to-text transcription and prompt preparation)
- State 4: EXECUTING (AI reasoning via Qwen/Gemma, tool execution, or direct command)
- State 5: SPEAKING (TTS audio output playing back to user)
"""

from __future__ import annotations

import enum
import logging
import threading
from typing import Callable, Optional, Set

logger = logging.getLogger("luna.audio.state_machine")


class AssistantState(str, enum.Enum):
    """The 5 discrete states of Luna's voice assistant loop."""
    SLEEPING = "SLEEPING"       # State 1: Low-CPU background wake-word detection
    LISTENING = "LISTENING"     # State 2: Mic actively recording user command
    THINKING = "THINKING"       # State 3: STT transcription & LLM prompt processing
    EXECUTING = "EXECUTING"     # State 4: Tool / app execution / AI answer generation
    SPEAKING = "SPEAKING"       # State 5: TTS audio output playing back to user


CANCEL_PHRASES: Set[str] = {
    "cancel",
    "cancel command",
    "never mind",
    "nevermind",
    "stop",
    "stop listening",
    "abort",
    "dismiss",
    "exit",
    "shut up",
    "quiet",
}


def is_cancel_phrase(text: str) -> bool:
    """Checks whether the transcribed text represents a cancellation request."""
    if not text:
        return False
    cleaned = text.strip().lower().rstrip(".,!?")
    if cleaned in CANCEL_PHRASES:
        return True
    for phrase in CANCEL_PHRASES:
        if cleaned == phrase or cleaned.startswith(f"{phrase} ") or cleaned.endswith(f" {phrase}"):
            return True
    return False


class WakeStateMachine:
    """Thread-safe state machine for the Luna Voice Assistant."""

    def __init__(
        self,
        initial_state: AssistantState = AssistantState.SLEEPING,
        on_state_change: Optional[Callable[[AssistantState, AssistantState], None]] = None,
    ) -> None:
        self._state = initial_state
        self._lock = threading.Lock()
        self.on_state_change = on_state_change

    @property
    def current_state(self) -> AssistantState:
        with self._lock:
            return self._state

    def is_sleeping(self) -> bool:
        return self.current_state == AssistantState.SLEEPING

    def is_listening(self) -> bool:
        return self.current_state == AssistantState.LISTENING

    def is_thinking(self) -> bool:
        return self.current_state == AssistantState.THINKING

    def is_executing(self) -> bool:
        return self.current_state == AssistantState.EXECUTING

    def is_speaking(self) -> bool:
        return self.current_state == AssistantState.SPEAKING

    def transition_to(self, new_state: AssistantState) -> bool:
        """Transitions to new_state and invokes notification callback."""
        with self._lock:
            old_state = self._state
            if old_state == new_state:
                return False
            self._state = new_state

        logger.info(f"Luna State Transition: {old_state.value} -> {new_state.value}")
        if self.on_state_change:
            try:
                self.on_state_change(old_state, new_state)
            except Exception as e:
                logger.error(f"Error in on_state_change callback: {e}")
        return True


_GLOBAL_STATE_MACHINE: Optional[WakeStateMachine] = None


def get_assistant_state_machine() -> WakeStateMachine:
    """Returns singleton assistant state machine instance."""
    global _GLOBAL_STATE_MACHINE
    if _GLOBAL_STATE_MACHINE is None:
        _GLOBAL_STATE_MACHINE = WakeStateMachine()
    return _GLOBAL_STATE_MACHINE
