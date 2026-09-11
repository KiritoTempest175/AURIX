"""AURIX AI Brain -- Hybrid Sandboxed File Controller.

Enforces strict C: drive path jailing (restricted exclusively to user folders:
Desktop, Downloads, Documents, Pictures, Music, Videos) while leaving non-C
drives accessible. Destructive actions (cut, move, delete) require user
confirmation, while autonomous memory paths remain prompt-free. Visual GUI
operations are automated via PyAutoGUI so the user can observe actions.
"""

from __future__ import annotations

import os
import sys
import time
import shutil
import logging
import platform
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

try:
    import winreg
except ImportError:
    winreg = None

try:
    import pyautogui
    pyautogui.PAUSE = 0.12
    pyautogui.FAILSAFE = True
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

try:
    import send2trash
    SEND2TRASH_AVAILABLE = True
except ImportError:
    SEND2TRASH_AVAILABLE = False

logger = logging.getLogger("aurix.ai_brain.file_control")
IS_WINDOWS = platform.system() == "Windows"


def _get_windows_known_folder(folder_name: str, fallback: Path) -> Path:
    """Resolve the real Windows known-folder location.

    Supports redirected folders such as OneDrive Desktop/Documents.
    Falls back safely to the conventional user-profile path when lookup fails.
    """
    fallback = fallback.expanduser()

    if not IS_WINDOWS or winreg is None:
        return fallback.resolve()

    registry_names = {
        "desktop": "Desktop",
        "documents": "Personal",
        "pictures": "My Pictures",
        "music": "My Music",
        "videos": "My Video",
        "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    }

    value_name = registry_names.get(folder_name.lower())
    if not value_name:
        return fallback.resolve()

    try:
        key_path = (
            r"Software\Microsoft\Windows\CurrentVersion"
            r"\Explorer\User Shell Folders"
        )

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            key_path,
        ) as key:
            value, _ = winreg.QueryValueEx(key, value_name)

        value = os.path.expandvars(str(value))
        return Path(value).expanduser().resolve()

    except Exception as exc:
        logger.debug(
            "Could not resolve Windows known folder %s: %s",
            folder_name,
            exc,
        )
        return fallback.resolve()


class SecurityException(PermissionError):
    """Raised when an operation attempts to breach filesystem safety constraints."""
    pass


# ═══════════════════════════════════════════════════════════════════════════
#  Security Sandbox & Path Verification
# ═══════════════════════════════════════════════════════════════════════════

