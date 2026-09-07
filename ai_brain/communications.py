"""AURIX AI Brain — External Communications Integration.

Implements email sending via SMTP, WhatsApp messaging via UIA automation,
and Phone calls via Phone Link UIA automation.
"""

import logging
import os
import smtplib
from email.message import EmailMessage
import time
from typing import Optional

from core_engine import UiaController
from security.encryption import get_default_encryptor

logger = logging.getLogger("aurix.ai_brain.communications")

class EmailClient:
    def __init__(self):
        self.encryptor = get_default_encryptor()
        self.cred_file = os.path.join("data", "smtp_creds.enc")
        
    def _get_credentials(self) -> Optional[tuple]:
        if not os.path.exists(self.cred_file):
            return None
        try:
            with open(self.cred_file, "rb") as f:
                encrypted = f.read()
            decrypted = self.encryptor.decrypt(encrypted).decode("utf-8")
            # Format expected: email|password
            parts = decrypted.split("|", 1)
            if len(parts) == 2:
                return parts[0], parts[1]
        except Exception as e:
            logger.error(f"Failed to decrypt SMTP credentials: {e}")
        return None

    def send_email(self, to_addr: str, subject: str, body: str) -> str:
        creds = self._get_credentials()
        if not creds:
            # We would normally prompt the user here. For autonomous mode, we return a failure
            # that triggers a credential request prompt via frontend.
            return "CREDENTIALS_MISSING: Email credentials not found. Please provide them to LUNA."
            
        sender_email, app_password = creds
        
        msg = EmailMessage()
        msg.set_content(body)
        msg['Subject'] = subject
        msg['From'] = sender_email
        msg['To'] = to_addr
        
        try:
            # Assuming Gmail for default, can be generalized later
            server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
            server.login(sender_email, app_password)
            server.send_message(msg)
            server.quit()
            logger.info(f"Email sent successfully to {to_addr}")
            return f"Successfully sent email to {to_addr}."
        except Exception as e:
            logger.error(f"SMTP send failed: {e}")
            return f"Failed to send email: {e}"


