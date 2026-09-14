from unittest.mock import patch

from ai_brain.email_control import EmailController
from ai_brain.message_control import (
    WhatsAppController,
    PendingWhatsAppAction,
)
from ai_brain.tool_executor import ToolExecutor


class FakeEmailModel:
    def format_chat_prompt(
        self,
        user_message: str,
    ) -> str:
        return user_message

    def generate_response(
        self,
        prompt: str,
    ) -> str:
        return (
            "Hello,\n\n"
            "This is the generated email.\n\n"
            "Regards"
        )


def test_direct_email_send_is_blocked():
    controller = EmailController()

    with patch.object(
        controller,
        "_get_credentials",
    ) as credentials:

        result = controller.send_email(
            "test@example.com",
            "Hello",
            "Test message",
        )

    credentials.assert_not_called()

    assert "not sent" in result.lower()
    assert "approval" in result.lower()


def test_ai_email_generation_does_not_send():
    controller = EmailController()

    with patch.object(
        controller,
        "send_email",
    ) as sender:

        result = controller.send_email_from_subject(
            "test@example.com",
            "Project update",
            FakeEmailModel(),
        )

    sender.assert_not_called()

    assert result.startswith(
        "EMAIL_REVIEW_REQUIRED:"
    )

    assert "test@example.com" in result
    assert "generated email" in result.lower()


def test_authorized_email_can_reach_delivery_path():
    controller = EmailController()

    with patch.object(
        controller,
        "_get_credentials",
        return_value=None,
    ), patch.object(
        controller,
        "open_mail_client",
        return_value="Draft opened.",
    ):

        result = controller.send_email(
            "test@example.com",
            "Hello",
            "Message",
            authorized=True,
        )

    assert "NOT sent automatically" in result


def test_direct_whatsapp_send_is_blocked():
    controller = WhatsAppController()

    result = controller.send_message_direct(
        "Saad",
        "Hello",
    )

    assert result.status == "blocked"

    assert "disabled" in result.detail.lower()


def test_whatsapp_execute_requires_authorization():
    controller = WhatsAppController()

    pending = PendingWhatsAppAction(
        kind="message",
        matched_contact="Saad",
        message="Hello",
    )

    result = controller.execute(
        pending
    )

    assert result.status == "blocked"

    assert "approval" in result.detail.lower()


def test_tool_executor_email_requires_trust_token():
    executor = ToolExecutor()

    result = executor.execute(
        "send_email",
        {
            "to": "test@example.com",
            "subject": "Hello",
            "body": "Test body",
        },
    )

    assert result.startswith(
        "TRUST_TOKEN_REQUIRED:"
    )


def test_tool_executor_passes_authorization_to_email():
    executor = ToolExecutor()

    with patch.object(
        executor.email,
        "send_email",
        return_value="EMAIL_SENT_TEST",
    ) as sender:

        request = executor.execute(
            "send_email",
            {
                "to": "test@example.com",
                "subject": "Hello",
                "body": "Test body",
            },
        )

        assert request.startswith(
            "TRUST_TOKEN_REQUIRED:"
        )

        result = executor.confirm_pending(
            request
        )

    assert result == "EMAIL_SENT_TEST"

    sender.assert_called_once_with(
        "test@example.com",
        "Hello",
        "Test body",
        authorized=True,
    )


def test_tool_executor_whatsapp_requires_confirmation():
    executor = ToolExecutor()

    result = executor.execute(
        "send_whatsapp_message",
        {
            "contact": "Saad",
            "message": "Hello",
        },
    )

    assert result.startswith(
        "TRUST_TOKEN_REQUIRED:"
    )