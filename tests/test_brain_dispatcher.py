"""Unit tests verifying AURIX BrainDispatcher intent parsing and execution."""

from unittest.mock import patch
import pytest
from ai_brain.dispatcher import BrainDispatcher


@pytest.fixture
def dispatcher():
    return BrainDispatcher()


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

        # Next / prev
        reply, handled = dispatcher.dispatch("next track")
        assert handled is True

        reply, handled = dispatcher.dispatch("previous track")
        assert handled is True

        # Spotify DJ
        reply, handled = dispatcher.dispatch("spotify dj")
        assert handled is True

        # Play song on spotify
        reply, handled = dispatcher.dispatch("play bohemian rhapsody on spotify")
        assert handled is True

        # Play song on youtube music
        reply, handled = dispatcher.dispatch("play starboy on youtube music")
        assert handled is True


def test_youtube_controls(dispatcher):
    with patch("subprocess.Popen"):
        # Play on youtube
        reply, handled = dispatcher.dispatch("play lofi hip hop on youtube")
        assert handled is True

        # Youtube keyword
        reply, handled = dispatcher.dispatch("youtube interstellar soundtrack")
        assert handled is True

        # Trending
        reply, handled = dispatcher.dispatch("trending videos")
        assert handled is True


def test_web_search(dispatcher):
    with patch("subprocess.Popen"):
        reply, handled = dispatcher.dispatch("search python documentation")
        assert handled is True

        reply, handled = dispatcher.dispatch("google latest quantum computing news")
        assert handled is True


def test_file_controls(dispatcher):
    # List files
    reply, handled = dispatcher.dispatch("list files in desktop")
    assert handled is True

    # Read non-existent file gracefully
    reply, handled = dispatcher.dispatch("read file nonexistent_sample_test_123.txt")
    assert handled is True
    assert "File not found" in reply or "Read error" in reply or "desktop" in reply.lower()


def test_email_controls(dispatcher):
    with patch("os.startfile", return_value=None):
        reply, handled = dispatcher.dispatch("draft email to test@example.com | Hello | How are you")
        assert handled is True

        reply, handled = dispatcher.dispatch("email test@example.com saying Meeting at 3pm")
        assert handled is True


def test_app_controls(dispatcher):
    with patch("os.startfile", return_value=None):
        # Launch aliases
        reply, handled = dispatcher.dispatch("open notepad")
        assert handled is True

        reply, handled = dispatcher.dispatch("calc")
        assert handled is True

        # Close
        reply, handled = dispatcher.dispatch("close notepad")
        assert handled is True


def test_shell_command(dispatcher):
    reply, handled = dispatcher.dispatch("cmd: echo AURIX_TEST_OK")
    assert handled is True
    assert "AURIX_TEST_OK" in reply
