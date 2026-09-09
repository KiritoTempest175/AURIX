"""AURIX AI Brain -- Hybrid Dynamic App Control.

Combines OS-level path resolution with GUI automation. Features intelligent 
directory pruning to prevent file searches from hanging on heavy dev folders,
and uses URI protocols to instantly launch UWP/AppData applications.
"""

import os
import time
import platform
import shutil
import logging
import subprocess
from pathlib import Path
from typing import Optional, List

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

try:
    import pyautogui
    pyautogui.PAUSE = 0.1
    pyautogui.FAILSAFE = True
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

logger = logging.getLogger("aurix.ai_brain.app_control")
IS_WINDOWS = platform.system() == "Windows"

# ═══════════════════════════════════════════════════════════════════════════
#  AppLauncher -- Hybrid Directory, File & GUI Launcher
# ═══════════════════════════════════════════════════════════════════════════

class AppLauncher:
    """
    Dynamically launches apps, folders, and files using an optimized tiered approach.
    """

    def __init__(self):
        # Maps common names to their exact executables or Windows URIs
        self._aliases = {
            "setting": "ms-settings:",
            "settings": "ms-settings:",
            "calculator": "calc.exe",
            "notepad": "notepad.exe",
            "cmd": "cmd.exe",
            "terminal": "cmd.exe",
            "powershell": "powershell.exe",
            "explorer": "explorer.exe",
            "file explorer": "explorer.exe",
            "paint": "mspaint.exe",
            "task manager": "taskmgr.exe",
            "chrome": "chrome.exe",
            "google chrome": "chrome.exe",
            
            # Use URI protocols for apps hidden in AppData to bypass search
            "spotify": "spotify:",
            "whatsapp": "whatsapp:",
            
            "vscode": "code",
            "vs code": "code",
            "visual studio code": "code"
        }

    def launch(self, target: str) -> str:
        """Attempt to launch *target*. Returns a human-readable status message."""
        if not target or not target.strip():
            return "No application, folder, or file name provided."

        raw = target.strip()
        lower = raw.lower()
        
        # 1. Check if it is a URL
        if lower.startswith(("http://", "https://", "www.")):
            return self._open_url(raw)

        # Build execution queue: Try exact literal string first, THEN try stripped string
        targets_to_try = [lower]
        cleaned = lower
        for suffix in [" folder", " file", " directory", " app"]:
            if cleaned.endswith(suffix):
                cleaned = cleaned[:-len(suffix)].strip()
                break
        
        if cleaned != lower:
            targets_to_try.append(cleaned)

        logger.info("AppLauncher: targets queued for resolution -> %s", targets_to_try)

        # 2. Check Directories (Exact first, then stripped)
        for t in targets_to_try:
            folder_path = self._resolve_local_folder(t)
            if folder_path:
                return self._launch_via_startfile(str(folder_path), is_folder=True)

        # 3. Check Aliases (Fast Lane)
        for t in targets_to_try:
            for alias_key, alias_val in self._aliases.items():
                if t == alias_key:
                    success_msg = self._launch_via_startfile(alias_val)
                    if success_msg:
                        return success_msg

        # 4. Check Local Files (Fast os.walk traversal)
        for t in targets_to_try:
            local_file = self._resolve_local_file(t)
            if local_file and local_file.exists():
                return self._launch_via_startfile(str(local_file), is_folder=False)

        # 5. Check PATH environment
        for t in targets_to_try:
            path_hit = shutil.which(t) or shutil.which(f"{t}.exe")
            if path_hit:
                try:
                    subprocess.Popen([path_hit], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return f"Launched {os.path.basename(path_hit)} via system PATH."
                except Exception as e:
                    logger.error("AppLauncher: PATH launch failed: %s", e)

        # 6. Fallback to PyAutoGUI
        if IS_WINDOWS and PYAUTOGUI_AVAILABLE:
            return self._launch_via_pyautogui(raw)

        return f"Could not find or launch: {raw}"

    def _resolve_local_folder(self, target: str) -> Optional[Path]:
        """Resolves folder paths efficiently while avoiding search bar hijacking."""
        home = Path.home()
        shortcuts = {
            "desktop":   home / "Desktop",
            "downloads": home / "Downloads",
            "documents": home / "Documents",
            "pictures":  home / "Pictures",
            "music":     home / "Music",
            "videos":    home / "Videos",
            "home":      home,
        }

        if target in shortcuts:
            return shortcuts[target]

        search_dirs = [home / "Desktop", home / "Documents", home / "Downloads"]
        for directory in search_dirs:
            if directory.exists():
                potential_path = directory / target
                if potential_path.exists() and potential_path.is_dir():
                    return potential_path

        return None

    def _resolve_local_file(self, query: str) -> Optional[Path]:
        """
        Searches user directories utilizing fast os.walk pruning. 
        Instantly skips heavy developer folders to prevent bottlenecking.
        """
        home = Path.home()
        search_dirs = [home / "Documents", home / "Desktop", home / "Downloads"]
        
        matches = []
        q_lower = query.strip().lower()
        
        # Auto-append common extensions if none are provided
        if not any(q_lower.endswith(ext) for ext in [".pdf", ".docx", ".txt", ".xlsx", ".png", ".py", ".md", ".csv"]):
            search_terms = [q_lower, f"{q_lower}.pdf", f"{q_lower}.docx", f"{q_lower}.txt"]
        else:
            search_terms = [q_lower]

        # These directories are completely ignored to maintain speed
        skip_dirs = {".git", "node_modules", "venv", "env", "__pycache__", "appdata", "site-packages", ".vscode", "build", "dist"}

        for directory in search_dirs:
            if not directory.exists():
                continue
                
            for root, dirs, files in os.walk(directory):
                # IN-PLACE PRUNING: Modifies the dirs list so os.walk ignores heavy folders
                dirs[:] = [d for d in dirs if d.lower() not in skip_dirs]
                
                for file_name in files:
                    name_lower = file_name.lower()
                    if any(term == name_lower or term in name_lower for term in search_terms):
                        full_path = Path(root) / file_name
                        try:
                            matches.append((full_path.stat().st_mtime, full_path))
                        except Exception:
                            matches.append((0, full_path))

        if matches:
            # Sort by modification time descending to open the most recent version
            matches.sort(key=lambda x: x[0], reverse=True)
            return matches[0][1]
            
        return None

    def _open_url(self, url: str) -> str:
        """Open a URL in the default browser."""
        try:
            os.startfile(url) if IS_WINDOWS else subprocess.Popen(["xdg-open", url])
            return f"Opened URL: {url}"
        except Exception as e:
            return f"Failed to open URL {url}: {e}"

    def _launch_via_startfile(self, target: str, is_folder: bool = False) -> Optional[str]:
        """Silently launches an executable, URI, folder, or file via OS bindings."""
        if not IS_WINDOWS:
            return None
        try:
            os.startfile(target)
            path_obj = Path(target)
            if is_folder:
                target_type = "folder"
            elif path_obj.is_file():
                target_type = "file"
            else:
                target_type = "application"
                
            logger.info("AppLauncher: launched via os.startfile -- '%s'", target)
            name = path_obj.name if path_obj.exists() else target
            return f"Opened {target_type}: {name}."
        except OSError:
            return None

    def _launch_via_pyautogui(self, target: str) -> str:
        """Uses GUI automation to type the app name into the Start menu."""
        try:
            logger.info("AppLauncher: falling back to GUI automation for '%s'", target)
            pyautogui.press("win")
            time.sleep(0.6)
            pyautogui.write(target, interval=0.05)
            time.sleep(0.8)
            pyautogui.press("enter")
            return f"Used Windows Search to launch: {target}."
        except Exception as e:
            logger.error("AppLauncher: GUI launch failed: %s", e)
            return f"Failed to automate GUI for {target}: {e}"


# ═══════════════════════════════════════════════════════════════════════════
#  AppCloser -- Dynamic Application Closer
# ═══════════════════════════════════════════════════════════════════════════

class AppCloser:
    """Dynamically finds and terminates running applications using psutil."""
    
    def __init__(self):
        # STRICT MINIMAL ALIASES:
        # Only used when the conversational name completely differs from the Windows process name.
        self._close_aliases = {
            "task manager": "taskmgr",
            "command prompt": "cmd",
            "vs code": "code",
            "visual studio code": "code",
            "settings": "systemsettings",
            "calculator": "calculatorapp",
            "paint": "mspaint",
            "terminal": "windowsterminal"
        }

    _PROTECTED = frozenset({
        "system", "smss", "csrss", "wininit", "winlogon", "services",
        "lsass", "svchost", "dwm", "taskhostw", "explorer",
        "sihost", "fontdrvhost", "ctfmon", "runtimebroker",
        "searchhost", "startmenuexperiencehost", "shellexperiencehost",
        "textinputhost", "securityhealthservice", "securityhealthsystray",
    })

    def close(self, target: str) -> str:
        """Attempt to close application matching *target*."""
        if not target or not target.strip():
            return "No application name provided."

        if not PSUTIL_AVAILABLE:
            return self._fallback_close(target)

        raw = target.strip()
        lower = raw.lower()
        
        # TRANSLATION STEP: If the user typed "task manager", turn it into "taskmgr".
        # If it's not in the dictionary, just use whatever the user typed.
        search_target = self._close_aliases.get(lower, lower)
        
        logger.info("AppCloser: requested to close '%s' (searching for process: '%s')", raw, search_target)

        killed_count = 0
        errors = []

        for proc in psutil.process_iter(["pid", "name"]):
            try:
                proc_name = proc.info["name"] or ""
                proc_name_lower = proc_name.lower()
                proc_stem = os.path.splitext(proc_name_lower)[0]

                if proc_stem in self._PROTECTED:
                    continue

                # Match against the TRANSLATED search_target, not the raw input
                if search_target in proc_name_lower:
                    proc.terminate()
                    killed_count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                errors.append(f"{proc.info.get('name', 'Unknown')}: {e}")
                continue

        if killed_count > 0:
            return f"Successfully closed {killed_count} instance(s) matching '{raw}'."

        if errors:
            return f"Found processes but couldn't close them: {'; '.join(errors)}"

        return f"No running application found matching: {raw}"

    def _fallback_close(self, target: str) -> str:
        """Fallback when psutil is not installed -- use taskkill on Windows."""
        if not IS_WINDOWS:
            return "Cannot close applications without psutil on this platform."

        lower = target.strip().lower()
        # Ensure the fallback closer also translates the alias
        search_target = self._close_aliases.get(lower, lower)
        
        exe_name = search_target if search_target.endswith(".exe") else f"{search_target}.exe"
        try:
            result = subprocess.run(
                ["taskkill", "/F", "/IM", exe_name, "/T"],
                capture_output=True, text=True, errors="replace",
            )
            if result.returncode == 0:
                return f"Closed {target}."
        except Exception as e:
            logger.error("AppCloser: taskkill failed for '%s': %s", exe_name, e)

        return f"Could not find or terminate running application: {target}"# ═══════════════════════════════════════════════════════════════════════════
#  AppCloser -- Dynamic Application Closer
# ═══════════════════════════════════════════════════════════════════════════

class AppCloser:
    """Dynamically finds and terminates running applications using psutil."""
    
    def __init__(self):
        # STRICT MINIMAL ALIASES:
        # Only used when the conversational name completely differs from the Windows process name.
        self._close_aliases = {
            "task manager": "taskmgr",
            "command prompt": "cmd",
            "vs code": "code",
            "visual studio code": "code",
            "settings": "systemsettings",
            "calculator": "calculatorapp",
            "paint": "mspaint",
            "terminal": "windowsterminal"
        }

    _PROTECTED = frozenset({
        "system", "smss", "csrss", "wininit", "winlogon", "services",
        "lsass", "svchost", "dwm", "taskhostw", "explorer",
        "sihost", "fontdrvhost", "ctfmon", "runtimebroker",
        "searchhost", "startmenuexperiencehost", "shellexperiencehost",
        "textinputhost", "securityhealthservice", "securityhealthsystray",
    })

    def close(self, target: str) -> str:
        """Attempt to close application matching *target*."""
        if not target or not target.strip():
            return "No application name provided."

        if not PSUTIL_AVAILABLE:
            return self._fallback_close(target)

        raw = target.strip()
        lower = raw.lower()
        
        # TRANSLATION STEP: If the user typed "task manager", turn it into "taskmgr".
        # If it's not in the dictionary, just use whatever the user typed.
        search_target = self._close_aliases.get(lower, lower)
        
        logger.info("AppCloser: requested to close '%s' (searching for process: '%s')", raw, search_target)

        killed_count = 0
        errors = []

        for proc in psutil.process_iter(["pid", "name"]):
            try:
                proc_name = proc.info["name"] or ""
                proc_name_lower = proc_name.lower()
                proc_stem = os.path.splitext(proc_name_lower)[0]

                if proc_stem in self._PROTECTED:
                    continue

                # Match against the TRANSLATED search_target, not the raw input
                if search_target in proc_name_lower:
                    proc.terminate()
                    killed_count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                errors.append(f"{proc.info.get('name', 'Unknown')}: {e}")
                continue

        if killed_count > 0:
            return f"Successfully closed {killed_count} instance(s) matching '{raw}'."

        if errors:
            return f"Found processes but couldn't close them: {'; '.join(errors)}"

        return f"No running application found matching: {raw}"

    def _fallback_close(self, target: str) -> str:
        """Fallback when psutil is not installed -- use taskkill on Windows."""
        if not IS_WINDOWS:
            return "Cannot close applications without psutil on this platform."

        lower = target.strip().lower()
        # Ensure the fallback closer also translates the alias
        search_target = self._close_aliases.get(lower, lower)
        
        exe_name = search_target if search_target.endswith(".exe") else f"{search_target}.exe"
        try:
            result = subprocess.run(
                ["taskkill", "/F", "/IM", exe_name, "/T"],
                capture_output=True, text=True, errors="replace",
            )
            if result.returncode == 0:
                return f"Closed {target}."
        except Exception as e:
            logger.error("AppCloser: taskkill failed for '%s': %s", exe_name, e)

        return f"Could not find or terminate running application: {target}"

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(levelname)s: %(message)s")
    
    print("=" * 50)
    print("AURIX App Control - Standalone Test Mode")
    print("Commands: 'open <target>', 'close <target>', or 'exit'")
    print("=" * 50)
    
    launcher = AppLauncher()
    closer = AppCloser()
    
    while True:
        try:
            user_input = input("\n[Test Mode] >>> ").strip()
            
            if not user_input:
                continue
                
            if user_input.lower() in ["exit", "quit"]:
                print("Exiting test mode.")
                break
                
            if user_input.lower().startswith("open "):
                target = user_input[5:].strip()
                result = launcher.launch(target)
                print(f"Result: {result}")
                
            elif user_input.lower().startswith("close "):
                target = user_input[6:].strip()
                result = closer.close(target)
                print(f"Result: {result}")
                
            else:
                print("Invalid command. Please use 'open <target>', 'close <target>', or 'exit'.")
                
        except KeyboardInterrupt:
            print("\nExiting test mode.")
            break
        except Exception as e:
            print(f"\nAn error occurred: {e}")