"""AURIX AI Brain -- Dynamic App Control (Launch & Close).

Pure-Python module that dynamically discovers and manages applications
on Windows. No hardcoded app lists -- uses runtime discovery via:
  - Start Menu shortcut scanning
  - Steam library scanning (libraryfolders.vdf + appmanifest_*.acf)
  - Windows Registry App Paths / Uninstall keys
  - PATH environment scanning
  - psutil process enumeration with fuzzy matching

Only a minimal alias map is kept for common shorthand convenience.

NOTE ON ENCODING: every file read/write in this module passes
encoding='utf-8' explicitly. On Windows, open() without an explicit
encoding falls back to the system codepage (often cp1252), which cannot
represent characters like em-dashes or box-drawing lines and will raise
UnicodeEncodeError/UnicodeDecodeError partway through a write -- and
because 'w' mode truncates the file the instant it's opened, a crash
mid-write leaves a 0-byte file with no way to recover the original
content short of a backup. Do not remove these encoding= arguments.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("aurix.ai_brain.app_control")

# ---------------------------------------------------------------------------
# Conditional imports
# ---------------------------------------------------------------------------
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None
    PSUTIL_AVAILABLE = False

IS_WINDOWS = platform.system() == "Windows"

if IS_WINDOWS:
    try:
        import winreg
    except ImportError:
        winreg = None
else:
    winreg = None

# ---------------------------------------------------------------------------
# Alias cache (persisted, shared between AppLauncher and AppCloser)
# ---------------------------------------------------------------------------
ALIAS_CACHE_PATH = os.path.join("data", "app_alias_cache.json")

# Open Item #2 from the brief: if the user says "close X" within this many
# seconds of X being launched via a cached/fuzzy-matched alias, treat that
# as a strong signal the resolution was wrong and drop it from the cache
# instead of leaving a bad mapping in place indefinitely.
ALIAS_INVALIDATE_WINDOW_SECONDS = 30


def _load_alias_cache() -> Dict[str, dict]:
    if not os.path.exists(ALIAS_CACHE_PATH):
        return {}
    try:
        with open(ALIAS_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.warning("AppControl: failed to load alias cache, starting fresh", exc_info=True)
        return {}


def _save_alias_cache(cache: Dict[str, dict]) -> None:
    try:
        os.makedirs(os.path.dirname(ALIAS_CACHE_PATH) or ".", exist_ok=True)
        with open(ALIAS_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except Exception:
        logger.warning("AppControl: failed to save alias cache", exc_info=True)


def _invalidate_alias_cache_for_names(closed_names: List[str]) -> None:
    """Called by AppCloser after a successful close. Removes any alias-cache
    entry whose resolved path matches one of the just-closed process names,
    if that entry was launched within ALIAS_INVALIDATE_WINDOW_SECONDS."""
    if not closed_names:
        return

    cache = _load_alias_cache()
    if not cache:
        return

    closed_stems = {os.path.splitext(n)[0].lower() for n in closed_names}
    now = time.time()
    removed = []

    for query, entry in list(cache.items()):
        path = entry.get("path", "")
        launched_at = entry.get("launched_at", 0)
        path_stem = os.path.splitext(os.path.basename(path))[0].lower()

        if path_stem in closed_stems and (now - launched_at) <= ALIAS_INVALIDATE_WINDOW_SECONDS:
            del cache[query]
            removed.append(query)

    if removed:
        _save_alias_cache(cache)
        logger.info("AppControl: invalidated alias cache entries %s (closed within %ds of launch)",
                     removed, ALIAS_INVALIDATE_WINDOW_SECONDS)


# ═══════════════════════════════════════════════════════════════════════════
#  Fuzzy Matching Utilities
# ═══════════════════════════════════════════════════════════════════════════

def _fuzzy_score(query: str, candidate: str) -> int:
    """Score how well *query* matches *candidate* (higher = better).

    Returns 0 if no match at all.
    Scoring tiers:
        100 -- exact match
         80 -- candidate starts with query
         60 -- query starts with candidate (user typed more than needed)
         40 -- all query words found inside candidate
         20 -- at least one query word found (only for queries >= 5 chars)
          0 -- no match

    Length-aware guard: for short queries (< 5 chars), a substring hit
    anywhere inside a much longer candidate name is not meaningful signal
    on its own -- e.g. "nte" is a substring of "Internet Download Manager"
    but has nothing to do with it. Short queries must cover at least half
    of the candidate string's length to count as an "all words matched" hit,
    and are never eligible for the weaker "at least one word" tier at all.
    """
    q = query.lower().strip()
    c = candidate.lower().strip()

    if not q or not c:
        return 0
    if q == c:
        return 100
    if c.startswith(q):
        return 80
    if q.startswith(c):
        return 60

    q_words = q.split()
    if not q_words:
        return 0
    matches = sum(1 for w in q_words if w in c)

    if matches == len(q_words):
        if len(q) < 5:
            coverage = len(q) / max(len(c), 1)
            if coverage < 0.5:
                return 0
        return 40

    if matches > 0 and len(q) >= 5:
        return 20

    return 0


def _disambiguate(scored: List[Tuple[int, str, str]]) -> Optional[str]:
    """Given a list of (score, name, path) sorted descending by score,
    return a clarification question if the top two candidates are close
    enough that guessing would be unsafe -- e.g. the VS Code vs
    'Developer Command Prompt for VS 2022' collision. Returns None if the
    top candidate is a clear, safe winner."""
    if len(scored) < 2:
        return None

    top_score, top_name, top_path = scored[0]
    second_score, second_name, second_path = scored[1]

    if top_name.lower() == second_name.lower() or top_path == second_path:
        return None  # same app found via two discovery sources, not a real collision

    if (top_score - second_score) <= 5:
        return f"Did you mean {top_name} or {second_name}?"

    return None


# ═══════════════════════════════════════════════════════════════════════════
#  AppLauncher -- Dynamic Application Launcher
# ═══════════════════════════════════════════════════════════════════════════

class AppLauncher:
    """Dynamically discovers and launches applications on Windows.

    Discovery pipeline:
        1. Direct URL / existing file-or-folder path pass-through
        2. Learned alias cache (instant exact hits from prior successful launches)
        3. Minimal alias resolution (convenience shorthand only)
        4. Merged fuzzy search across Start Menu shortcuts + Steam library +
           Windows registry uninstall entries, with disambiguation on near-ties
        5. Windows Registry App Paths lookup (exact/near-exact, no fuzzy scoring)
        6. PATH / shutil.which() scan
        7. os.startfile() fallback (let Windows figure it out)
    """

    _ALIASES: Dict[str, str] = {
        "chrome": "Google Chrome",
        "firefox": "Mozilla Firefox",
        "edge": "Microsoft Edge",
        "vscode": "Visual Studio Code",
        "vs code": "Visual Studio Code",
        "code": "Visual Studio Code",
        "vs": "Visual Studio",
        "word": "Word",
        "excel": "Excel",
        "ppt": "PowerPoint",
        "powerpoint": "PowerPoint",
        "opera": "Opera",
        "discord": "Discord",
        "steam": "Steam",
        "spotify": "Spotify",
        "epic": "Epic Games Launcher",
        "epic games": "Epic Games Launcher",
        "terminal": "Windows Terminal",
        "cmd": "Command Prompt",
        "files": "File Explorer",
        "explorer": "File Explorer",
    }

    def __init__(self) -> None:
        self._start_apps_cache: Optional[List[Tuple[str, str]]] = None
        self._shortcut_cache: Optional[List[Tuple[str, str]]] = None
        self._steam_cache: Optional[List[Tuple[str, str]]] = None
        self._uninstall_cache: Optional[List[Tuple[str, str]]] = None
        self._alias_cache: Dict[str, dict] = _load_alias_cache()

    # ── Public API ────────────────────────────────────────────────────────

    def launch(self, target: str) -> str:
        """Attempt to launch *target*. Returns a human-readable status message."""
        if not target or not target.strip():
            return "No application name provided."

        raw = target.strip()
        lower = raw.lower()
        logger.info("AppLauncher: requested '%s'", raw)

        # 0a. Direct URL
        if lower.startswith(("http://", "https://", "www.")):
            return self._open_url(raw)

        # 0b. Direct existing file/folder path
        target_path = Path(raw).expanduser()
        if target_path.exists():
            try:
                os.startfile(str(target_path))
                return f"Opened {raw}."
            except Exception as e:
                logger.warning("AppLauncher: direct path open failed for '%s': %s", raw, e)

        # 1. Learned alias cache -- instant exact hit
        if lower in self._alias_cache:
            entry = self._alias_cache[lower]
            path = entry.get("path", "")
            try:
                os.startfile(path)
                entry["launched_at"] = time.time()
                self._alias_cache[lower] = entry
                _save_alias_cache(self._alias_cache)
                return f"Launched {os.path.basename(path)} (from cache)."
            except Exception as e:
                logger.warning("AppLauncher: cached path stale for '%s' (%s), re-resolving", lower, e)
                del self._alias_cache[lower]

        # 2. Alias resolution (shorthand only, e.g. "vscode" -> "Visual Studio Code")
        resolved = self._ALIASES.get(lower, raw)
        if resolved.lower() != raw.lower():
            logger.info("AppLauncher: resolved '%s' -> '%s'", raw, resolved)

        # 3. Merged fuzzy search across all discovery sources
        candidates: List[Tuple[str, str]] = []
        candidates.extend(self._scan_start_apps())
        candidates.extend(self._scan_start_menu())
        candidates.extend(self._scan_steam_library())
        candidates.extend(self._scan_registry_uninstall())

        if candidates:
            scored: List[Tuple[int, str, str]] = []
            for name, path in candidates:
                score = _fuzzy_score(resolved, name)
                if score > 0:
                    scored.append((score, name, path))

            if scored:
                scored.sort(key=lambda x: x[0], reverse=True)

                question = _disambiguate(scored)
                if question:
                    return question

                best_score, best_name, best_path = scored[0]
                try:
                    os.startfile(best_path)
                    self._alias_cache[lower] = {"path": best_path, "launched_at": time.time()}
                    _save_alias_cache(self._alias_cache)
                    logger.info("AppLauncher: launched '%s' (score=%d)", best_name, best_score)
                    return f"Launched {best_name}."
                except Exception as e:
                    logger.error("AppLauncher: launch failed for '%s': %s", best_name, e)
                    return f"Failed to launch {best_name}: {e}"

        # 4. Registry App Paths (exact/near-exact, no fuzzy scoring)
        result = self._try_registry(resolved)
        if result:
            return result

        # 5. PATH / shutil.which
        result = self._try_path(resolved)
        if result:
            return result

        # 6. os.startfile fallback
        result = self._try_startfile(resolved)
        if result:
            return result

        # 7. Retry the above three with the original raw input if alias changed it
        if resolved.lower() != raw.lower():
            for method in (self._try_registry, self._try_path, self._try_startfile):
                result = method(raw)
                if result:
                    return result

        return f"Could not find application: {raw}"

    # ── Discovery Methods ─────────────────────────────────────────────────

    def _open_url(self, url: str) -> str:
        try:
            os.startfile(url) if IS_WINDOWS else subprocess.Popen(["xdg-open", url])
            return f"Opened URL: {url}"
        except Exception as e:
            return f"Failed to open URL {url}: {e}"

    def _scan_start_apps(self) -> List[Tuple[str, str]]:
        """Scan all registered Windows Start apps (including Windows Store / UWP / MSIX apps)."""
        if self._start_apps_cache is not None:
            return self._start_apps_cache
        self._start_apps_cache = []
        if not IS_WINDOWS:
            return self._start_apps_cache

        try:
            import csv
            import io
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-StartApps | ConvertTo-Csv -NoTypeInformation"],
                capture_output=True, text=True, errors="replace", timeout=10,
            )
            if res.returncode == 0:
                reader = csv.DictReader(io.StringIO(res.stdout))
                for row in reader:
                    name = (row.get("Name") or "").strip()
                    appid = (row.get("AppID") or "").strip()
                    if name and appid and not appid.startswith("http"):
                        if os.path.exists(appid):
                            self._start_apps_cache.append((name, appid))
                        else:
                            self._start_apps_cache.append((name, f"shell:AppsFolder\\{appid}"))
        except Exception as e:
            logger.warning("AppLauncher: Get-StartApps scan failed: %s", e)

        logger.info("AppLauncher: cached %d StartApps entries", len(self._start_apps_cache))
        return self._start_apps_cache

    def _scan_start_menu(self) -> List[Tuple[str, str]]:
        if self._shortcut_cache is not None:
            return self._shortcut_cache

        shortcuts: List[Tuple[str, str]] = []
        if not IS_WINDOWS:
            self._shortcut_cache = shortcuts
            return shortcuts

        dirs = [
            os.path.join(os.environ.get("ProgramData", "C:\\ProgramData"),
                         "Microsoft", "Windows", "Start Menu", "Programs"),
            os.path.join(os.environ.get("APPDATA", ""),
                         "Microsoft", "Windows", "Start Menu", "Programs"),
        ]

        for d in dirs:
            if not os.path.isdir(d):
                continue
            for root, _, files in os.walk(d):
                for f in files:
                    if f.lower().endswith(".lnk"):
                        stem = os.path.splitext(f)[0]
                        full = os.path.join(root, f)
                        shortcuts.append((stem, full))

        self._shortcut_cache = shortcuts
        logger.info("AppLauncher: cached %d Start Menu shortcuts", len(shortcuts))
        return shortcuts

    def _scan_steam_library(self) -> List[Tuple[str, str]]:
        if self._steam_cache is not None:
            return self._steam_cache
        self._steam_cache = []
        if not IS_WINDOWS or not winreg:
            return self._steam_cache

        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam") as key:
                install_path, _ = winreg.QueryValueEx(key, "InstallPath")
        except OSError:
            return self._steam_cache

        library_vdf = os.path.join(install_path, "steamapps", "libraryfolders.vdf")
        if not os.path.exists(library_vdf):
            return self._steam_cache

        library_paths = [install_path]
        try:
            with open(library_vdf, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if '"path"' in line:
                        parts = line.split('"')
                        if len(parts) >= 4:
                            p = parts[3].replace("\\\\", "\\")
                            if p not in library_paths:
                                library_paths.append(p)
        except OSError:
            pass

        for lp in library_paths:
            steamapps = os.path.join(lp, "steamapps")
            if not os.path.isdir(steamapps):
                continue
            for file in os.listdir(steamapps):
                if file.startswith("appmanifest_") and file.endswith(".acf"):
                    appid = file[len("appmanifest_"):-len(".acf")]
                    try:
                        with open(os.path.join(steamapps, file), "r", encoding="utf-8", errors="ignore") as f:
                            for line in f:
                                if '"name"' in line:
                                    parts = line.split('"')
                                    if len(parts) >= 4:
                                        name = parts[3]
                                        self._steam_cache.append((name, f"steam://run/{appid}"))
                                    break
                    except OSError:
                        pass

        logger.info("AppLauncher: cached %d Steam library entries", len(self._steam_cache))
        return self._steam_cache

    def _scan_registry_uninstall(self) -> List[Tuple[str, str]]:
        if self._uninstall_cache is not None:
            return self._uninstall_cache
        self._uninstall_cache = []
        if not IS_WINDOWS or not winreg:
            return self._uninstall_cache

        keys_to_check = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        ]

        for hkey, subkey in keys_to_check:
            try:
                with winreg.OpenKey(hkey, subkey) as key:
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            subkey_name = winreg.EnumKey(key, i)
                            with winreg.OpenKey(key, subkey_name) as app_key:
                                try:
                                    name, _ = winreg.QueryValueEx(app_key, "DisplayName")
                                    icon, _ = winreg.QueryValueEx(app_key, "DisplayIcon")
                                    icon_path = icon.split(",")[0].strip('"')
                                    if icon_path.lower().endswith(".exe") and os.path.exists(icon_path):
                                        self._uninstall_cache.append((name, icon_path))
                                except OSError:
                                    pass
                        except OSError:
                            pass
            except OSError:
                pass

        logger.info("AppLauncher: cached %d registry uninstall entries", len(self._uninstall_cache))
        return self._uninstall_cache

    def _try_registry(self, query: str) -> Optional[str]:
        if not IS_WINDOWS or winreg is None:
            return None

        for exe_name in (query, f"{query}.exe"):
            try:
                key_path = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}"
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                    exe_path, _ = winreg.QueryValueEx(key, "")
                    if exe_path and os.path.isfile(exe_path):
                        subprocess.Popen([exe_path])
                        logger.info("AppLauncher: launched via Registry -- '%s'", exe_path)
                        return f"Launched {query}."
            except (FileNotFoundError, OSError):
                continue
        return None

    def _try_path(self, query: str) -> Optional[str]:
        found = shutil.which(query) or shutil.which(f"{query}.exe")
        if not found:
            for word in query.lower().split():
                found = shutil.which(word)
                if found:
                    break

        if found:
            try:
                subprocess.Popen([found])
                logger.info("AppLauncher: launched via PATH -- '%s'", found)
                return f"Launched {os.path.basename(found)}."
            except Exception as e:
                logger.error("AppLauncher: PATH launch failed for '%s': %s", found, e)
        return None

    def _try_startfile(self, query: str) -> Optional[str]:
        if not IS_WINDOWS:
            return None
        try:
            os.startfile(query)
            logger.info("AppLauncher: launched via os.startfile -- '%s'", query)
            return f"Launched {query}."
        except OSError:
            pass
        try:
            os.startfile(f"{query}.exe")
            return f"Launched {query}."
        except OSError:
            pass
        return None

    def invalidate_cache(self) -> None:
        """Force re-scan of all discovery sources on next launch attempt."""
        self._start_apps_cache = None
        self._shortcut_cache = None
        self._steam_cache = None
        self._uninstall_cache = None


# ═══════════════════════════════════════════════════════════════════════════
#  AppCloser -- Dynamic Application Closer
# ═══════════════════════════════════════════════════════════════════════════

class AppCloser:
    """Dynamically finds and terminates running applications.

    Uses psutil to scan all running processes and fuzzy-matches by:
      - Process name
      - Window title (on Windows via process.name() / cmdline)
    Gracefully terminates first, force-kills after timeout.

    On a successful close, also checks the alias cache: if any cached
    query resolves to a path matching one of the processes just closed,
    and that launch happened within the last ALIAS_INVALIDATE_WINDOW_SECONDS,
    the cache entry is removed -- treating "close X shortly after launch"
    as a signal that a fuzzy/cached match for X was wrong.
    """

    _PROCESS_ALIASES: Dict[str, List[str]] = {
        "chrome": ["chrome"],
        "firefox": ["firefox"],
        "edge": ["msedge"],
        "vscode": ["Code"],
        "vs code": ["Code"],
        "code": ["Code"],
        "word": ["WINWORD"],
        "excel": ["EXCEL"],
        "powerpoint": ["POWERPNT"],
        "ppt": ["POWERPNT"],
        "opera": ["opera"],
        "discord": ["Discord"],
        "steam": ["steam"],
        "spotify": ["Spotify"],
        "notepad": ["notepad"],
        "calculator": ["CalculatorApp", "Calculator"],
        "calc": ["CalculatorApp", "Calculator"],
        "paint": ["mspaint"],
        "explorer": ["explorer"],
        "terminal": ["WindowsTerminal"],
        "cmd": ["cmd"],
    }

    _PROTECTED = frozenset({
        "system", "smss", "csrss", "wininit", "winlogon", "services",
        "lsass", "svchost", "dwm", "taskhostw", "explorer",
        "sihost", "fontdrvhost", "ctfmon", "runtimebroker",
        "searchhost", "startmenuexperiencehost", "shellexperiencehost",
        "textinputhost", "securityhealthservice", "securityhealthsystray",
        "python", "python3", "pythonw",
    })

    def close(self, target: str) -> str:
        if not target or not target.strip():
            return "No application name provided."

        if not PSUTIL_AVAILABLE:
            return self._fallback_close(target)

        raw = target.strip()
        lower = raw.lower()
        logger.info("AppCloser: requested to close '%s'", raw)

        search_terms = self._PROCESS_ALIASES.get(lower, [raw])

        candidates: List[Tuple[int, "psutil.Process", str]] = []

        current_pid = os.getpid()
        for proc in psutil.process_iter(["pid", "name", "exe", "cmdline"]):
            try:
                if proc.pid == current_pid:
                    continue
                proc_name = proc.info["name"] or ""
                proc_name_lower = proc_name.lower()
                proc_stem = os.path.splitext(proc_name_lower)[0]

                if proc_stem in self._PROTECTED and lower not in self._PROTECTED:
                    continue

                best = 0
                for term in search_terms:
                    s = _fuzzy_score(term, proc_name_lower)
                    if s < 20 and proc.info.get("exe"):
                        exe_base = os.path.splitext(os.path.basename(proc.info["exe"]))[0]
                        s = max(s, _fuzzy_score(term, exe_base))
                    if s < 20 and proc.info.get("cmdline"):
                        # Only check the binary path or direct script argument, not arbitrary python eval code
                        leading_args = " ".join(proc.info["cmdline"][:2]).lower()
                        if term.lower() in leading_args:
                            s = max(s, 25)
                    best = max(best, s)

                if best >= 20:
                    candidates.append((best, proc, proc_name))

            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        if not candidates:
            return f"No running application found matching: {raw}"

        candidates.sort(key=lambda x: x[0], reverse=True)

        killed_names = set()
        killed_count = 0
        errors = []

        for score, proc, proc_name in candidates:
            try:
                proc.terminate()
                killed_names.add(proc_name)
                killed_count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                errors.append(f"{proc_name} (PID {proc.pid}): {e}")
                continue

        if killed_count > 0:
            time.sleep(0.5)
            for _, proc, proc_name in candidates:
                try:
                    if proc.is_running():
                        proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

        if killed_count > 0:
            names_str = ", ".join(sorted(killed_names))
            _invalidate_alias_cache_for_names(list(killed_names))
            msg = f"Closed {names_str}."
            if errors:
                msg += f" (Some processes couldn't be stopped: {'; '.join(errors)})"
            logger.info("AppCloser: closed %d processes -- %s", killed_count, names_str)
            return msg

        if errors:
            return f"Found matching processes but couldn't close them: {'; '.join(errors)}"

        return f"No running application found matching: {raw}"

    def _fallback_close(self, target: str) -> str:
        if not IS_WINDOWS:
            return "Cannot close applications without psutil on this platform."

        lower = target.strip().lower()
        search_terms = self._PROCESS_ALIASES.get(lower, [target.strip()])

        for term in search_terms:
            exe_name = term if term.endswith(".exe") else f"{term}.exe"
            try:
                result = subprocess.run(
                    ["taskkill", "/F", "/IM", exe_name, "/T"],
                    capture_output=True, text=True, errors="replace",
                )
                if result.returncode == 0:
                    logger.info("AppCloser: taskkill closed '%s'", exe_name)
                    _invalidate_alias_cache_for_names([exe_name])
                    return f"Closed {target.strip()}."
            except Exception as e:
                logger.error("AppCloser: taskkill failed for '%s': %s", exe_name, e)

        return f"Could not find running application: {target.strip()}"