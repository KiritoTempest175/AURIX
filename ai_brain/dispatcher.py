"""AURIX AI Brain -- Central Intent Dispatcher.

Connects all implemented cognitive & system actuators:
1. App Control: AppLauncher & AppCloser (apps, folders, files, URLs, PATH, Windows search)
2. Media Player: Spotify & YouTube Music (play/pause, skip, prev, DJ, search & play)
3. Web Search: Chrome Guest Mode visual search
4. YouTube Video: Playback in Chrome, video info, downloads (yt-dlp), transcript summaries, trending
5. File Controller: Strict jailed C: user folders, view/list/create/delete/move/copy/rename
6. Email Controller: Secure SMTP or native Windows mailto: client
7. WhatsApp & Calling: WhatsApp message automation and voice/video calling
8. Direct Shell Commands: cmd: / run:
"""

from __future__ import annotations

import logging
import re
import subprocess
from typing import Optional, Tuple

from ai_brain.app_control import AppCloser, AppLauncher
from ai_brain.email_control import EmailController
from ai_brain.file_control import FileController
from ai_brain.media_player import MediaPlayer
from ai_brain.message_control import (
    ActionResult,
    PendingWhatsAppAction,
    WhatsAppController,
    WhatsAppLaunchError,
    WhatsAppUIError,
)
from ai_brain.web_search import WebSearcher
from ai_brain.youtube_video import youtube_video

logger = logging.getLogger("aurix.ai_brain.dispatcher")

_AFFIRMATIVE = frozenset({
    "yes", "yeah", "yep", "confirm", "confirmed", "do it", "send it", "go ahead", "sure", "ok", "okay",
})
_NEGATIVE = frozenset({
    "no", "nope", "cancel", "cancelled", "stop", "don't", "dont", "never mind", "nevermind",
})


