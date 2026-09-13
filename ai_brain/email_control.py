"""AURIX AI Brain — Email Controller.

Supports automated email dispatch via secure Gmail SMTP as well as
fallback desktop mail client invocation via the Windows 'mailto:' protocol.

SMTP credentials are encrypted at rest using AURIX's CheckpointEncryptor.

Rev. 2 -- adds AI-generated email bodies: give it just a subject line and a
model runner (e.g. the project's Gemma 4 E4B inference wrapper), and it
writes and sends the body itself, via generate_body_from_subject() /
send_email_from_subject(). Everything else in this file is unchanged from
before.

SAFETY NOTE, stated plainly rather than silently decided: send_email_from_subject()
does exactly what was asked -- generate a body from the subject, then send it
-- including over real SMTP with NO review step, if credentials are
configured. That's a real difference from the confirm-before-send pattern
used for WhatsApp messages/calls elsewhere in this project (see
ai_brain/dispatcher.py's two-turn confirmation flow) -- there, nothing
irreversible happens until the user explicitly says yes to what will
actually be sent. This method does not have that step. If you want the same
protection here, wire send_email_from_subject() through a similar
prepare/confirm/execute split before hooking it into the dispatcher, rather
than calling it directly on a single user utterance. Not built here because
it wasn't what was asked -- flagging it so the gap is a known choice, not an
overlooked one.
"""

from __future__ import annotations

import os
import sys
import smtplib
import logging
import urllib.parse
from pathlib import Path
from email.message import EmailMessage
from typing import Optional, Protocol

# Ensure project root is in sys.path for direct execution
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from security.encryption import get_default_encryptor
except ImportError:
    get_default_encryptor = None

logger = logging.getLogger("aurix.ai_brain.email_control")


class ModelRunnerProtocol(Protocol):
    """Matches the Gemma 4 E4B inference wrapper's interface as already used
    elsewhere in this project (see frontend.py's self.gemma_runner usage)."""
    def format_chat_prompt(self, user_message: str) -> str: ...
    def generate_response(self, prompt: str) -> str: ...


class EmailGenerationError(RuntimeError):
    """Raised when the AI body-generation step fails or produces nothing
    usable -- kept distinct from send/SMTP errors so callers can tell
    'couldn't write it' apart from 'wrote it, couldn't send it'."""
    pass


_BODY_GENERATION_INSTRUCTION = (
    "Write a clear, appropriately concise email body for an email with this "
    "subject line: \"{subject}\". Output ONLY the body text itself, ready to "
    "send -- no subject line repeated back, no placeholder brackets like "
    "[Your Name], and no meta-commentary about the email. Match the tone to "
    "what the subject implies (a casual note reads casually, a formal "
    "request reads formally)."
)


