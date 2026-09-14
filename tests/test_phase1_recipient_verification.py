from unittest.mock import patch

import pytest

from ai_brain.message_control import (
    ActionResult,
    PendingWhatsAppAction,
    WhatsAppController,
    WhatsAppUIError,
)


def test_contact_name_matching_ignores_case_and_spacing():

    controller = WhatsAppController()

    assert controller._contact_names_match(
        "  Muhammad   Saad ",
        "muhammad saad",
    )


def test_partial_contact_name_is_not_accepted():

    controller = WhatsAppController()

    assert not controller._contact_names_match(
        "Saad",
        "Saad Ahmed",
    )


def test_different_contact_is_rejected():

    controller = WhatsAppController()

    assert not controller._contact_names_match(
        "Saad",
        "Zain",
    )


def test_phone_number_exact_match():

    controller = WhatsAppController()

    assert controller._contact_names_match(
        "+92 300 1234567",
        "+923001234567",
    )


def test_prepare_message_uses_verified_contact():

    controller = WhatsAppController()

    with patch.object(
        controller,
        "_require_pyautogui",
    ), patch.object(
        controller,
        "_ensure_running",
    ), patch.object(
        controller,
        "_search_and_open_contact",
    ), patch.object(
        controller,
        "_verify_selected_contact",
        return_value="Muhammad Saad",
    ):

        pending = controller.prepare_message(
            "Muhammad Saad",
            "Hello",
        )

    assert pending.kind == "message"

    assert (
        pending.requested_contact
        == "Muhammad Saad"
    )

    assert (
        pending.matched_contact
        == "Muhammad Saad"
    )

    assert pending.message == "Hello"


def test_prepare_message_fails_when_recipient_not_verified():

    controller = WhatsAppController()

    with patch.object(
        controller,
        "_require_pyautogui",
    ), patch.object(
        controller,
        "_ensure_running",
    ), patch.object(
        controller,
        "_search_and_open_contact",
    ), patch.object(
        controller,
        "_verify_selected_contact",
        side_effect=WhatsAppUIError(
            "Recipient mismatch"
        ),
    ):

        with pytest.raises(
            WhatsAppUIError
        ):

            controller.prepare_message(
                "Saad",
                "Hello",
            )


def test_execute_reverifies_recipient_before_send():

    controller = WhatsAppController()

    pending = PendingWhatsAppAction(
        kind="message",
        requested_contact="Saad",
        matched_contact="Saad",
        message="Hello",
    )

    with patch.object(
        controller,
        "_require_pyautogui",
    ), patch.object(
        controller,
        "_ensure_running",
    ), patch.object(
        controller,
        "_verify_selected_contact",
        return_value="Saad",
    ) as verifier, patch.object(
        controller,
        "_execute_message",
        return_value=ActionResult(
            status="sent",
            detail="TEST_SENT",
            matched_contact="Saad",
        ),
    ) as sender:

        result = controller.execute(
            pending,
            authorized=True,
        )

    verifier.assert_called_once_with(
        "Saad"
    )

    sender.assert_called_once()

    assert result.status == "sent"


def test_execute_blocks_when_recipient_verification_fails():

    controller = WhatsAppController()

    pending = PendingWhatsAppAction(
        kind="message",
        requested_contact="Saad",
        matched_contact="Saad",
        message="Hello",
    )

    with patch.object(
        controller,
        "_require_pyautogui",
    ), patch.object(
        controller,
        "_ensure_running",
    ), patch.object(
        controller,
        "_verify_selected_contact",
        side_effect=WhatsAppUIError(
            "Could not verify Saad"
        ),
    ), patch.object(
        controller,
        "_execute_message",
    ) as sender:

        result = controller.execute(
            pending,
            authorized=True,
        )

    sender.assert_not_called()

    assert result.status == "blocked"

    assert (
        "verification"
        in result.detail.lower()
    )


def test_execute_blocks_if_chat_changes_after_prepare():

    controller = WhatsAppController()

    pending = PendingWhatsAppAction(
        kind="message",
        requested_contact="Saad",
        matched_contact="Saad",
        message="Hello",
    )

    with patch.object(
        controller,
        "_require_pyautogui",
    ), patch.object(
        controller,
        "_ensure_running",
    ), patch.object(
        controller,
        "_verify_selected_contact",
        return_value="Zain",
    ), patch.object(
        controller,
        "_execute_message",
    ) as sender:

        result = controller.execute(
            pending,
            authorized=True,
        )

    sender.assert_not_called()

    assert result.status == "blocked"

    assert (
        "changed"
        in result.detail.lower()
    )