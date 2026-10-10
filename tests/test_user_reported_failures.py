"""Regression checks for the user-reported AURIX desktop failures."""
from unittest.mock import patch

from ai_brain.email_control import EmailController, draft_is_complete
from ai_brain.message_control import WhatsAppController
from security.permission_preferences import read_policy, write_policy
from security.permissions import ActionCategory, PermissionManager


def test_placeholder_project_proposal_never_gets_sent(tmp_path):
    body = (
        "Dear Client,\nProject Name: [Insert Project Name]\n"
        "Project Budget: [Insert Project Budget]\nBest regards, [Your Name]"
    )
    assert draft_is_complete(body) is False
    ctrl = EmailController(cred_file=str(tmp_path / "credentials"))
    with patch("smtplib.SMTP_SSL") as smtp:
        result = ctrl.send_email("client@example.com", "Project proposal", body, authorized=True)
    assert "NOT sent" in result
    smtp.assert_not_called()


def test_finished_email_can_be_reviewed():
    message = (
        "Dear Client,\n\nI'm writing to discuss a potential collaboration on "
        "a new software project. I'd welcome a short discussion about your goals "
        "and requirements before proposing a scope or timeline.\n\nBest regards"
    )
    assert draft_is_complete(message)


def test_permission_preferences_are_persistent_and_do_not_unlock_unsafe_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("AURIX_DATA_DIR", str(tmp_path))
    policy = read_policy()
    assert policy["allow_known_app_control"]
    saved = write_policy({
        "allow_known_app_control": False,
        "allow_local_file_reads": False,
        "allow_trusted_workspace_edits": False,
    })
    assert read_policy() == saved
    manager = PermissionManager()
    assert manager.requires_trust_token(ActionCategory.APP_CONTROL, "notepad")
    assert manager.requires_trust_token(ActionCategory.FILE_READ, "file.txt")
    assert manager.requires_trust_token(ActionCategory.FILE_WRITE, "file.txt")
    assert manager.requires_trust_token(ActionCategory.EXTERNAL_COMMUNICATION, "email to client")
    assert manager.requires_trust_token(ActionCategory.FILE_DELETE, "important-file")


def test_invalid_permission_settings_cannot_enable_sensitive_override(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setenv("AURIX_DATA_DIR", str(tmp_path))
    with pytest.raises(ValueError):
        write_policy({"allow_external_messages": True})
    with pytest.raises(ValueError):
        write_policy({"allow_known_app_control": "yes", "allow_local_file_reads": True, "allow_trusted_workspace_edits": True})


def test_whatsapp_profile_toolbar_matching_is_strict():
    assert WhatsAppController._header_matches_contact("Haad", "Haad")
    assert WhatsAppController._header_matches_contact("Haad", "Haad, contact info")
    assert not WhatsAppController._header_matches_contact("Haad", "Monday")
    assert not WhatsAppController._header_matches_contact("Haad", "Chat Haad in messages")


def test_whatsapp_requires_verified_composer_before_typing():
    import pytest
    from ai_brain.message_control import PendingWhatsAppAction
    controller = WhatsAppController()
    pending = PendingWhatsAppAction(kind="message", requested_contact="Haad",
                                    matched_contact="Haad", message="Test")
    with patch("ai_brain.message_control.pyautogui") as keyboard, patch.object(
        controller, "_focus_message_composer", side_effect=RuntimeError("Cannot locate composer")
    ):
        result = controller._execute_message(pending)
        assert result.status == "error"
        keyboard.press.assert_not_called()
        keyboard.write.assert_not_called()
