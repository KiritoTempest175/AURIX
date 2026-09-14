"""AURIX AI Brain — Secure Email Controller.

Provides:

1. AI email body generation.
2. Draft/review flow for AI-generated emails.
3. Gmail SMTP delivery.
4. Native Windows mail-client fallback.
5. Encrypted SMTP credential storage.
6. Centralized authorization enforcement.

IMPORTANT SECURITY RULE:

EmailController itself must NEVER autonomously send email unless
ToolExecutor has already completed the AURIX trust-token approval flow
and explicitly calls send_email(..., authorized=True).

AI-generated emails are drafts only until approved.
"""

from __future__ import annotations

import logging
import os
import smtplib
import sys
import urllib.parse

from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Optional, Protocol


# ================================================================
# PROJECT ROOT
# ================================================================

_PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(_PROJECT_ROOT),
    )


# ================================================================
# ENCRYPTION
# ================================================================

try:
    from security.encryption import (
        get_default_encryptor,
    )

except ImportError:
    get_default_encryptor = None


logger = logging.getLogger(
    "aurix.ai_brain.email_control"
)


# ================================================================
# MODEL INTERFACE
# ================================================================

class ModelRunnerProtocol(Protocol):
    """Minimal interface needed for AI email generation."""

    def format_chat_prompt(
        self,
        user_message: str,
    ) -> str:
        ...

    def generate_response(
        self,
        prompt: str,
    ) -> str:
        ...


# ================================================================
# ERRORS
# ================================================================

class EmailGenerationError(
    RuntimeError
):
    """Raised when AI email generation fails."""

    pass


# ================================================================
# EMAIL DRAFT
# ================================================================

@dataclass(frozen=True)
class PreparedEmail:
    """Immutable email awaiting human approval."""

    to_addr: str
    subject: str
    body: str


# ================================================================
# AI PROMPT
# ================================================================

_BODY_GENERATION_INSTRUCTION = (
    "Write a clear, appropriately concise email body "
    "for an email with this subject line: "
    "\"{subject}\". "
    "Output ONLY the body text itself, ready for review. "
    "Do not repeat the subject line. "
    "Do not include placeholder brackets such as [Your Name]. "
    "Do not include meta-commentary. "
    "Match the tone to what the subject implies."
)


# ================================================================
# CONTROLLER
# ================================================================