class BrainDispatcher:
    """Central brain router that parses intent and dispatches to specialized handlers."""

    _WAKE_PHRASES = frozenset({
        "luna", "hey luna", "aurix", "wake up", "call luna", "hello", "hi luna", "hello luna",
    })

    def __init__(self, uia_actuator=None, process_checker=None) -> None:
        self.launcher = AppLauncher()
        self.closer = AppCloser()
        self.media_player = MediaPlayer()
        self.web_searcher = WebSearcher()
        self.file_controller = FileController(interactive_confirmations=False)
        self.email_controller = EmailController()

        checker = process_checker or _DefaultProcessChecker()
        self._whatsapp: WhatsAppController = WhatsAppController(
            actuator=uia_actuator,
            app_launcher=self.launcher,
            process_checker=checker,
        )

        self._call_manager = None
        self._pending_whatsapp: Optional[PendingWhatsAppAction] = None

        logger.info("BrainDispatcher initialized with full subsystem suite.")

    @property
    def call_manager(self):
        if self._call_manager is None:
            try:
                from ai_brain.call_control import CallManager
                self._call_manager = CallManager()
            except Exception as e:
                logger.warning("CallManager unavailable: %s", e)
        return self._call_manager

    def dispatch(self, text: str) -> Tuple[str, bool]:
        if not text or not text.strip():
            return ("", False)

        trimmed = text.strip()
        lower = trimmed.lower().rstrip(".,!?")

        # ── 1. Pending WhatsApp confirmation ──────────────────────────────
        if self._pending_whatsapp is not None:
            return self._resolve_pending_whatsapp(lower)

        # ── 2. Wake / greeting phrases ────────────────────────────────────
        if lower in self._WAKE_PHRASES:
            return ("AURIX Executive online and listening. Ready for your command.", True)

        # ── 3. Shell command execution (cmd: / run:) ──────────────────────
        if lower.startswith("cmd:") or lower.startswith("run:"):
            raw_cmd = trimmed.split(":", 1)[1].strip()
            return self._handle_shell(raw_cmd)

        # ── 4. Media Player Controls (Play/Pause, Next, Prev, DJ) ─────────
        if lower in ("pause", "pause music", "pause song", "stop music", "resume", "resume music", "play/pause"):
            return (self.media_player.toggle_playback(), True)

        if lower in ("next song", "next track", "skip song", "skip track", "skip"):
            return (self.media_player.next_track(), True)

        if lower in ("previous song", "prev song", "previous track", "prev track", "last song", "back song"):
            return (self.media_player.prev_track(), True)

        if lower in ("spotify dj", "play spotify dj", "start spotify dj"):
            return (self.media_player.start_spotify_dj(), True)

        # ── 5. YouTube Video Controls ─────────────────────────────────────
        # "play ... on youtube"
        if ("play " in lower and " on youtube" in lower) or lower.startswith("youtube "):
            query = trimmed
            if lower.startswith("youtube "):
                query = trimmed[8:].strip()
            elif " on youtube" in lower:
                # Extract part between "play " and " on youtube"
                m = re.search(r"play\s+(.*?)\s+on\s+youtube", trimmed, re.IGNORECASE)
                if m:
                    query = m.group(1).strip()
            if query:
                res = youtube_video({"action": "play", "query": query})
                return (res, True)

        if lower.startswith("download youtube ") or lower.startswith("download video "):
            url = trimmed.split(maxsplit=2)[-1].strip()
            return (youtube_video({"action": "download", "url": url}), True)

        if lower.startswith("summarize youtube ") or lower.startswith("summarize video "):
            url = trimmed.split(maxsplit=2)[-1].strip()
            return (youtube_video({"action": "summarize", "url": url}), True)

        if lower.startswith("youtube info ") or lower.startswith("video info "):
            url = trimmed.split(maxsplit=2)[-1].strip()
            return (youtube_video({"action": "info", "url": url}), True)

        if lower in ("youtube trending", "trending on youtube", "trending videos"):
            return (youtube_video({"action": "trending"}), True)

        # ── 6. Music Playback (Spotify / YouTube Music) ───────────────────
        if lower.startswith("play "):
            body = trimmed[5:].strip()
            body_lower = body.lower()
            if body_lower.endswith(" on spotify"):
                song = body[:-11].strip()
                return (self.media_player.play(song, service="spotify"), True)
            if body_lower.endswith(" on youtube music") or body_lower.endswith(" on yt music"):
                song = re.sub(r"\s+on\s+(youtube|yt)\s+music$", "", body, flags=re.IGNORECASE).strip()
                return (self.media_player.play(song, service="youtube music"), True)
            if body_lower.startswith("music ") or body_lower.startswith("song "):
                song = body.split(maxsplit=1)[-1].strip()
                return (self.media_player.play(song, service="spotify"), True)

        # ── 7. Web Search ─────────────────────────────────────────────────
        search_prefixes = (
            "search the web for ", "search web for ", "search google for ",
            "search for ", "google ", "browse ", "search "
        )
        for sp in search_prefixes:
            if lower.startswith(sp):
                q = trimmed[len(sp):].strip()
                if q:
                    return (self.web_searcher.search(q), True)

        # ── 8. Email Management ───────────────────────────────────────────
        parsed_email = self._try_parse_email(trimmed)
        if parsed_email is not None:
            to_addr, subject, body = parsed_email
            return (self.email_controller.send_email(to_addr, subject, body), True)

        # ── 9. WhatsApp Messaging ─────────────────────────────────────────
        parsed_msg = self._try_parse_whatsapp_message(trimmed)
        if parsed_msg is not None:
            contact, message = parsed_msg
            return self._start_whatsapp_message(contact, message)

        # ── 10. WhatsApp Calling ──────────────────────────────────────────
        parsed_call = self._try_parse_whatsapp_call(lower, trimmed)
        if parsed_call is not None:
            contact, video = parsed_call
            return self._start_whatsapp_call(contact, video)

        # ── 11. File & Folder Operations ──────────────────────────────────
        file_res = self._try_handle_file_op(lower, trimmed)
        if file_res is not None:
            return (file_res, True)

        # ── 12. Close Application ─────────────────────────────────────────
        close_prefixes = ("close ", "terminate ", "kill ", "quit ", "exit app ")
        for cp in close_prefixes:
            if lower.startswith(cp):
                target = trimmed[len(cp):].strip()
                if target:
                    return (self.closer.close(target), True)

        # ── 13. Open / Launch Application ─────────────────────────────────
        open_prefixes = ("open ", "launch ", "start ", "run app ")
        for op in open_prefixes:
            if lower.startswith(op):
                target = trimmed[len(op):].strip()
                if target:
                    return (self.launcher.launch(target), True)

        # Standalone app aliases
        if lower in (
            "notepad", "calc", "calculator", "explorer", "file explorer",
            "chrome", "google chrome", "spotify", "vscode", "vs code",
            "terminal", "cmd", "task manager", "settings", "paint"
        ):
            return (self.launcher.launch(lower), True)

        # ── 14. Fallback 'play <query>' for general song playback ─────────
        if lower.startswith("play ") and not any(k in lower for k in ("video", "youtube", "folder", "file")):
            song = trimmed[5:].strip()
            if song:
                return (self.media_player.play(song, service="spotify"), True)

        return ("", False)

    # ── WhatsApp Parser & Dispatch ───────────────────────────────────────

    def _try_parse_whatsapp_message(self, trimmed: str) -> Optional[Tuple[str, str]]:
        lower = trimmed.lower()
        for prefix in ("message ", "text ", "whatsapp "):
            if not lower.startswith(prefix):
                continue
            body = trimmed[len(prefix):]
            body_lower = body.lower()

            if " saying " in body_lower:
                idx = body_lower.index(" saying ")
                contact = body[:idx].strip()
                message = body[idx + len(" saying "):].strip()
                if contact and message:
                    return contact, message

            for open_q, close_q in (('"', '"'), ("'", "'"), ("“", "”"), ("‘", "’")):
                if open_q in body and body.rstrip().endswith(close_q):
                    q_start = body.index(open_q)
                    contact = body[:q_start].strip()
                    message = body[q_start + 1: body.rstrip().rfind(close_q)].strip()
                    if contact and message:
                        return contact, message

            if ":" in body:
                idx = body.index(":")
                contact = body[:idx].strip()
                message = body[idx + 1:].strip()
                if contact and message:
                    return contact, message

        return None

    def _try_parse_whatsapp_call(self, lower: str, trimmed: str) -> Optional[Tuple[str, bool]]:
        if lower.startswith("video call "):
            contact = trimmed[len("video call "):].strip()
            return (contact, True) if contact else None
        if lower.startswith("call "):
            contact = trimmed[len("call "):].strip()
            return (contact, False) if contact else None
        if lower.startswith("phone "):
            contact = trimmed[len("phone "):].strip()
            return (contact, False) if contact else None
        return None

    def _start_whatsapp_message(self, contact: str, message: str) -> Tuple[str, bool]:
        if self._whatsapp is None:
            return ("WhatsApp automation isn't set up yet on this system.", True)
        try:
            pending = self._whatsapp.prepare_message(contact, message)
        except (WhatsAppLaunchError, WhatsAppUIError) as e:
            return (f"Couldn't prepare that message: {e}", True)

        self._pending_whatsapp = pending
        return (
            f"Found {pending.matched_contact} on WhatsApp. Send: \"{pending.message}\"? "
            f"Say yes to confirm or no to cancel.",
            True,
        )

    def _start_whatsapp_call(self, contact: str, video: bool) -> Tuple[str, bool]:
        if self._whatsapp is None:
            return ("WhatsApp automation isn't set up yet on this system.", True)
        try:
            pending = self._whatsapp.prepare_call(contact, video=video)
        except (WhatsAppLaunchError, WhatsAppUIError) as e:
            return (f"Couldn't prepare that call: {e}", True)

        self._pending_whatsapp = pending
        kind = "video call" if video else "voice call"
        return (
            f"Found {pending.matched_contact} on WhatsApp. Place a {kind}? "
            f"Say yes to confirm or no to cancel.",
            True,
        )

    def _resolve_pending_whatsapp(self, lower: str) -> Tuple[str, bool]:
        pending = self._pending_whatsapp
        if lower in _AFFIRMATIVE:
            self._pending_whatsapp = None
            result: ActionResult = self._whatsapp.execute(pending)
            if result.status == "error":
                return (f"That didn't go through: {result.detail}", True)
            return (result.detail, True)

        if lower in _NEGATIVE:
            self._pending_whatsapp = None
            kind = "message" if pending.kind == "message" else "call"
            return (f"Okay, {kind} to {pending.matched_contact} cancelled.", True)

        logger.info("Pending WhatsApp %s to '%s' abandoned.", pending.kind, pending.matched_contact)
        self._pending_whatsapp = None
        return self.dispatch(lower)

    # ── Email Parser ─────────────────────────────────────────────────────

    def _try_parse_email(self, trimmed: str) -> Optional[Tuple[str, str, str]]:
        lower = trimmed.lower()
        if not (lower.startswith("email ") or lower.startswith("send email to ") or lower.startswith("draft email to ")):
            return None

        # Strip prefix
        text = trimmed
        for p in ("draft email to ", "send email to ", "email "):
            if lower.startswith(p):
                text = trimmed[len(p):].strip()
                break

        # Check format: "to@domain.com saying <message>"
        # or "to@domain.com subject <subject> body <message>"
        # or "to@domain.com | <subject> | <message>"
        if "|" in text:
            parts = [p.strip() for p in text.split("|")]
            to_addr = parts[0]
            subject = parts[1] if len(parts) > 1 else "AURIX Notification"
            body = parts[2] if len(parts) > 2 else ""
            return to_addr, subject, body

        m_saying = re.search(r"^(.*?)\s+saying\s+(.*)$", text, re.IGNORECASE)
        if m_saying:
            to_addr = m_saying.group(1).strip()
            body = m_saying.group(2).strip()
            return to_addr, "Message from AURIX", body

        m_subj_body = re.search(r"^(.*?)\s+subject\s+(.*?)\s+body\s+(.*)$", text, re.IGNORECASE)
        if m_subj_body:
            to_addr = m_subj_body.group(1).strip()
            subj = m_subj_body.group(2).strip()
            body = m_subj_body.group(3).strip()
            return to_addr, subj, body

        # Just recipient: "email user@example.com"
        to_addr = text.strip()
        if to_addr:
            return to_addr, "AURIX Draft", ""

        return None

    # ── File & Folder Operations ─────────────────────────────────────────

    def _try_handle_file_op(self, lower: str, trimmed: str) -> Optional[str]:
        # List files
        for p in ("list files in ", "list files on ", "show files in ", "list directory ", "dir ", "ls "):
            if lower.startswith(p):
                target = trimmed[len(p):].strip() or "desktop"
                return self.file_controller.list_directory(target)

        # Read file
        for p in ("read file ", "view file ", "show file ", "cat "):
            if lower.startswith(p):
                target = trimmed[len(p):].strip()
                return self.file_controller.read_file(target)

        # Create folder
        for p in ("create folder ", "make folder ", "make directory ", "new folder ", "mkdir "):
            if lower.startswith(p):
                target = trimmed[len(p):].strip()
                return self.file_controller.create_folder(target)

        # Create / write file
        for p in ("create file ", "write file "):
            if lower.startswith(p):
                rest = trimmed[len(p):].strip()
                if " with content " in rest.lower():
                    parts = re.split(r"\s+with content\s+", rest, flags=re.IGNORECASE)
                    return self.file_controller.write_file(parts[0].strip(), parts[1].strip())
                if " saying " in rest.lower():
                    parts = re.split(r"\s+saying\s+", rest, flags=re.IGNORECASE)
                    return self.file_controller.write_file(parts[0].strip(), parts[1].strip())
                return self.file_controller.write_file(rest, "")

        # Delete item
        for p in ("delete file ", "delete folder ", "remove file ", "remove folder ", "trash "):
            if lower.startswith(p):
                target = trimmed[len(p):].strip()
                return self.file_controller.delete_item(target, visual=False)

        # Copy item
        if lower.startswith("copy file ") or lower.startswith("copy "):
            prefix = "copy file " if lower.startswith("copy file ") else "copy "
            rest = trimmed[len(prefix):].strip()
            if " to " in rest.lower():
                parts = re.split(r"\s+to\s+", rest, flags=re.IGNORECASE)
                return self.file_controller.copy_item(parts[0].strip(), parts[1].strip(), visual=False)

        # Move item
        if lower.startswith("move file ") or lower.startswith("move "):
            prefix = "move file " if lower.startswith("move file ") else "move "
            rest = trimmed[len(prefix):].strip()
            if " to " in rest.lower():
                parts = re.split(r"\s+to\s+", rest, flags=re.IGNORECASE)
                return self.file_controller.move_item(parts[0].strip(), parts[1].strip(), visual=False)

        # Rename item
        if lower.startswith("rename file ") or lower.startswith("rename "):
            prefix = "rename file " if lower.startswith("rename file ") else "rename "
            rest = trimmed[len(prefix):].strip()
            if " to " in rest.lower():
                parts = re.split(r"\s+to\s+", rest, flags=re.IGNORECASE)
                return self.file_controller.rename_item(parts[0].strip(), parts[1].strip(), visual=False)

        return None

    # ── Shell Handler ─────────────────────────────────────────────────────

    def _handle_shell(self, raw_cmd: str) -> Tuple[str, bool]:
        if not raw_cmd:
            return ("No command provided.", True)
        try:
            res = subprocess.run(
                raw_cmd, shell=True,
                capture_output=True, text=True, errors="replace",
            )
            out = (res.stdout or res.stderr or "Command executed successfully (exit code 0).").strip()
            reply = f"[Command Result (Exit {res.returncode})]:\n{out}"
        except Exception as e:
            reply = f"[Command Error]: {e}"
        return (reply, True)


class _DefaultProcessChecker:
    """Thin psutil-based process checker."""

    def is_running(self, process_names: tuple) -> bool:
        try:
            import psutil
        except ImportError:
            return False
        names_lower = {n.lower() for n in process_names}
        for proc in psutil.process_iter(["name"]):
            try:
                if (proc.info["name"] or "").lower() in names_lower:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return False