class FileSandbox:
    """Validates paths against strict boundaries:
    - C: drive access is restricted exclusively to the 6 pinned user folders.
    - Other drives (D:, E:, etc.) are unrestricted.
    - System root, Windows, and AppData directories are strictly blocked.
    """

    HOME = Path.home().resolve()

    # Resolve actual Windows user folders, including OneDrive/redirection.
    DESKTOP = _get_windows_known_folder(
        "desktop",
        HOME / "Desktop",
    )
    DOWNLOADS = _get_windows_known_folder(
        "downloads",
        HOME / "Downloads",
    )
    DOCUMENTS = _get_windows_known_folder(
        "documents",
        HOME / "Documents",
    )
    PICTURES = _get_windows_known_folder(
        "pictures",
        HOME / "Pictures",
    )
    MUSIC = _get_windows_known_folder(
        "music",
        HOME / "Music",
    )
    VIDEOS = _get_windows_known_folder(
        "videos",
        HOME / "Videos",
    )

    ALLOWED_C_DIRS = frozenset({
        DESKTOP,
        DOWNLOADS,
        DOCUMENTS,
        PICTURES,
        MUSIC,
        VIDEOS,
    })

    SHORTCUTS = {
        "desktop": DESKTOP,
        "downloads": DOWNLOADS,
        "documents": DOCUMENTS,
        "pictures": PICTURES,
        "music": MUSIC,
        "videos": VIDEOS,
        "home": HOME,
    }

    @classmethod
    def resolve_path(
        cls,
        raw: str,
        *,
        destructive: bool = False,
    ) -> Path:
        """Resolve a user path safely.

        Rules:
        - Absolute paths are validated directly.
        - Known folder shortcuts are supported.
        - Relative file names are searched in approved user folders.
        - Destructive operations require an exact, unambiguous match.
        - Never silently guess between multiple destructive targets.
        """

        if not raw or not str(raw).strip():
            raise SecurityException(
                "No file or folder path was provided."
            )

        cleaned = str(raw).strip().strip('"').strip("'")
        lower = cleaned.lower()

        # ---------------------------------------------------------
        # 1. Named shortcuts
        # ---------------------------------------------------------

        if lower in cls.SHORTCUTS:

            resolved = cls.SHORTCUTS[lower].resolve()

            cls.validate_path(resolved)

            return resolved

        # ---------------------------------------------------------
        # 2. Absolute path
        # ---------------------------------------------------------

        possible = Path(cleaned).expanduser()

        if possible.is_absolute():

            resolved = possible.resolve()

            cls.validate_path(resolved)

            return resolved

        # ---------------------------------------------------------
        # 3. Explicit relative folder:
        #    Desktop/test.txt
        #    Documents/file.docx
        # ---------------------------------------------------------

        parts = Path(cleaned).parts

        if parts:

            first = parts[0].lower()

            shortcut_root = cls.SHORTCUTS.get(first)

            if shortcut_root is not None:

                target = shortcut_root.joinpath(
                    *parts[1:]
                ).resolve()

                cls.validate_path(target)

                return target

        # ---------------------------------------------------------
        # 4. Search allowed roots
        # ---------------------------------------------------------

        exact_matches = []
        fuzzy_matches = []

        skip_dirs = {
            ".git",
            "node_modules",
            "venv",
            ".venv",
            "env",
            "__pycache__",
            ".vscode",
            "appdata",
        }

        for base_dir in cls.ALLOWED_C_DIRS:

            if not base_dir.exists():
                continue

            try:

                for root, dirs, files in os.walk(
                    base_dir
                ):

                    dirs[:] = [
                        d
                        for d in dirs
                        if d.lower() not in skip_dirs
                    ]

                    root_path = Path(root)

                    # Directory match
                    if root_path.name.lower() == lower:

                        candidate = root_path.resolve()

                        cls.validate_path(candidate)

                        exact_matches.append(
                            candidate
                        )

                    # File matches
                    for file_name in files:

                        name_lower = file_name.lower()

                        candidate = (
                            root_path / file_name
                        ).resolve()

                        if name_lower == lower:

                            cls.validate_path(
                                candidate
                            )

                            exact_matches.append(
                                candidate
                            )

                        elif (
                            not destructive
                            and lower in name_lower
                        ):

                            cls.validate_path(
                                candidate
                            )

                            fuzzy_matches.append(
                                candidate
                            )

            except Exception as exc:

                logger.debug(
                    "Search skipped for %s: %s",
                    base_dir,
                    exc,
                )

        # ---------------------------------------------------------
        # Exact single match
        # ---------------------------------------------------------

        unique_exact = list(
            dict.fromkeys(exact_matches)
        )

        if len(unique_exact) == 1:
            return unique_exact[0]

        # Multiple matches = NEVER GUESS.
        if len(unique_exact) > 1:

            matches = "\n".join(
                f"- {path}"
                for path in unique_exact[:10]
            )

            raise SecurityException(
                "Multiple matching items were found. "
                "Please specify the location:\n"
                f"{matches}"
            )

        # ---------------------------------------------------------
        # Destructive actions cannot use fuzzy guesses.
        # ---------------------------------------------------------

        if destructive:

            raise FileNotFoundError(
                f"Could not safely locate '{cleaned}'. "
                "Specify its folder, for example "
                "'Desktop/test.txt'."
            )

        # ---------------------------------------------------------
        # Non-destructive fuzzy fallback
        # ---------------------------------------------------------

        unique_fuzzy = list(
            dict.fromkeys(fuzzy_matches)
        )

        if len(unique_fuzzy) == 1:
            return unique_fuzzy[0]

        if len(unique_fuzzy) > 1:

            matches = "\n".join(
                f"- {path}"
                for path in unique_fuzzy[:10]
            )

            raise SecurityException(
                "Several similar items were found. "
                "Please specify which one you mean:\n"
                f"{matches}"
            )

        # ---------------------------------------------------------
        # New file/path default
        # ---------------------------------------------------------

        target = (
            cls.DESKTOP
            / cleaned
        ).resolve()

        cls.validate_path(target)

        return target

    @classmethod
    def validate_path(cls, target: Path) -> None:
        """Enforces drive-level isolation and sandboxing."""
        target_str = str(target)

        blocked_keywords = ["%appdata%", "%systemroot%", "%temp%", "appdata", "windows", "system32", "$recycle.bin"]
        for kw in blocked_keywords:
            if kw in target_str.lower():
                raise SecurityException(f"Access denied: Path references restricted system identifier '{kw}'.")

        drive = target.drive.upper()
        if drive.startswith("C"):
            is_permitted = any(
                allowed == target or allowed in target.parents
                for allowed in cls.ALLOWED_C_DIRS
            )
            if not is_permitted:
                raise SecurityException(
                    f"Access denied: C: drive operations are strictly restricted to "
                    f"Desktop, Downloads, Documents, Pictures, Music, and Videos. Target: {target}"
                )

    @classmethod
    def is_autonomous_memory_path(cls, path: Path) -> bool:
        """Determines if the file path is part of Luna's internal memory/vault."""
        p_str = str(path).lower()
        memory_indicators = [".aurix_memory", ".obsidian", "memory", "history", "vault"]
        return any(ind in p_str for ind in memory_indicators)


