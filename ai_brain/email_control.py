"""AURIX AI Brain — Email Controller.

Supports automated email dispatch via secure Gmail SMTP as well as
fallback desktop mail client invocation via the Windows 'mailto:' protocol.

SMTP credentials are encrypted at rest using AURIX's CheckpointEncryptor.
"""

from __future__ import annotations

import os
import sys
import smtplib
import logging
import urllib.parse
from pathlib import Path
from email.message import EmailMessage
from typing import Optional

# Ensure project root is in sys.path for direct execution
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from security.encryption import get_default_encryptor
except ImportError:
    get_default_encryptor = None

logger = logging.getLogger("aurix.ai_brain.email_control")


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

    print("=" * 60)
    print(
        "AURIX Email Control — Standalone Test Mode"
    )
    print("Commands:")
    print(
        "  send <to> | <subject> | <body>  "
        "- Send email via SMTP / mailto"
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