class EmailController:
    """Secure email composition and delivery controller."""

    def __init__(
        self,
        cred_file: str = os.path.join(
            "data",
            "smtp_creds.enc",
        ),
    ) -> None:

        self.cred_file = cred_file

        self.encryptor = (
            get_default_encryptor()
            if get_default_encryptor
            else None
        )

    # ============================================================
    # VALIDATION
    # ============================================================

    @staticmethod
    def _validate_email_address(
        email_addr: str,
    ) -> str:

        email_addr = str(
            email_addr or ""
        ).strip()

        if (
            not email_addr
            or "@" not in email_addr
            or email_addr.startswith("@")
            or email_addr.endswith("@")
        ):
            raise ValueError(
                "Recipient email address is invalid."
            )

        return email_addr

    # ============================================================
    # AI BODY GENERATION
    # ============================================================

    def generate_body_from_subject(
        self,
        subject: str,
        model_runner: Optional[
            ModelRunnerProtocol
        ],
    ) -> str:
        """Generate email text without sending anything."""

        subject = str(
            subject or ""
        ).strip()

        if not subject:
            raise ValueError(
                "Cannot generate an email body "
                "from an empty subject."
            )

        if model_runner is None:
            raise EmailGenerationError(
                "No AI model is available "
                "to generate the email body."
            )

        prompt_text = (
            _BODY_GENERATION_INSTRUCTION.format(
                subject=subject
            )
        )

        try:

            prompt = (
                model_runner.format_chat_prompt(
                    user_message=prompt_text
                )
            )

            body = (
                model_runner.generate_response(
                    prompt
                )
            )

        except Exception as exc:

            raise EmailGenerationError(
                f"AI email generation failed: {exc}"
            ) from exc

        body = str(
            body or ""
        ).strip()

        if not body:

            raise EmailGenerationError(
                "AI generated an empty email body."
            )

        logger.info(
            "Generated email draft for subject '%s' "
            "(%d characters)",
            subject,
            len(body),
        )

        return body

    # ============================================================
    # PREPARE AI EMAIL
    # ============================================================

    def prepare_email_from_subject(
        self,
        to_addr: str,
        subject: str,
        model_runner: Optional[
            ModelRunnerProtocol
        ],
    ) -> PreparedEmail:
        """Generate an email draft for human review.

        Nothing is sent from this method.
        """

        to_addr = (
            self._validate_email_address(
                to_addr
            )
        )

        subject = str(
            subject or ""
        ).strip()

        if not subject:

            raise ValueError(
                "Email subject cannot be empty "
                "when generating an AI draft."
            )

        body = (
            self.generate_body_from_subject(
                subject,
                model_runner,
            )
        )

        return PreparedEmail(
            to_addr=to_addr,
            subject=subject,
            body=body,
        )

    # ============================================================
    # LEGACY SMART EMAIL API
    # ============================================================

    def send_email_from_subject(
        self,
        to_addr: str,
        subject: str,
        model_runner: Optional[
            ModelRunnerProtocol
        ],
    ) -> str:
        """Generate AI email but DO NOT send it.

        This function previously generated and immediately sent an
        email. That bypassed the central AURIX trust-token workflow.

        It now returns a review payload only.
        """

        try:

            draft = (
                self.prepare_email_from_subject(
                    to_addr=to_addr,
                    subject=subject,
                    model_runner=model_runner,
                )
            )

        except (
            ValueError,
            EmailGenerationError,
        ) as exc:

            return (
                "Could not prepare the email: "
                f"{exc}"
            )

        logger.info(
            "AI email prepared for review: %s",
            draft.to_addr,
        )

        return (
            "EMAIL_REVIEW_REQUIRED:"
            f"to={draft.to_addr}"
            f"|subject={draft.subject}"
            f"|body={draft.body}"
        )

    # ============================================================
    # CREDENTIAL STORAGE
    # ============================================================

    def _get_credentials(
        self,
    ) -> Optional[
        tuple[str, str]
    ]:
        """Load and decrypt stored SMTP credentials."""

        if (
            not os.path.exists(
                self.cred_file
            )
            or not self.encryptor
        ):
            return None

        try:

            with open(
                self.cred_file,
                "rb",
            ) as file:

                encrypted = file.read()

            decrypted = (
                self.encryptor.decrypt_bytes(
                    encrypted
                )
                .decode(
                    "utf-8"
                )
            )

            parts = decrypted.split(
                "|",
                1,
            )

            if len(parts) != 2:

                logger.error(
                    "Stored SMTP credential "
                    "format is invalid."
                )

                return None

            email_addr = (
                parts[0]
                .strip()
            )

            app_password = (
                parts[1]
                .strip()
            )

            if (
                not email_addr
                or not app_password
            ):

                logger.error(
                    "Stored SMTP credentials "
                    "are incomplete."
                )

                return None

            return (
                email_addr,
                app_password,
            )

        except Exception as exc:

            logger.error(
                "Failed to decrypt SMTP "
                "credentials: %s",
                exc,
            )

            return None

    # ============================================================
    # SAVE CREDENTIALS
    # ============================================================

    def save_credentials(
        self,
        email_addr: str,
        app_password: str,
    ) -> bool:
        """Encrypt and store SMTP credentials."""

        if not self.encryptor:

            logger.error(
                "Encryption engine unavailable."
            )

            return False

        try:

            email_addr = str(
                email_addr or ""
            ).strip()

            app_password = (
                str(
                    app_password or ""
                )
                .replace(
                    " ",
                    "",
                )
                .strip()
            )

            if (
                not email_addr
                or "@" not in email_addr
                or email_addr.startswith("@")
                or email_addr.endswith("@")
            ):

                logger.error(
                    "Invalid email address."
                )

                return False

            if not app_password:

                logger.error(
                    "App password cannot be empty."
                )

                return False

            cred_dir = (
                os.path.dirname(
                    self.cred_file
                )
            )

            if cred_dir:

                os.makedirs(
                    cred_dir,
                    exist_ok=True,
                )

            payload = (
                f"{email_addr}|{app_password}"
                .encode(
                    "utf-8"
                )
            )

            encrypted = (
                self.encryptor.encrypt_bytes(
                    payload
                )
            )

            with open(
                self.cred_file,
                "wb",
            ) as file:

                file.write(
                    encrypted
                )

            logger.info(
                "SMTP credentials saved securely."
            )

            return True

        except Exception as exc:

            logger.error(
                "Failed to save credentials: %s",
                exc,
            )

            return False

    # ============================================================
    # EMAIL DELIVERY
    # ============================================================

    def send_email(
        self,
        to_addr: str,
        subject: str,
        body: str,
        *,
        authorized: bool = False,
    ) -> str:
        """Deliver an email after centralized authorization.

        `authorized=True` must only be supplied by ToolExecutor after
        the PermissionManager trust-token flow succeeds.
        """

        # --------------------------------------------------------
        # SECURITY GATE
        # --------------------------------------------------------

        if not authorized:

            logger.warning(
                "Blocked direct email send outside "
                "ToolExecutor security flow."
            )

            return (
                "Email not sent: centralized AURIX "
                "security approval is required."
            )

        # --------------------------------------------------------
        # NORMALIZATION
        # --------------------------------------------------------

        try:

            to_addr = (
                self._validate_email_address(
                    to_addr
                )
            )

        except ValueError:

            return (
                "Email not sent: recipient address "
                "is missing or invalid."
            )

        subject = str(
            subject or ""
        ).strip()

        body = str(
            body or ""
        ).strip()

        if not body:

            return (
                "Email not sent: "
                "message body is empty."
            )

        # --------------------------------------------------------
        # CREDENTIALS
        # --------------------------------------------------------

        creds = (
            self._get_credentials()
        )

        if not creds:

            logger.info(
                "SMTP credentials unavailable. "
                "Opening draft instead."
            )

            draft_result = (
                self.open_mail_client(
                    to_addr,
                    subject,
                    body,
                )
            )

            return (
                "SMTP credentials are not configured, "
                "so the email was NOT sent automatically. "
                f"{draft_result}"
            )

        sender_email, app_password = creds

        # --------------------------------------------------------
        # MESSAGE
        # --------------------------------------------------------

        msg = EmailMessage()

        msg.set_content(
            body
        )

        msg[
            "Subject"
        ] = subject

        msg[
            "From"
        ] = sender_email

        msg[
            "To"
        ] = to_addr

        # --------------------------------------------------------
        # SMTP
        # --------------------------------------------------------

        try:

            with smtplib.SMTP_SSL(
                "smtp.gmail.com",
                465,
                timeout=10,
            ) as server:

                server.login(
                    sender_email,
                    app_password,
                )

                server.send_message(
                    msg
                )

            logger.info(
                "Email sent successfully to %s",
                to_addr,
            )

            return (
                "Successfully sent email to "
                f"{to_addr} via Gmail SMTP."
            )

        except smtplib.SMTPAuthenticationError as exc:

            logger.error(
                "SMTP authentication failed: %s",
                exc,
            )

            draft_result = (
                self.open_mail_client(
                    to_addr,
                    subject,
                    body,
                )
            )

            return (
                "SMTP authentication failed. "
                "The email was NOT sent automatically. "
                "Check the Gmail address and App Password. "
                f"{draft_result}"
            )

        except Exception as exc:

            logger.error(
                "SMTP delivery failed: %s",
                exc,
            )

            draft_result = (
                self.open_mail_client(
                    to_addr,
                    subject,
                    body,
                )
            )

            return (
                "SMTP delivery failed, so the email "
                "was NOT sent automatically. "
                f"{draft_result}"
            )

    # ============================================================
    # NATIVE MAIL CLIENT
    # ============================================================

    def open_mail_client(
        self,
        to_addr: str,
        subject: str = "",
        body: str = "",
    ) -> str:
        """Open native mail client with a draft.

        This does NOT send the email.
        """

        try:

            to_addr = str(
                to_addr or ""
            ).strip()

            subject = str(
                subject or ""
            )

            body = str(
                body or ""
            )

            query_params = []

            if subject:

                query_params.append(
                    "subject="
                    + urllib.parse.quote(
                        subject
                    )
                )

            if body:

                query_params.append(
                    "body="
                    + urllib.parse.quote(
                        body
                    )
                )

            query = (
                "?"
                + "&".join(
                    query_params
                )
                if query_params
                else ""
            )

            mailto_url = (
                f"mailto:{to_addr}{query}"
            )

            if not hasattr(
                os,
                "startfile",
            ):

                return (
                    "Could not open the native "
                    "mail client on this operating system."
                )

            os.startfile(
                mailto_url
            )

            return (
                "Opened default mail client "
                f"with draft for {to_addr}."
            )

        except Exception as exc:

            logger.error(
                "Failed to open default "
                "mail client: %s",
                exc,
            )

            return (
                f"Failed to open mail client: {exc}"
            )


# ================================================================
# STANDALONE SAFE TEST MODE
# ================================================================

if __name__ == "__main__":

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "[%(name)s] "
            "%(levelname)s: %(message)s"
        ),
    )

    controller = EmailController()

    _gemma_runner = None
    _gemma_load_error = None

    def _get_gemma_for_test_mode():

        global _gemma_runner, _gemma_load_error