# ═══════════════════════════════════════════════════════════════════════════
#  FileController Engine
# ═══════════════════════════════════════════════════════════════════════════

class FileController:
    """Manages file operations combining OS-level accuracy with visual PyAutoGUI
    execution and strict security validation.
    """

    def __init__(self, interactive_confirmations: bool = True):
        self.interactive = interactive_confirmations

    def _request_permission(self, action: str, details: str, path: Path) -> bool:
        """Requests user confirmation before performing destructive operations.
        Memory and history maintenance operations are automatically permitted.
        """
        if FileSandbox.is_autonomous_memory_path(path):
            return True

        if not self.interactive:
            return True

        print("\n" + "!" * 60)
        print(f"[SECURITY ALERT] Luna is requesting permission to: {action.upper()}")
        print(f"Target Details: {details}")
        print("!" * 60)

        choice = input("Authorize this modification? (yes/no): ").strip().lower()
        return choice in ["y", "yes", "authorize", "ok"]

    def _open_in_explorer_and_select(self, path: Path) -> bool:
        """Opens File Explorer with the target item highlighted."""
        if not IS_WINDOWS:
            return False
        try:
            if path.exists():
                subprocess.Popen(f'explorer /select,"{path}"')
            else:
                subprocess.Popen(f'explorer "{path.parent}"')
            time.sleep(1.0)
            return True
        except Exception as e:
            logger.error("Failed to open File Explorer visually: %s", e)
            return False

    # ── Read / Inspection Operations (Silent & Safe) ─────────────────────

    def read_file(self, target_path: str, max_chars: int = 4000) -> str:
        """Reads content from a text file within permitted directories."""
        try:
            target = FileSandbox.resolve_path(target_path)
            if not target.exists():
                return f"File not found: {target}"
            if not target.is_file():
                return f"Path is a directory, not a file: {target}"

            content = target.read_text(encoding="utf-8", errors="replace")
            if len(content) > max_chars:
                return content[:max_chars] + f"\n\n[Truncated: displaying {max_chars} of {len(content)} total characters]"
            return content
        except Exception as e:
            return f"Read error: {e}"

    def list_directory(self, target_path: str = "desktop", show_hidden: bool = False) -> str:
        """Lists directories and files inside a resolved folder."""
        try:
            target = FileSandbox.resolve_path(target_path)
            if not target.exists():
                return f"Path not found: {target}"
            if not target.is_dir():
                return f"Target is not a directory: {target}"

            items = []
            for entry in sorted(target.iterdir()):
                if not show_hidden and entry.name.startswith("."):
                    continue
                if entry.is_dir():
                    items.append(f"📁 {entry.name}/")
                else:
                    size_kb = entry.stat().st_size / 1024
                    items.append(f"📄 {entry.name} ({size_kb:.1f} KB)")

            if not items:
                return f"Directory is empty: {target.name}/"

            return f"Contents of {target} ({len(items)} items):\n" + "\n".join(items)
        except Exception as e:
            return f"Listing error: {e}"

    # ── Writing & Creation Operations ────────────────────────────────────

    def write_file(self, target_path: str, content: str = "", append: bool = False) -> str:
        """Writes or appends to a file. Requires confirmation if overwriting an existing file,
        unless the destination is part of Luna's autonomous memory system.
        """
        try:
            target = FileSandbox.resolve_path(target_path)

            if target.exists() and not append:
                authorized = self._request_permission("OVERWRITE FILE", str(target), target)
                if not authorized:
                    return f"Operation aborted: Overwrite authorization denied for {target.name}"

            target.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if append else "w"
            with open(target, mode, encoding="utf-8") as f:
                f.write(content)

            status = "Appended to" if append else "Created/Updated"
            return f"{status} file: {target}"
        except Exception as e:
            return f"Write error: {e}"

    def create_folder(self, target_path: str) -> str:
        """Creates a new folder at the target path."""
        try:
            target = FileSandbox.resolve_path(target_path)
            target.mkdir(parents=True, exist_ok=True)
            return f"Folder established: {target}"
        except Exception as e:
            return f"Folder creation error: {e}"

    # ── Destructive Operations (Visual + Permission Gated) ───────────────

    def delete_item(self, target_path: str, visual: bool = True) -> str:
        """Soft-deletes a file or directory by moving it to the Recycle Bin.
        Always requires user authorization and can be driven visually via PyAutoGUI.
        """
        try:
            target = FileSandbox.resolve_path(
                target_path,
                destructive=True,
            )
            if not target.exists():
                return f"File not found: {target}"

            authorized = self._request_permission("DELETE (Recycle Bin)", str(target), target)
            if not authorized:
                return f"Operation cancelled: Deletion authorization declined for {target.name}."

            if visual and PYAUTOGUI_AVAILABLE and IS_WINDOWS:
                opened = self._open_in_explorer_and_select(target)
                if opened:
                    time.sleep(0.5)
                    pyautogui.press("delete")
                    time.sleep(0.4)
                    return f"Visually triggered deletion for: {target.name}"

            # Fallback to direct Recycle Bin invocation
            if SEND2TRASH_AVAILABLE:
                send2trash.send2trash(str(target))
                return f"Moved to Recycle Bin: {target.name}"
            else:
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
                return f"Permanently removed: {target.name}"

        except Exception as e:
            return f"Delete error: {e}"

    def move_item(self, source_path: str, destination_path: str, visual: bool = True) -> str:
        """Moves a file or folder from source to destination with visual automation."""
        try:
            src = FileSandbox.resolve_path(
                source_path,
                destructive=True,
            )
            dst = FileSandbox.resolve_path(destination_path)

            if not src.exists():
                return f"Source item does not exist: {src}"

            final_dest = dst / src.name if dst.is_dir() else dst

            authorized = self._request_permission("MOVE / RELOCATE", f"{src} -> {final_dest}", src)
            if not authorized:
                return f"Operation cancelled: Move authorization declined for {src.name}."

            if visual and PYAUTOGUI_AVAILABLE and IS_WINDOWS:
                self._open_in_explorer_and_select(src)
                pyautogui.hotkey("ctrl", "x")
                time.sleep(0.5)

                dst_dir = dst if dst.is_dir() else dst.parent
                subprocess.Popen(f'explorer "{dst_dir}"')
                time.sleep(1.0)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(0.5)
                return f"Visually relocated {src.name} to {dst_dir.name}/"

            # Direct fallback
            final_dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(final_dest))
            return f"Relocated {src.name} to {final_dest}"

        except Exception as e:
            return f"Move error: {e}"

    def copy_item(self, source_path: str, destination_path: str, visual: bool = True) -> str:
        """Duplicates a file or folder with visual automation."""
        try:
            src = FileSandbox.resolve_path(source_path)
            dst = FileSandbox.resolve_path(destination_path)

            if not src.exists():
                return f"Source not found: {src}"

            final_dest = dst / src.name if dst.is_dir() else dst

            if visual and PYAUTOGUI_AVAILABLE and IS_WINDOWS:
                self._open_in_explorer_and_select(src)
                pyautogui.hotkey("ctrl", "c")
                time.sleep(0.5)

                dst_dir = dst if dst.is_dir() else dst.parent
                subprocess.Popen(f'explorer "{dst_dir}"')
                time.sleep(1.0)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(0.5)
                return f"Visually copied {src.name} to {dst_dir.name}/"

            # Direct fallback
            final_dest.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(str(src), str(final_dest))
            else:
                shutil.copy2(str(src), str(final_dest))
            return f"Copied {src.name} to {final_dest}"

        except Exception as e:
            return f"Copy error: {e}"

    def rename_item(self, target_path: str, new_name: str, visual: bool = True) -> str:
        """Renames a file or directory with visual automation."""
        try:
            target = FileSandbox.resolve_path(
                target_path,
                destructive=True,
            )
            if not target.exists():
                return f"Target not found: {target}"

            new_target = target.parent / new_name
            FileSandbox.validate_path(new_target)

            if new_target.exists():
                return f"Conflict: An item named '{new_name}' already exists in that location."

            authorized = self._request_permission("RENAME", f"{target.name} -> {new_name}", target)
            if not authorized:
                return f"Operation cancelled: Rename authorization declined."

            if visual and PYAUTOGUI_AVAILABLE and IS_WINDOWS:
                self._open_in_explorer_and_select(target)
                pyautogui.press("f2")
                time.sleep(0.3)
                pyautogui.write(new_name, interval=0.03)
                time.sleep(0.3)
                pyautogui.press("enter")
                return f"Visually renamed {target.name} to {new_name}"

            target.rename(new_target)
            return f"Renamed {target.name} to {new_name}"

        except Exception as e:
            return f"Rename error: {e}"