class WhatsAppClient:
    def __init__(self):
        self.uia = UiaController()

    @staticmethod
    def _open_whatsapp():
        """Ensure WhatsApp is launched and brought to foreground."""
        try:
            import os
            os.startfile("whatsapp:")
        except Exception:
            try:
                from ai_brain.app_control import AppLauncher
                AppLauncher().launch("WhatsApp")
            except Exception:
                import subprocess
                subprocess.Popen(["explorer.exe", "whatsapp://"])
        time.sleep(1.8)

    @staticmethod
    def _paste_clipboard(text: str) -> bool:
        """Set clipboard text reliably using 64-bit safe Windows API with fallback."""
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
            kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
            kernel32.GlobalLock.restype = wintypes.LPVOID
            kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
            kernel32.GlobalUnlock.restype = wintypes.BOOL
            kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]

            user32.OpenClipboard.argtypes = [wintypes.HWND]
            user32.OpenClipboard.restype = wintypes.BOOL
            user32.EmptyClipboard.argtypes = []
            user32.EmptyClipboard.restype = wintypes.BOOL
            user32.SetClipboardData.restype = wintypes.HANDLE
            user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
            user32.CloseClipboard.argtypes = []
            user32.CloseClipboard.restype = wintypes.BOOL

            text_bytes = (text + '\0').encode('utf-16le')
            opened = False
            for _ in range(5):
                if user32.OpenClipboard(None):
                    opened = True
                    break
                time.sleep(0.05)

            if not opened:
                raise RuntimeError("Could not open Windows clipboard")

            try:
                user32.EmptyClipboard()
                h = kernel32.GlobalAlloc(0x0042, len(text_bytes))
                if not h:
                    raise RuntimeError("GlobalAlloc failed")
                ptr = kernel32.GlobalLock(h)
                if not ptr:
                    raise RuntimeError("GlobalLock returned NULL pointer")
                ctypes.memmove(ptr, text_bytes, len(text_bytes))
                kernel32.GlobalUnlock(h)
                user32.SetClipboardData(13, h)  # CF_UNICODETEXT = 13
            finally:
                user32.CloseClipboard()
            return True
        except Exception as e:
            logger.warning(f"Ctypes clipboard failed: {e}; falling back to PowerShell Set-Clipboard")
            try:
                import subprocess
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command", "$input | Set-Clipboard"],
                    input=text, text=True, capture_output=True, timeout=3, check=True
                )
                return True
            except Exception as e2:
                logger.error(f"Clipboard fallback failed: {e2}")
                return False

    def _search_contact(self, contact: str) -> bool:
        """Search and select a contact in WhatsApp."""
        # Try UIA search box first
        found = False
        try:
            if self.uia.set_focus_and_type("WhatsApp", "Search", contact) or \
               self.uia.set_focus_and_type("WhatsApp", "Search or start new chat", contact):
                found = True
                time.sleep(0.8)
                self.uia.send_enter_key("WhatsApp")
                time.sleep(0.8)
        except Exception:
            pass

        if not found:
            import ctypes
            user32 = ctypes.windll.user32
            VK_CONTROL, VK_F, VK_V, VK_RETURN, VK_DOWN = 0x11, 0x46, 0x56, 0x0D, 0x28

            # Ctrl+F to focus search
            user32.keybd_event(VK_CONTROL, 0, 0, 0)
            user32.keybd_event(VK_F, 0, 0, 0)
            time.sleep(0.05)
            user32.keybd_event(VK_F, 0, 2, 0)
            user32.keybd_event(VK_CONTROL, 0, 2, 0)
            time.sleep(0.3)

            # Clear any previous search (Ctrl+A -> Backspace)
            user32.keybd_event(VK_CONTROL, 0, 0, 0)
            user32.keybd_event(0x41, 0, 0, 0)  # A
            time.sleep(0.05)
            user32.keybd_event(0x41, 0, 2, 0)
            user32.keybd_event(VK_CONTROL, 0, 2, 0)
            time.sleep(0.05)
            user32.keybd_event(0x08, 0, 0, 0)  # Backspace
            time.sleep(0.05)
            user32.keybd_event(0x08, 0, 2, 0)
            time.sleep(0.1)

            # Paste contact name
            if self._paste_clipboard(contact):
                user32.keybd_event(VK_CONTROL, 0, 0, 0)
                user32.keybd_event(VK_V, 0, 0, 0)
                time.sleep(0.05)
                user32.keybd_event(VK_V, 0, 2, 0)
                user32.keybd_event(VK_CONTROL, 0, 2, 0)
            time.sleep(0.7)

            # Press Enter to open the conversation
            user32.keybd_event(VK_RETURN, 0, 0, 0)
            time.sleep(0.05)
            user32.keybd_event(VK_RETURN, 0, 2, 0)
            time.sleep(0.4)

            # Fallback if focus is on list: Down Arrow + Enter
            user32.keybd_event(VK_DOWN, 0, 0, 0)
            time.sleep(0.05)
            user32.keybd_event(VK_DOWN, 0, 2, 0)
            time.sleep(0.1)
            user32.keybd_event(VK_RETURN, 0, 0, 0)
            time.sleep(0.05)
            user32.keybd_event(VK_RETURN, 0, 2, 0)
            time.sleep(0.8)
        return True

    def send_message(self, contact: str, message: str) -> str:
        """Automate WhatsApp Desktop to search a contact and send a message."""
        try:
            self._open_whatsapp()
            self._search_contact(contact)

            # Try UIA input box
            sent = False
            try:
                if self.uia.set_focus_and_type("WhatsApp", "Type a message", message):
                    time.sleep(0.3)
                    self.uia.send_enter_key("WhatsApp")
                    sent = True
            except Exception:
                pass

            if not sent:
                # Fallback: paste message directly and press Enter
                import ctypes
                user32 = ctypes.windll.user32
                VK_CONTROL, VK_V, VK_RETURN = 0x11, 0x56, 0x0D

                if self._paste_clipboard(message):
                    user32.keybd_event(VK_CONTROL, 0, 0, 0)
                    user32.keybd_event(VK_V, 0, 0, 0)
                    time.sleep(0.05)
                    user32.keybd_event(VK_V, 0, 2, 0)
                    user32.keybd_event(VK_CONTROL, 0, 2, 0)
                time.sleep(0.3)

                user32.keybd_event(VK_RETURN, 0, 0, 0)
                time.sleep(0.05)
                user32.keybd_event(VK_RETURN, 0, 2, 0)

            logger.info(f"WhatsApp message sent to {contact}: {message}")
            return f'Sent message to {contact}: "{message}"'
        except Exception as e:
            logger.error(f"WhatsApp message sending failed: {e}")
            return f"Failed to send message to {contact}: {e}"

    def make_call(self, contact: str, message: str = "") -> str:
        """Automate WhatsApp Desktop to call a contact and speak the message."""
        try:
            self._open_whatsapp()
            self._search_contact(contact)

            # Initiate call via UIA or shortcut
            called = False
            try:
                if self.uia.invoke_control("WhatsApp", "Voice call") or \
                   self.uia.invoke_control("WhatsApp", "Audio call") or \
                   self.uia.invoke_control("WhatsApp", "Start voice call") or \
                   self.uia.invoke_control("WhatsApp", "Call"):
                    called = True
            except Exception:
                pass

            if not called:
                # Shortcut for Voice Call in WhatsApp Desktop
                import ctypes
                user32 = ctypes.windll.user32
                VK_CONTROL, VK_SHIFT, VK_C = 0x11, 0x10, 0x43
                user32.keybd_event(VK_CONTROL, 0, 0, 0)
                user32.keybd_event(VK_SHIFT, 0, 0, 0)
                user32.keybd_event(VK_C, 0, 0, 0)
                time.sleep(0.05)
                user32.keybd_event(VK_C, 0, 2, 0)
                user32.keybd_event(VK_SHIFT, 0, 2, 0)
                user32.keybd_event(VK_CONTROL, 0, 2, 0)

            time.sleep(1.2)

            # If a message was specified in quotes, speak it
            if message:
                try:
                    from native_ui.audio import speak
                    speak(message)
                except Exception as tts_err:
                    logger.warning(f"Failed to speak call message via TTS: {tts_err}")

            logger.info(f"WhatsApp call initiated to {contact} (message='{message}')")
            spoken_part = f' and said: "{message}"' if message else ""
            return f'Initiated call to {contact}{spoken_part}.'
        except Exception as e:
            logger.error(f"WhatsApp calling failed: {e}")
            return f"Failed to call {contact}: {e}"


