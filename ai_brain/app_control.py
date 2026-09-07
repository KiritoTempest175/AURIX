"""AURIX AI Brain -- Dynamic App Control (Launch & Close).

Pure-Python module that dynamically discovers and manages applications
on Windows. No hardcoded app lists -- uses runtime discovery via:
  - Start Menu shortcut scanning
  - Windows Registry App Paths
  - PATH environment scanning
  - psutil process enumeration with fuzzy matching

Only a minimal alias map is kept for common shorthand convenience.

Fix log (Phase A.1 -- fuzzy matching false positives):
  Session log showed three real wrong-launch bugs, all traced to the same root
  cause: `_fuzzy_score`'s substring-matching tiers (score 40/20) accepted a
  match whenever ANY query word >2 chars appeared as a bare substring inside a
  candidate name, with a flat acceptance threshold of >=20. Short query words
  are substrings of huge numbers of unrelated candidate names:
    - "nte"   is a substring of "Internet Download Manager" -> wrongly launched IDM
    - "drive" is a substring of "RecoveryDrive"              -> wrongly launched RecoveryDrive
    - "vs code" partially word-matched "Developer Command Prompt for VS 2022"
      as well as (or better than) the real "Visual Studio Code" shortcut, and
      the old flat threshold couldn't tell the two apart.

  Fix: (1) substring-tier matching now requires query words of length >=4
  (was >2) to even be considered, and its maximum achievable score was lowered
  so a *pure* substring-only match can no longer clear the acceptance bar on
  its own for short/medium queries; (2) the acceptance threshold now scales
  with query length instead of being a flat 20, since short queries need much
  stronger evidence than long ones; (3) when the top match isn't clearly ahead
  of the next-best candidate, launch is refused and both/all close candidates
  are returned for disambiguation instead of silently picking one.

  Trade-off, stated honestly: this makes matching stricter, which fixes the
  three wrong-launch bugs and correctly still resolves "games" -> Epic Games
  Launcher and "google" -> Google Chrome (both still pass). It does NOT fix
  "vs code" resolving to the *correct* Visual Studio Code shortcut -- with the
  stricter thresholds it now correctly refuses to guess between the two
  VS-related shortcuts rather than picking the wrong one, but doesn't have
  enough signal to confidently pick the right one either. That's a real gap;
  closing it needs either better discovery data (so "Visual Studio Code"'s
  shortcut is unambiguously distinguishable) or the learned-alias cache
  (Part A.3 of the LUNA AI Brain directive) so a one-time correction is
  remembered -- neither is implemented in this file.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
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


# ═══════════════════════════════════════════════════════════════════════════
#  Fuzzy Matching Utilities
# ═══════════════════════════════════════════════════════════════════════════

# Minimum length a query word must have to be eligible for SUBSTRING (not
# whole-word) matching. Raised from the previous >2 to >=4: this is what stops
# 3-letter fragments like "nte" from matching inside unrelated long words like
# "Internet".
_MIN_SUBSTRING_WORD_LEN = 4


def _fuzzy_score(query: str, candidate: str) -> int:
    """Score how well *query* matches *candidate* (higher = better).

    Returns 0 if no match at all.
    Scoring tiers:
        100 -- exact match
         80 -- candidate starts with query
         60 -- query starts with candidate (user typed more than needed)
         50 -- all query words found as whole words inside candidate (high confidence)
         30 -- all query words found only as bare substrings inside candidate (low confidence)
          0 to 29 -- partial word/substring overlap (low confidence, scaled down)
          0 -- no match
    """
    q = query.lower().strip()
    c = candidate.lower().strip()

    if q == c:
        return 100
    if c.startswith(q):
        return 80
    if q.startswith(c):
        return 60

    q_words = q.split()
    c_words = c.split()

    word_matches = sum(1 for w in q_words if w in c_words)

    # Substring matching: only for words long enough that a coincidental match
    # inside an unrelated word is unlikely (see _MIN_SUBSTRING_WORD_LEN note above).
    substr_matches = sum(1 for w in q_words if len(w) >= _MIN_SUBSTRING_WORD_LEN and w in c)

    if word_matches == len(q_words) and word_matches > 0:
        return 50

    # Lowered from 40 -> 30 (Phase A.1 fix): a purely-substring-based match is
    # inherently lower confidence than a whole-word match, and 30 sits below
    # the length-scaled acceptance threshold (see _min_acceptable_score) for
    # anything shorter than a fairly specific 6+ character query -- so a bare
    # substring hit alone can no longer silently win for short/medium queries.
    if substr_matches == len(q_words) and substr_matches > 0:
        return 30

    # Partial matches -- capped low, same intent as before but working off the
    # stricter substr_matches count.
    if word_matches > 0:
        return 15 + int((word_matches / len(q_words)) * 10)
    if substr_matches > 0 and (substr_matches / len(q_words)) >= 0.5:
        return 15

    return 0


def _min_acceptable_score(query: str) -> int:
    """Minimum score required to accept a match at all, scaled by query length.

    Short queries carry much less information than long ones, so the same raw
    score means very different things: a 40 for a 3-character query is almost
    certainly coincidental (see the "nte" bug); a 40 for an 8-character query
    is much more likely to be a real, specific match. This directly replaces
    the old flat `score >= 20` threshold that accepted both cases equally.
    """
    n = len(query.strip())
    if n <= 3:
        return 80   # only exact / clear-prefix matches for very short queries
    if n <= 5:
        return 50   # must be at least a whole-word match, not a bare substring hit
    return 30       # longer, more specific queries may rely on substring matches


@dataclass
class MatchResult:
    """Result of attempting to resolve a query against a candidate pool."""
    status: str  # "matched" | "ambiguous" | "none"
    top_name: str = ""
    top_path: str = ""
    top_score: int = 0
    alternatives: List[Tuple[str, str, int]] = field(default_factory=list)  # (name, path, score)


def find_best_match(
    query: str,
    candidates: List[Tuple[str, str]],
    ambiguity_margin: int = 12,
) -> MatchResult:
    """Score every candidate against *query* and decide whether there's a
    single confident winner, an ambiguous tie, or no acceptable match.

    Args:
        query: The user's typed/spoken target.
        candidates: List of (name, path) pairs to score against.
        ambiguity_margin: If the runner-up scores within this many points of
            the top match (and isn't just the same underlying path), the
            match is considered ambiguous rather than auto-resolved.
    """
    if not candidates:
        return MatchResult(status="none")

    scored = sorted(
        ((name, path, _fuzzy_score(query, name)) for name, path in candidates),
        key=lambda item: item[2],
        reverse=True,
    )

    top_name, top_path, top_score = scored[0]
    min_score = _min_acceptable_score(query)

    if top_score < min_score or top_score <= 0:
        return MatchResult(status="none")

    close_alternatives: List[Tuple[str, str, int]] = []
    for name, path, score in scored[1:]:
        if path == top_path:
            continue  # same underlying target under a different label -- not a real alternative
        if top_score - score <= ambiguity_margin:
            close_alternatives.append((name, path, score))
        else:
            break  # sorted descending, so nothing further can be within the margin either

    if close_alternatives:
        return MatchResult(
            status="ambiguous",
            top_name=top_name,
            top_path=top_path,
            top_score=top_score,
            alternatives=close_alternatives,
        )

    return MatchResult(status="matched", top_name=top_name, top_path=top_path, top_score=top_score)


# ═══════════════════════════════════════════════════════════════════════════
#  AppLauncher -- Dynamic Application Launcher
# ═══════════════════════════════════════════════════════════════════════════

class AppLauncher:
    """Dynamically discovers and launches applications on Windows.

    Discovery pipeline (tried in order, first hit wins):
        1. Minimal alias resolution (convenience shorthand only)
        2. Start Menu shortcut (.lnk) scanning with fuzzy match
        3. Windows Registry App Paths lookup
        4. PATH / shutil.which() scan
        5. os.startfile() fallback (let Windows figure it out)
        6. Direct URL pass-through

    NOTE: Additional discovery sources (Steam library manifests, Epic Games
    manifests, Windows Uninstall registry keys) and the learned-alias cache
    described in the LUNA AI Brain directive (Part A.2/A.3) are NOT included
    in this file -- they need real installed-application data to write and
    verify against, which isn't available in an isolated review/fix pass like
    this one. This file only fixes the fuzzy-matching false-positive bugs
    (Part A.1) in the existing Start Menu discovery path.
    """

    def __init__(self) -> None:
        self._shortcut_cache: Optional[List[Tuple[str, str]]] = None  # (name, path)

    # ── Public API ────────────────────────────────────────────────────────

    def launch(self, target: str) -> str:
        """Attempt to launch *target*. Returns a human-readable status message."""
        if not target or not target.strip():
            return "No application name provided."

        raw = target.strip()
        logger.info("AppLauncher: requested '%s'", raw)

        # 0. Direct URL
        lower = raw.lower()
        if lower.startswith(("http://", "https://", "www.")):
            return self._open_url(raw)

        # 1. Start Menu shortcut scan
        result = self._try_start_menu(raw)
        if result:
            return result

        # 2. Registry App Paths
        result = self._try_registry(raw)
        if result:
            return result

        # 3. PATH / shutil.which
        result = self._try_path(raw)
        if result:
            return result

        # 4. os.startfile fallback
        result = self._try_startfile(raw)
        if result:
            return result

        return f"Could not find application: {raw}"

    # ── Discovery Methods ─────────────────────────────────────────────────

    def _open_url(self, url: str) -> str:
        """Open a URL in the default browser."""
        try:
            os.startfile(url) if IS_WINDOWS else subprocess.Popen(["xdg-open", url])
            return f"Opened URL: {url}"
        except Exception as e:
            return f"Failed to open URL {url}: {e}"

    def _scan_start_menu(self) -> List[Tuple[str, str]]:
        """Scan Start Menu directories for .lnk shortcuts. Cached after first scan."""
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

    def _try_start_menu(self, query: str) -> Optional[str]:
        """Search Start Menu shortcuts for the best fuzzy match.

        FIX (Phase A.1): now goes through find_best_match() instead of a
        simple max-score loop with a flat >=20 threshold. This both raises
        the bar for short/ambiguous queries and, when the top two candidates
        are genuinely close, refuses to guess and asks the caller to
        disambiguate instead of silently launching the higher-scoring one.
        """
        shortcuts = self._scan_start_menu()
        if not shortcuts:
            return None

        result = find_best_match(query, shortcuts)

        if result.status == "matched":
            try:
                os.startfile(result.top_path)
                logger.info(
                    "AppLauncher: launched via Start Menu -- '%s' (score=%d)",
                    result.top_name, result.top_score,
                )
                return f"Launched {result.top_name}."
            except Exception as e:
                logger.error("AppLauncher: Start Menu launch failed for '%s': %s", result.top_name, e)
                return None

        if result.status == "ambiguous":
            options = [result.top_name] + [alt[0] for alt in result.alternatives]
            logger.info(
                "AppLauncher: ambiguous match for '%s' -- candidates: %s", query, options
            )
            names = ", ".join(f"'{n}'" for n in options[:4])
            return f"That's ambiguous -- did you mean {names}? Please be more specific."

        return None

    def _try_registry(self, query: str) -> Optional[str]:
        """Look up application in Windows Registry App Paths."""
        if not IS_WINDOWS or winreg is None:
            return None

        # Try direct exe name
        exe_candidates = [query, f"{query}.exe"]
        for exe_name in exe_candidates:
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
        """Search PATH for matching executable."""
        # Try exact name first
        found = shutil.which(query)
        if not found:
            found = shutil.which(f"{query}.exe")
        if not found:
            # Try without spaces (e.g., "file explorer" -> "explorer")
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
        """Last resort: let Windows try to figure it out via os.startfile or shell."""
        if not IS_WINDOWS:
            return None
        try:
            os.startfile(query)
            logger.info("AppLauncher: launched via os.startfile -- '%s'", query)
            return f"Launched {query}."
        except OSError:
            pass

        # Try appending .exe
        try:
            os.startfile(f"{query}.exe")
            return f"Launched {query}."
        except OSError:
            pass

        return None

    def invalidate_cache(self) -> None:
        """Force re-scan of Start Menu on next launch attempt."""
        self._shortcut_cache = None


# ═══════════════════════════════════════════════════════════════════════════
#  AppCloser -- Dynamic Application Closer
# ═══════════════════════════════════════════════════════════════════════════

class AppCloser:
    """Dynamically finds and terminates running applications.

    Uses psutil to scan all running processes and fuzzy-matches by:
      - Process name
      - Window title (on Windows via process.name() / cmdline)
    Gracefully terminates first, force-kills after timeout.

    NOTE: This class's matching logic was NOT part of the demonstrated bug
    log (the failures shown were all launch-side), so it hasn't been touched
    beyond continuing to use the shared, now-fixed _fuzzy_score(). If closing
    the wrong process is ever observed in practice, it should go through the
    same find_best_match()/ambiguity treatment as AppLauncher above.
    """

    # System-critical processes we must NEVER kill
    _PROTECTED = frozenset({
        "system", "smss", "csrss", "wininit", "winlogon", "services",
        "lsass", "svchost", "dwm", "taskhostw", "explorer",
        "sihost", "fontdrvhost", "ctfmon", "runtimebroker",
        "searchhost", "startmenuexperiencehost", "shellexperiencehost",
        "textinputhost", "securityhealthservice", "securityhealthsystray",
    })

    def close(self, target: str) -> str:
        """Attempt to close application matching *target*. Returns status message."""
        if not target or not target.strip():
            return "No application name provided."

        if not PSUTIL_AVAILABLE:
            return self._fallback_close(target)

        raw = target.strip()
        lower = raw.lower()
        logger.info("AppCloser: requested to close '%s'", raw)

        # Scan running processes
        search_terms = [lower]
        candidates: List[Tuple[int, "psutil.Process", str]] = []  # (score, process, matched_name)

        for proc in psutil.process_iter(["pid", "name", "exe", "cmdline"]):
            try:
                proc_name = proc.info["name"] or ""
                proc_name_lower = proc_name.lower()

                # Skip protected system processes
                proc_stem = os.path.splitext(proc_name_lower)[0]
                if proc_stem in self._PROTECTED:
                    continue

                # Score against each search term
                best = 0
                for term in search_terms:
                    s = _fuzzy_score(term, proc_name_lower)
                    # Also check the exe path basename
                    if s < 20 and proc.info.get("exe"):
                        exe_base = os.path.splitext(os.path.basename(proc.info["exe"]))[0]
                        s = max(s, _fuzzy_score(term, exe_base))
                    best = max(best, s)

                if best >= _min_acceptable_score(raw):
                    candidates.append((best, proc, proc_name))

            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        if not candidates:
            return f"No running application found matching: {raw}"

        # Sort by score descending -- kill the best matches
        candidates.sort(key=lambda x: x[0], reverse=True)

        # Group by process name to report cleanly
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

        # Wait briefly then force-kill stragglers
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
            msg = f"Closed {names_str}."
            if errors:
                msg += f" (Some processes couldn't be stopped: {'; '.join(errors)})"
            logger.info("AppCloser: closed %d processes -- %s", killed_count, names_str)
            return msg

        if errors:
            return f"Found matching processes but couldn't close them: {'; '.join(errors)}"

        return f"No running application found matching: {raw}"

    def _fallback_close(self, target: str) -> str:
        """Fallback when psutil is not installed -- use taskkill on Windows."""
        if not IS_WINDOWS:
            return "Cannot close applications without psutil on this platform."

        search_terms = [target.strip()]

        for term in search_terms:
            exe_name = term if term.endswith(".exe") else f"{term}.exe"
            try:
                result = subprocess.run(
                    ["taskkill", "/F", "/IM", exe_name, "/T"],
                    capture_output=True, text=True, errors="replace",
                )
                if result.returncode == 0:
                    logger.info("AppCloser: taskkill closed '%s'", exe_name)
                    return f"Closed {target.strip()}."
            except Exception as e:
                logger.error("AppCloser: taskkill failed for '%s': %s", exe_name, e)

        return f"Could not find running application: {target.strip()}"