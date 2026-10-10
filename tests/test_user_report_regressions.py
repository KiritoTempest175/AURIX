"""Regression coverage for speech errors, unfilled email drafts and WhatsApp targeting."""
from unittest.mock import patch

from ai_brain.email_control import draft_is_complete
from ai_brain.message_control import WhatsAppController
from native_ui.audio import offline_voice


def test_unfilled_proposal_is_never_approved_as_complete():
    assert not draft_is_complete("Dear client,\nProject Budget: [Insert Project Budget]\n[Your Name]")
    assert not draft_is_complete("We will send this proposal, TBD.")
    assert draft_is_complete(
        "Dear Client,\nI would like to discuss our upcoming project and "
        "understand your requirements before proposing a scope.\nKind regards."
    )


def test_whatsapp_contact_match_never_accepts_chat_day_or_partial_name():
    assert WhatsAppController._header_matches_contact("Haad", "Haad, contact info")
    assert WhatsAppController._header_matches_contact("Haad", "haad")
    assert not WhatsAppController._header_matches_contact("Haad", "Monday")
    assert not WhatsAppController._header_matches_contact("Haad", "Haad's friend")


def test_missing_whisper_uses_explicit_local_windows_fallback():
    with patch.object(offline_voice, "_model_path", side_effect=RuntimeError("NO_STT_MODEL")):
        with patch.object(offline_voice, "_windows_speech_recognition", return_value=""):
            assert offline_voice.transcribe_microphone() == ""