# ═══════════════════════════════════════════════════════════════════════════
#  LLM Dispatcher Protocol Interface
# ═══════════════════════════════════════════════════════════════════════════

_global_controller = FileController()

def handle_file_action(parameters: Dict[str, Any]) -> str:
    """Entry point for tool-dispatch calling from Luna's cognitive layer."""
    action = parameters.get("action", "").lower().strip()
    path = parameters.get("path", "desktop")
    destination = parameters.get("destination", "")
    content = parameters.get("content", "")
    new_name = parameters.get("new_name", "")

    try:
        if action in ("read", "view"):
            return _global_controller.read_file(path)
        elif action in ("list", "dir", "ls"):
            return _global_controller.list_directory(path)
        elif action in ("write", "create_file"):
            return _global_controller.write_file(path, content=content, append=parameters.get("append", False))
        elif action == "create_folder":
            return _global_controller.create_folder(path)
        elif action in ("delete", "remove", "del"):
            return _global_controller.delete_item(path)
        elif action in ("move", "cut"):
            return _global_controller.move_item(path, destination)
        elif action in ("copy", "duplicate"):
            return _global_controller.copy_item(path, destination)
        elif action == "rename":
            return _global_controller.rename_item(path, new_name)
        else:
            return f"Unrecognized file action: '{action}'"
    except SecurityException as sec_err:
        logger.error("Security boundary triggered: %s", sec_err)
        return f"[Security Blocked]: {sec_err}"
    except Exception as err:
        logger.error("FileController dispatch error: %s", err)
        return f"[Error]: {err}"