class PhoneLinkClient:
    def __init__(self):
        self.uia = UiaController()

    def make_call(self, contact: str) -> str:
        """Automate Phone Link to make a phone call."""
        try:
            import subprocess
            subprocess.Popen(["explorer", "ms-phone:"])
            time.sleep(2.0)
            
            if not self.uia.find_window_by_title("Phone Link"):
                return "Phone Link window not found."
                
            # Assume Phone Link has a "Search contacts" or similar
            success = self.uia.set_focus_and_type("Phone Link", "Search", contact)
            if not success:
                success = self.uia.set_focus_and_type("Phone Link", "Search contacts", contact)
                
            if not success:
                return "Failed to find Phone Link search box."
                
            time.sleep(1.0)
            self.uia.send_enter_key("Phone Link")
            time.sleep(1.0)
            
            # Find and invoke the Call button
            # This is highly dependent on the exact UIA tree of Phone Link
            success = self.uia.invoke_control("Phone Link", "Call")
            if not success:
                success = self.uia.invoke_control("Phone Link", "Audio call")
                
            if not success:
                # Fallback to just pressing enter again if the contact is selected
                self.uia.send_enter_key("Phone Link")
                
            logger.info(f"Phone call initiated to {contact}")
            return f"Initiated phone call to {contact} via Phone Link."
        except Exception as e:
            logger.error(f"Phone Link automation failed: {e}")
            return f"Failed to initiate phone call: {e}"
