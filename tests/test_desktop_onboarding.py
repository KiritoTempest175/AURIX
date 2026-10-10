"""Regression tests for onboarding and risk-based desktop actions."""
from unittest.mock import patch

from ai_brain.tool_executor import ToolExecutor
from ai_brain.dispatcher import BrainDispatcher
from ai_brain.email_control import EmailController
from security.permissions import ActionCategory, PermissionManager
from native_ui.audio import offline_voice
from native_ui.audio.wake_service import _WAKE


def test_common_apps_need_no_dialog_but_powershell_does():
    executor = ToolExecutor()
    for app in ("whatsapp", "notepad", "calculator", "spotify"):
        assert executor._get_category("open_app", {"target": app}) == ActionCategory.APP_CONTROL
        assert executor.permission_manager.requires_trust_token(
            ActionCategory.APP_CONTROL, f"target={app}"
        ) is False
        assert executor._get_category("close_app", {"target": app}) == ActionCategory.APP_CONTROL
    for app in ("powershell", "cmd", "regedit", "C:\\Windows\\System32\\cmd.exe", "https://bad.test"):
        assert executor._get_category("open_app", {"target": app}) == ActionCategory.SYSTEM_SETTING
        assert executor.permission_manager.requires_trust_token(
            ActionCategory.SYSTEM_SETTING, f"target={app}"
        ) is True


def test_privileged_actions_still_need_approval():
    manager = PermissionManager()
    assert manager.requires_trust_token(ActionCategory.FILE_DELETE, "secret") is True
    assert manager.requires_trust_token(ActionCategory.EXTERNAL_COMMUNICATION, "email") is True
    assert manager.requires_trust_token(ActionCategory.SYSTEM_SETTING, "shell") is True


def test_direct_open_app_works_without_model(tmp_path, monkeypatch):
    monkeypatch.setenv("AURIX_DATA_DIR", str(tmp_path))
    router = BrainDispatcher(model_runner=None)
    with patch.object(router.executor.launcher, "launch", return_value="Launched WhatsApp") as launcher:
        reply, handled = router.dispatch("Open WhatsApp")
    assert handled and "Launched WhatsApp" in reply
    launcher.assert_called_once_with("whatsapp")


def test_encrypted_smtp_credentials_do_not_expose_secret(tmp_path):
    store = EmailController(cred_file=str(tmp_path / "private" / "smtp_creds.enc"))
    assert store.save_credentials("test@gmail.com", "abcd efgh ijkl mnop")
    raw = (tmp_path / "private" / "smtp_creds.enc").read_bytes()
    assert b"abcdefghijklmnop" not in raw
    assert store.credentials_status() == {"configured": True, "address": "test@gmail.com"}
    assert store._get_credentials() == ("test@gmail.com", "abcdefghijklmnop")
    assert store.remove_credentials()
    assert store.credentials_status() == {"configured": False, "address": ""}


def test_microphone_uses_os_fallback_if_no_whisper_model():
    with patch.object(offline_voice, "_model_path", side_effect=RuntimeError("NO_STT_MODEL")), patch.object(
        offline_voice, "_windows_speech_recognition", return_value="Hey Luna"
    ):
        assert offline_voice.transcribe_microphone() == "Hey Luna"


def test_wake_regex_recognizes_only_phrases():
    assert _WAKE.search("Hey Luna, open WhatsApp")
    assert _WAKE.search("hello luna")
    assert not _WAKE.search("alunatic")
