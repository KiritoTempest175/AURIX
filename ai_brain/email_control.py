"""AURIX AI Brain — Email Controller.

Supports automated email dispatch via secure SMTP (Gmail / custom) as well
as fallback desktop mail client invocation via the Windows 'mailto:' protocol.
"""

from __future__ import annotations

import os
import smtplib
import logging
import urllib.parse
from email.message import EmailMessage
from typing import Optional

try:
    from security.encryption import get_default_encryptor
except ImportError:
    get_default_encryptor = None

logger = logging.getLogger("aurix.ai_brain.email_control")


class EmailController:
    """Handles email composition and delivery via SMTP or native mail client."""

    def __init__(self, cred_file: str = os.path.join("data", "smtp_creds.enc")):
        self.cred_file = cred_file
        self.encryptor = get_default_encryptor() if get_default_encryptor else None

    def _get_credentials(self) -> Optional[tuple[str, str]]:
        if not os.path.exists(self.cred_file) or not self.encryptor:
            return None
        try:
            with open(self.cred_file, "rb") as f:
                encrypted = f.read()
            decrypted = self.encryptor.decrypt(encrypted).decode("utf-8")
            parts = decrypted.split("|", 1)
            if len(parts) == 2:
                return parts[0].strip(), parts[1].strip()
        except Exception as e:
            logger.error("Failed to decrypt SMTP credentials: %s", e)
        return None

    def save_credentials(self, email_addr: str, app_password: str) -> bool:
        """Encrypts and stores SMTP credentials for automated dispatch."""
        if not self.encryptor:
            logger.error("Encryption engine unavailable.")
            return False
        try:
            os.makedirs(os.path.dirname(self.cred_file), exist_ok=True)
            payload = f"{email_addr}|{app_password}".encode("utf-8")
            encrypted = self.encryptor.encrypt(payload)
            with open(self.cred_file, "wb") as f:
                f.write(encrypted)
            return True
        except Exception as e:
            logger.error("Failed to save credentials: %s", e)
            return False

    def send_email(self, to_addr: str, subject: str, body: str) -> str:
        """Sends an email via SMTP, or falls back to the native desktop mail client."""
        creds = self._get_credentials()
        if not creds:
            logger.info("SMTP credentials not found. Falling back to native mail client.")
            return self.open_mail_client(to_addr, subject, body)

        sender_email, app_password = creds
        msg = EmailMessage()
        msg.set_content(body)
        msg["Subject"] = subject
        msg["From"] = sender_email
        msg["To"] = to_addr

        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as server:
                server.login(sender_email, app_password)
                server.send_message(msg)
            logger.info("Email sent successfully to %s", to_addr)
            return f"Successfully sent email to {to_addr} via SMTP."
        except Exception as e:
            logger.error("SMTP delivery failed: %s. Falling back to native mail client.", e)
            return self.open_mail_client(to_addr, subject, body)

    def open_mail_client(self, to_addr: str, subject: str = "", body: str = "") -> str:
        """Opens the user's default Windows mail client with prefilled details."""
        try:
            query_params = []
            if subject:
                query_params.append(f"subject={urllib.parse.quote(subject)}")
            if body:
                query_params.append(f"body={urllib.parse.quote(body)}")
            query = f"?{'&'.join(query_params)}" if query_params else ""
            mailto_url = f"mailto:{to_addr}{query}"

            os.startfile(mailto_url)
            return f"Opened default mail client with draft for {to_addr}."
        except Exception as e:
            logger.error("Failed to open default mail client: %s", e)
            return f"Failed to open mail client: {e}"


# ═══════════════════════════════════════════════════════════════════════════
#  Standalone Interactive Test Mode
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(levelname)s: %(message)s")

    controller = EmailController()
    print("=" * 60)
    print("AURIX Email Control — Standalone Test Mode")
    print("Commands:")
    print("  send <to> | <subject> | <body>  - Send email via SMTP / mailto")
    print("  draft <to> | <subject> | <body> - Open in default mail client")
    print("  setup <email> <app_password>    - Store encrypted SMTP credentials")
    print("  exit                            - Quit")
    print("=" * 60)

    while True:
        try:
            cmd = input("\n[Email Controller] >>> ").strip()
            if not cmd:
                continue
            if cmd.lower() in ["exit", "quit"]:
                break

            if cmd.startswith("setup "):
                parts = cmd[6:].strip().split(maxsplit=1)
                if len(parts) == 2:
                    ok = controller.save_credentials(parts[0], parts[1])
                    print("Credentials saved successfully!" if ok else "Failed to save credentials.")
                else:
                    print("Usage: setup <email> <app_password>")
            elif cmd.startswith("draft "):
                parts = [p.strip() for p in cmd[6:].split("|")]
                to = parts[0] if len(parts) > 0 else ""
                subj = parts[1] if len(parts) > 1 else ""
                body = parts[2] if len(parts) > 2 else ""
                print(controller.open_mail_client(to, subj, body))
            elif cmd.startswith("send "):
                parts = [p.strip() for p in cmd[5:].split("|")]
                to = parts[0] if len(parts) > 0 else ""
                subj = parts[1] if len(parts) > 1 else ""
                body = parts[2] if len(parts) > 2 else ""
                print(controller.send_email(to, subj, body))
            else:
                print("Unknown command. Try: send to@domain.com | Subject | Body")
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")