class EmailController:
    """Handles email composition and delivery via SMTP or native mail client."""

    def __init__(
        self,
        cred_file: str = os.path.join("data", "smtp_creds.enc"),
    ) -> None:
        self.cred_file = cred_file
        self.encryptor = (
            get_default_encryptor()
            if get_default_encryptor
            else None
        )

    # ============================================================
    # AI BODY GENERATION (new)
    # ============================================================

    def generate_body_from_subject(
        self,
        subject: str,
        model_runner: Optional[ModelRunnerProtocol],
    ) -> str:
        """Uses `model_runner` to write a full email body from just a
        subject line. Raises ValueError/EmailGenerationError rather than
        returning an empty/placeholder string on failure, so callers can't
        accidentally send a blank or broken email without noticing.
        """
        subject = str(subject or "").strip()
        if not subject:
            raise ValueError("Cannot generate an email body from an empty subject.")

        if model_runner is None:
            raise EmailGenerationError("No AI model is available to generate the email body.")

        prompt_text = _BODY_GENERATION_INSTRUCTION.format(subject=subject)
        try:
            prompt = model_runner.format_chat_prompt(user_message=prompt_text)
            body = model_runner.generate_response(prompt)
        except Exception as e:
            raise EmailGenerationError(f"AI email generation failed: {e}") from e

        body = (body or "").strip()
        if not body:
            raise EmailGenerationError("AI generated an empty email body.")

        logger.info("Generated email body for subject '%s' (%d chars)", subject, len(body))
        return body

    def send_email_from_subject(
        self,
        to_addr: str,
        subject: str,
        model_runner: Optional[ModelRunnerProtocol],
    ) -> str:
        """Generates the body from `subject` via `model_runner`, then sends
        it through the existing send_email() path (SMTP if configured,
        mailto draft fallback otherwise). See the module docstring's SAFETY
        NOTE -- there is no confirmation step here; this sends exactly what
        the AI wrote, over SMTP, with no review, if credentials exist.
        """
        try:
            body = self.generate_body_from_subject(subject, model_runner)
        except (ValueError, EmailGenerationError) as e:
            return f"Could not generate the email: {e}"

        return self.send_email(to_addr, subject, body)

    # ============================================================
    # CREDENTIAL STORAGE
    # ============================================================

    def _get_credentials(
        self,
    ) -> Optional[tuple[str, str]]:
        """Load and decrypt stored SMTP credentials."""

        if (
            not os.path.exists(self.cred_file)
            or not self.encryptor
        ):
            return None

        try:
            with open(self.cred_file, "rb") as f:
                encrypted = f.read()

            decrypted = self.encryptor.decrypt_bytes(
                encrypted
            ).decode("utf-8")

            parts = decrypted.split("|", 1)

            if len(parts) != 2:
                logger.error(
                    "Stored SMTP credential format is invalid."
                )
                return None

            email_addr = parts[0].strip()
            app_password = parts[1].strip()

            if not email_addr or not app_password:
                logger.error(
                    "Stored SMTP credentials are incomplete."
                )
                return None

            return (
                email_addr,
                app_password,
            )

        except Exception as e:
            logger.error(
                "Failed to decrypt SMTP credentials: %s",
                e,
            )
            return None

    def save_credentials(
        self,
        email_addr: str,
        app_password: str,
    ) -> bool:
        """Encrypt and store SMTP credentials securely."""

        if not self.encryptor:
            logger.error(
                "Encryption engine unavailable."
            )
            return False

        try:
            email_addr = str(email_addr).strip()

            # Google displays App Passwords with spaces.
            # SMTP expects the actual 16-character token.
            app_password = (
                str(app_password)
                .replace(" ", "")
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

            cred_dir = os.path.dirname(
                self.cred_file
            )

            if cred_dir:
                os.makedirs(
                    cred_dir,
                    exist_ok=True,
                )

            payload = (
                f"{email_addr}|{app_password}"
            ).encode("utf-8")

            encrypted = (
                self.encryptor.encrypt_bytes(
                    payload
                )
            )

            with open(
                self.cred_file,
                "wb",
            ) as f:
                f.write(encrypted)

            logger.info(
                "SMTP credentials saved securely."
            )

            return True

        except Exception as e:
            logger.error(
                "Failed to save credentials: %s",
                e,
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
    ) -> str:
        """Send an email via Gmail SMTP.

        If SMTP credentials are unavailable or SMTP delivery fails,
        AURIX opens the user's default mail client with a prefilled draft.
        """

        to_addr = str(to_addr).strip()
        subject = str(subject or "").strip()
        body = str(body or "").strip()

        if (
            not to_addr
            or "@" not in to_addr
            or to_addr.startswith("@")
            or to_addr.endswith("@")
        ):
            return (
                "Email not sent: recipient address "
                "is missing or invalid."
            )

        if not body:
            return (
                "Email not sent: message body is empty."
            )

        creds = self._get_credentials()

        if not creds:
            logger.info(
                "SMTP credentials not found. "
                "Opening native mail client draft."
            )

            draft_result = self.open_mail_client(
                to_addr,
                subject,
                body,
            )

            return (
                "SMTP credentials are not configured, "
                "so the email was NOT sent automatically. "
                f"{draft_result}"
            )

        sender_email, app_password = creds

        msg = EmailMessage()
        msg.set_content(body)
        msg["Subject"] = subject
        msg["From"] = sender_email
        msg["To"] = to_addr

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

                server.send_message(msg)

            logger.info(
                "Email sent successfully to %s",
                to_addr,
            )

            return (
                f"Successfully sent email to "
                f"{to_addr} via Gmail SMTP."
            )

        except smtplib.SMTPAuthenticationError as e:
            logger.error(
                "SMTP authentication failed: %s",
                e,
            )

            draft_result = self.open_mail_client(
                to_addr,
                subject,
                body,
            )

            return (
                "SMTP authentication failed. "
                "The email was NOT sent automatically. "
                "Check the Gmail address and App Password. "
                f"{draft_result}"
            )

        except Exception as e:
            logger.error(
                "SMTP delivery failed: %s",
                e,
            )

            draft_result = self.open_mail_client(
                to_addr,
                subject,
                body,
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
        """Open the user's default Windows mail client with a prefilled draft."""

        try:
            to_addr = str(to_addr).strip()
            subject = str(subject or "")
            body = str(body or "")

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
                + "&".join(query_params)
                if query_params
                else ""
            )

            mailto_url = (
                f"mailto:{to_addr}{query}"
            )

            if not hasattr(os, "startfile"):
                return (
                    "Could not open the native mail "
                    "client on this operating system."
                )

            os.startfile(mailto_url)

            return (
                f"Opened default mail client "
                f"with draft for {to_addr}."
            )

        except Exception as e:
            logger.error(
                "Failed to open default mail client: %s",
                e,
            )

            return (
                f"Failed to open mail client: {e}"
            )


# ================================================================
# STANDALONE INTERACTIVE TEST MODE
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

    # Lazy-import the real Gemma runner, same graceful-fallback pattern
    # frontend.py uses -- this test harness has no GUI/session around it, so
    # there's no other source of a model_runner to test send_email_from_subject
    # against. If ai_engine isn't importable standalone (e.g. run from a
    # different working directory, or the model isn't downloaded yet), the
    # 'smart' command below reports that clearly instead of crashing.
    _gemma_runner = None
    _gemma_load_error = None

    def _get_gemma_for_test_mode():
        global _gemma_runner, _gemma_load_error
        if _gemma_runner is not None or _gemma_load_error is not None:
            return _gemma_runner
        try:
            from ai_engine.inference.gemma_e4b import get_default_gemma_runner
            _gemma_runner = get_default_gemma_runner()
            return _gemma_runner
        except Exception as e:
            _gemma_load_error = str(e)
            return None

    print("=" * 60)
    print(
        "AURIX Email Control — Standalone Test Mode"
    )
    print("Commands:")
    print(
        "  send <to> | <subject> | <body>  "
        "- Send email via SMTP / mailto (all 3 parts required, pipe-separated)"
    )
    print(
        "  smart <to> | <subject>          "
        "- AI writes the body from just the subject, then sends it"
    )
    print(
        "  draft <to> | <subject> | <body> "
        "- Open in default mail client"
    )
    print(
        "  setup <email> <app_password>    "
        "- Store encrypted SMTP credentials"
    )
    print(
        "  status                          "
        "- Check whether SMTP credentials exist"
    )
    print(
        "  exit                            "
        "- Quit"
    )
    print(
        "\nNote the '|' separators above are required -- "
        "'send a@b.com hello there' will NOT work; "
        "use 'send a@b.com | hello | there' instead."
    )
    print("=" * 60)

    while True:
        try:
            cmd = input(
                "\n[Email Controller] >>> "
            ).strip()

            if not cmd:
                continue

            if cmd.lower() in {
                "exit",
                "quit",
            }:
                break

            if cmd.lower() == "status":
                creds = (
                    controller._get_credentials()
                )

                if creds:
                    print(
                        "SMTP credentials are configured "
                        f"for: {creds[0]}"
                    )
                else:
                    print(
                        "SMTP credentials are not configured."
                    )

            elif cmd.startswith("setup "):

                parts = (
                    cmd[6:]
                    .strip()
                    .split(maxsplit=1)
                )

                if len(parts) == 2:

                    ok = (
                        controller.save_credentials(
                            parts[0],
                            parts[1],
                        )
                    )

                    print(
                        "Credentials saved successfully!"
                        if ok
                        else "Failed to save credentials."
                    )

                else:
                    print(
                        "Usage: "
                        "setup <email> <app_password>"
                    )

            elif cmd.startswith("smart "):

                parts = [
                    p.strip()
                    for p in cmd[6:].split("|", 1)
                ]

                if len(parts) != 2 or not parts[0] or not parts[1]:
                    print(
                        "Usage: smart <to> | <subject>  "
                        "(both parts required, separated by '|')"
                    )
                else:
                    to, subj = parts
                    runner = _get_gemma_for_test_mode()
                    if runner is None:
                        print(
                            f"Could not load the Gemma runner for AI generation: "
                            f"{_gemma_load_error}. (This test harness needs "
                            f"ai_engine.inference.gemma_e4b to be importable and "
                            f"the model available -- run this from the project "
                            f"root, with the model downloaded, or test this "
                            f"feature from within frontend.py instead.)"
                        )
                    else:
                        print(f"Asking Gemma to write the body for subject: {subj!r}...")
                        print(controller.send_email_from_subject(to, subj, runner))

            elif cmd.startswith("draft "):

                parts = [
                    p.strip()
                    for p in cmd[6:].split(
                        "|",
                        2,
                    )
                ]

                to = (
                    parts[0]
                    if len(parts) > 0
                    else ""
                )

                subj = (
                    parts[1]
                    if len(parts) > 1
                    else ""
                )

                body = (
                    parts[2]
                    if len(parts) > 2
                    else ""
                )

                print(
                    controller.open_mail_client(
                        to,
                        subj,
                        body,
                    )
                )

            elif cmd.startswith("send "):

                parts = [
                    p.strip()
                    for p in cmd[5:].split(
                        "|",
                        2,
                    )
                ]

                if len(parts) != 3 or not all(parts):
                    print(
                        "Usage: send <to> | <subject> | <body>  "
                        "(all 3 parts required, separated by '|')"
                    )
                else:
                    to, subj, body = parts
                    print(
                        controller.send_email(
                            to,
                            subj,
                            body,
                        )
                    )

            else:
                print(
                    "Unknown command. Try: "
                    "send to@domain.com | Subject | Body"
                )

        except KeyboardInterrupt:
            break

        except Exception as e:
            print(
                f"Error: {e}"
            )