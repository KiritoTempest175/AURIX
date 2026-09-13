"""Unit tests verifying AURIX BrainDispatcher intent parsing and execution."""

from unittest.mock import patch

import pytest

from ai_brain.dispatcher import BrainDispatcher
from ai_brain.tool_executor import ToolExecutor


class FakeModelRunner:
    """Lightweight fake model used during unit tests.

    Prevents real Gemma/Unsloth/GPU/network initialization while still
    returning deterministic tool selections for commands under test.
    """

    def __init__(self):
        self.history = []

    def select_tool(self, text: str) -> dict:
        lower = text.lower().strip()

        # ---------------------------------------------------------
        # APP CONTROL
        # ---------------------------------------------------------
        if lower.startswith("open "):
            target = text[5:].strip()

            return {
                "tool": "open_app",
                "args": {
                    "target": target,
                },
            }

        # ---------------------------------------------------------
        # FILE CONTROL
        # ---------------------------------------------------------
        if lower.startswith("list files in "):
            path = text[len("list files in "):].strip()

            return {
                "tool": "list_directory",
                "args": {
                    "path": path,
                },
            }

        if lower.startswith("list directory "):
            path = text[len("list directory "):].strip()

            return {
                "tool": "list_directory",
                "args": {
                    "path": path,
                },
            }

        if lower.startswith("read file "):
            path = text[len("read file "):].strip()

            return {
                "tool": "read_file",
                "args": {
                    "path": path,
                },
            }

        # ---------------------------------------------------------
        # SHELL
        # ---------------------------------------------------------
        if lower.startswith("cmd:"):
            command = text.split(":", 1)[1].strip()

            return {
                "tool": "shell_exec",
                "args": {
                    "command": command,
                },
            }

        # ---------------------------------------------------------
        # NORMAL CONVERSATION
        # ---------------------------------------------------------
        return {
            "tool": "general_answer",
            "args": {},
        }

    def chat(
        self,
        user_message: str,
        **kwargs,
    ) -> str:
        return "Test response."

    def remember_exchange(
        self,
        user_message: str,
        assistant_message: str,
    ) -> None:
        self.history.append(
            (user_message, assistant_message)
        )


@pytest.fixture
def dispatcher():
    """Create BrainDispatcher with fake model so tests never load real LLM."""
    return BrainDispatcher(
        model_runner=FakeModelRunner()
    )


def test_wake_phrases(dispatcher):
    reply, handled = dispatcher.dispatch("hey luna")

    assert handled is True
    assert "AURIX Executive online" in reply

    reply, handled = dispatcher.dispatch("luna")
    assert handled is True

    reply, handled = dispatcher.dispatch("aurix")
    assert handled is True


def test_media_controls(dispatcher):
    with patch("os.startfile", return_value=None):

        # Pause / toggle
        reply, handled = dispatcher.dispatch("pause music")
        assert handled is True

        # Next
        reply, handled = dispatcher.dispatch("next track")
        assert handled is True

        # Previous
        reply, handled = dispatcher.dispatch("previous track")
        assert handled is True

        # Spotify DJ
        reply, handled = dispatcher.dispatch("spotify dj")
        assert handled is True

        # Play song on Spotify
        reply, handled = dispatcher.dispatch(
            "play bohemian rhapsody on spotify"
        )
        assert handled is True

        # Play song on YouTube Music
        reply, handled = dispatcher.dispatch(
            "play starboy on youtube music"
        )
        assert handled is True


def test_youtube_controls(dispatcher):
    with patch("subprocess.Popen"):

        # Play on YouTube
        reply, handled = dispatcher.dispatch(
            "play lofi hip hop on youtube"
        )
        assert handled is True

        # YouTube keyword
        reply, handled = dispatcher.dispatch(
            "youtube interstellar soundtrack"
        )
        assert handled is True

        # Trending
        reply, handled = dispatcher.dispatch(
            "trending videos"
        )
        assert handled is True


def test_web_search(dispatcher):
    with patch("subprocess.Popen"):

        reply, handled = dispatcher.dispatch(
            "search python documentation"
        )
        assert handled is True

        reply, handled = dispatcher.dispatch(
            "google latest quantum computing news"
        )
        assert handled is True


def test_file_controls(dispatcher):
    # List files
    reply, handled = dispatcher.dispatch(
        "list files in desktop"
    )

    assert handled is True

    # Read non-existent file gracefully
    reply, handled = dispatcher.dispatch(
        "read file nonexistent_sample_test_123.txt"
    )

    assert handled is True

    assert (
        "File not found" in reply
        or "Read error" in reply
        or "not found" in reply.lower()
        or "does not exist" in reply.lower()
    )


def test_email_controls(dispatcher):
    with patch("os.startfile", return_value=None):

        reply, handled = dispatcher.dispatch(
            "draft email to test@example.com | Hello | How are you"
        )
        assert handled is True

        reply, handled = dispatcher.dispatch(
            "email test@example.com saying Meeting at 3pm"
        )
        assert handled is True


def test_app_controls(dispatcher):
    with patch("os.startfile", return_value=None):

        # Launch Notepad
        reply, handled = dispatcher.dispatch(
            "open notepad"
        )
        assert handled is True

        # Calculator
        reply, handled = dispatcher.dispatch(
            "calc"
        )
        assert handled is True

        # Close application
        reply, handled = dispatcher.dispatch(
            "close notepad"
        )
        assert handled is True


def test_shell_command_requires_confirmation():
    """Shell commands must require explicit trust-token approval."""

    executor = ToolExecutor()

    reply = executor.execute(
        "shell_exec",
        {
            "command": "echo AURIX_TEST_OK"
        },
    )

    assert reply.startswith(
        "TRUST_TOKEN_REQUIRED:"
    )