# ═══════════════════════════════════════════════════════════════════════════
#  Standalone Interactive Test Mode
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(levelname)s: %(message)s")

    print("=" * 65)
    print("AURIX File Controller -- Standalone Test Mode")
    print("Commands:")
    print("  list <path>                - List directory contents")
    print("  read <path>                - Read a text file")
    print("  write <path> <content>     - Create/update a file")
    print("  delete <path>              - Delete an item (Recycle Bin)")
    print("  move <src> -> <dst>        - Move an item")
    print("  copy <src> -> <dst>        - Copy an item")
    print("  rename <path> -> <new_name>- Rename an item")
    print("  exit                       - Quit")
    print("=" * 65)

    controller = FileController(interactive_confirmations=True)

    while True:
        try:
            raw_input = input("\n[File Controller] >>> ").strip()
            if not raw_input:
                continue

            cmd_lower = raw_input.lower()
            if cmd_lower in ["exit", "quit"]:
                print("Exiting test mode.")
                break

            if cmd_lower.startswith("list"):
                arg = raw_input[4:].strip() or "desktop"
                print(controller.list_directory(arg))

            elif cmd_lower.startswith("read "):
                arg = raw_input[5:].strip()
                print(controller.read_file(arg))

            elif cmd_lower.startswith("write "):
                parts = raw_input[6:].strip().split(" ", 1)
                if len(parts) == 2:
                    p, c = parts
                    print(controller.write_file(p, content=c))
                else:
                    print("Usage: write <path> <content>")

            elif cmd_lower.startswith("delete "):
                arg = raw_input[7:].strip()
                print(controller.delete_item(arg))

            elif cmd_lower.startswith("move "):
                parts = raw_input[5:].split("->")
                if len(parts) == 2:
                    s, d = parts[0].strip(), parts[1].strip()
                    print(controller.move_item(s, d))
                else:
                    print("Usage: move <src> -> <dst>")

            elif cmd_lower.startswith("copy "):
                parts = raw_input[5:].split("->")
                if len(parts) == 2:
                    s, d = parts[0].strip(), parts[1].strip()
                    print(controller.copy_item(s, d))
                else:
                    print("Usage: copy <src> -> <dst>")

            elif cmd_lower.startswith("rename "):
                parts = raw_input[7:].split("->")
                if len(parts) == 2:
                    p, n = parts[0].strip(), parts[1].strip()
                    print(controller.rename_item(p, n))
                else:
                    print("Usage: rename <path> -> <new_name>")

            else:
                print("Unknown command. Check available commands above.")

        except SecurityException as sec_ex:
            print(f"\n[SECURITY VIOLATION]: {sec_ex}")
        except KeyboardInterrupt:
            print("\nExiting test mode.")
            break
        except Exception as ex:
            print(f"\nError: {ex}")