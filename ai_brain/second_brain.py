"""AURIX Second Brain — Runtime memory vault for Luna.

A local, Obsidian-compatible markdown vault with programmatic read/write
access.  Provides structured episodic logging, fact persistence with
contradiction detection, history archival, goal tracking, correction
logging, keyword search (vector-ready interface), periodic consolidation,
and session-context assembly.

Usage::

    from ai_brain.second_brain import SecondBrain

    brain = SecondBrain("vault")
    ctx   = brain.load_context()
    brain.write_fact("user prefers dark mode", "stated")

Dependencies: stdlib + pyyaml
"""

from __future__ import annotations

import contextlib
import datetime
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Callable, Generator

# ---------------------------------------------------------------------------
# Platform-specific advisory file locking
# ---------------------------------------------------------------------------
if os.name == "nt":
    import msvcrt

    def _os_lock(fd: int) -> None:
        """Acquire an exclusive byte-range lock (Windows)."""
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)

    def _os_unlock(fd: int) -> None:
        """Release a byte-range lock (Windows)."""
        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
else:
    import fcntl  # type: ignore[import-not-found]

    def _os_lock(fd: int) -> None:  # type: ignore[misc]
        """Acquire an exclusive flock (POSIX)."""
        fcntl.flock(fd, fcntl.LOCK_EX)

    def _os_unlock(fd: int) -> None:  # type: ignore[misc]
        """Release a flock (POSIX)."""
        fcntl.flock(fd, fcntl.LOCK_UN)

try:
    import yaml
except ImportError:
    raise ImportError(
        "pyyaml is required for frontmatter parsing: pip install pyyaml"
    )

# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------
_FM_RE = re.compile(r"\A---[ \t]*\r?\n(.*?\r?\n)---[ \t]*\r?\n", re.DOTALL)
_FACT_RE = re.compile(
    r"^- \[(\d{4}-\d{2}-\d{2})\] \[(\w+)\](?: \[sensitive\])? (.+)",
)


# ═══════════════════════════════════════════════════════════════════════════
#  SecondBrain
# ═══════════════════════════════════════════════════════════════════════════
class SecondBrain:
    """Local, Obsidian-compatible markdown vault with runtime read/write
    access for the AURIX/Luna desktop AI.

    Parameters
    ----------
    vault_path : str | Path
        Root directory of the vault.  Relative paths are resolved from the
        project root (parent of ``ai_brain/``).
    """

    # ── constructor ───────────────────────────────────────────────────────

    def __init__(self, vault_path: str | Path) -> None:
        p = Path(vault_path)
        if not p.is_absolute():
            p = Path(__file__).resolve().parent.parent / p
        self.vault_path: Path = p.resolve()
        self.last_meta: dict[str, Any] = {}

    # ── path resolution ───────────────────────────────────────────────────

    def _resolve(self, file: str) -> Path:
        """Resolve *file* relative to vault root; reject escapes."""
        resolved = (self.vault_path / file).resolve()
        if not str(resolved).startswith(str(self.vault_path)):
            raise ValueError(f"Path escapes vault boundary: {file}")
        return resolved

    # ── frontmatter helpers ───────────────────────────────────────────────

    @staticmethod
    def _parse_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
        """Split YAML frontmatter from markdown body.

        Returns ``(metadata_dict, body_string)``.
        """
        m = _FM_RE.match(raw)
        if m:
            try:
                meta = yaml.safe_load(m.group(1)) or {}
            except yaml.YAMLError:
                meta = {}
            return meta, raw[m.end():]
        return {}, raw

    @staticmethod
    def _build_frontmatter(meta: dict[str, Any]) -> str:
        """Serialize *meta* into a ``---``-fenced YAML block."""
        blob = yaml.dump(meta, default_flow_style=False, sort_keys=False)
        return f"---\n{blob.rstrip()}\n---\n\n"

    @staticmethod
    def _default_meta(
        type_: str = "config",
        confidence: str = "stated",
    ) -> dict[str, Any]:
        """Return a minimal frontmatter dict with today's date."""
        today = datetime.date.today().isoformat()
        return {
            "type": type_,
            "created": today,
            "updated": today,
            "confidence": confidence,
            "sensitive": False,
            "salience": 0,
        }

    # ── concurrency primitives ────────────────────────────────────────────

    @contextlib.contextmanager
    def _file_lock(self, path: Path) -> Generator[None, None, None]:
        """Acquire an advisory exclusive lock via a sidecar ``.lock`` file.

        Uses ``msvcrt.locking`` on Windows and ``fcntl.flock`` on POSIX.
        The lock is released in the ``finally`` clause even on exceptions.
        """
        lock_path = path.parent / (path.name + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        try:
            # Ensure the file has at least 1 byte so the lock range is valid
            os.write(fd, b"L")
            os.lseek(fd, 0, os.SEEK_SET)
            _os_lock(fd)
            yield
        finally:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                _os_unlock(fd)
            except OSError:
                pass
            os.close(fd)
            with contextlib.suppress(OSError):
                os.unlink(str(lock_path))

    def _atomic_write(self, path: Path, content: str) -> None:
        """Write *content* atomically via temp-file → ``os.replace``."""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(path.parent), suffix=".tmp", prefix=".sb_",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                fh.write(content)
            os.replace(tmp, str(path))
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def _locked_append(self, path: Path, content: str) -> None:
        """Append *content* to *path* under an exclusive lock."""
        with self._file_lock(path):
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8", newline="") as fh:
                fh.write(content)

    def _locked_read_write(
        self, path: Path, transform: Callable[[str], str],
    ) -> None:
        """Read *path*, apply *transform*, write back atomically — all
        under an exclusive lock so no concurrent writer can interleave."""
        with self._file_lock(path):
            old = path.read_text(encoding="utf-8") if path.exists() else ""
            self._atomic_write(path, transform(old))

    # ══════════════════════════════════════════════════════════════════════
    #  PUBLIC API
    # ══════════════════════════════════════════════════════════════════════

    # ── read ──────────────────────────────────────────────────────────────

    def read(self, file: str) -> str:
        """Load a vault file's body.

        The parsed YAML frontmatter is stored in ``self.last_meta`` for
        inspection after calling this method.

        Parameters
        ----------
        file : str
            Path relative to vault root, e.g. ``"memory/facts.md"``.

        Returns
        -------
        str
            The markdown body (everything after the frontmatter fence).
        """
        path = self._resolve(file)
        if not path.exists():
            self.last_meta = {}
            return ""
        raw = path.read_text(encoding="utf-8")
        self.last_meta, body = self._parse_frontmatter(raw)
        return body

    # ── write_fact ────────────────────────────────────────────────────────

    def write_fact(
        self,
        text: str,
        confidence: str,
        sensitive: bool = False,
    ) -> None:
        """Append a tagged, dated fact to ``memory/facts.md``.

        Before appending, existing facts are scanned for contradictions
        (matching key before the colon, different value after it).
        Contradicted facts are struck through with a date pointer to the
        replacement — **never** silently duplicated.

        Parameters
        ----------
        text : str
            Fact body, preferably in ``key: value`` form.
        confidence : str
            One of ``stated``, ``inferred``, ``observed``.
        sensitive : bool
            If ``True`` the fact is tagged ``[sensitive]`` and excluded
            from ``load_context()`` output by default.
        """
        today = datetime.date.today().isoformat()
        sens = " [sensitive]" if sensitive else ""
        new_line = f"- [{today}] [{confidence}]{sens} {text}"

        # Extract key portion (text before the first colon)
        new_key = (
            text.split(":", 1)[0].strip().lower() if ":" in text else None
        )

        facts_path = self._resolve("memory/facts.md")

        def _transform(content: str) -> str:
            meta, body = self._parse_frontmatter(content)
            meta["updated"] = today

            # No key:value structure — just append
            if new_key is None:
                body = body.rstrip("\n") + "\n" + new_line + "\n"
                return self._build_frontmatter(meta) + body

            # Scan for contradictions
            lines = body.split("\n")
            out: list[str] = []
            flagged = False
            for line in lines:
                m = _FACT_RE.match(line)
                if m and not line.lstrip().startswith("~~"):
                    existing_text = m.group(3)
                    existing_key = (
                        existing_text.split(":", 1)[0].strip().lower()
                        if ":" in existing_text
                        else None
                    )
                    if (
                        existing_key
                        and existing_key == new_key
                        and existing_text.strip() != text.strip()
                    ):
                        # Strike through the old fact and mark as superseded
                        out.append(f"~~{line}~~ → superseded [{today}]")
                        flagged = True
                        continue
                out.append(line)

            body = "\n".join(out).rstrip("\n") + "\n" + new_line + "\n"
            if flagged:
                body += (
                    f"  > ⚠️ Contradiction: previous value for "
                    f"'{new_key}' was superseded.\n"
                )
            return self._build_frontmatter(meta) + body

        self._locked_read_write(facts_path, _transform)

    # ── log_episodic ──────────────────────────────────────────────────────

    def log_episodic(self, event: str) -> None:
        """Append a timestamped entry to the current month's episodic file.

        Creates ``memory/episodic/YYYY-MM.md`` on first use with proper
        frontmatter and a month heading.
        """
        now = datetime.datetime.now()
        month_tag = now.strftime("%Y-%m")
        path = self._resolve(f"memory/episodic/{month_tag}.md")
        stamp = now.strftime("%Y-%m-%d %H:%M")
        entry = f"- [{stamp}] {event}\n"

        if not path.exists():
            meta = self._default_meta("event", "observed")
            header = (
                self._build_frontmatter(meta)
                + f"# Episodic Memory — {now.strftime('%B %Y')}\n\n"
            )
            self._atomic_write(path, header)

        self._locked_append(path, entry)

    # ── log_history ───────────────────────────────────────────────────────

    def log_history(self, command: str, response: str) -> None:
        """Append a command / response pair to the current month's history
        log at ``history/log/YYYY-MM.md``."""
        now = datetime.datetime.now()
        month_tag = now.strftime("%Y-%m")
        path = self._resolve(f"history/log/{month_tag}.md")
        stamp = now.strftime("%Y-%m-%d %H:%M:%S")
        entry = (
            f"\n### [{stamp}]\n"
            f"**Command:** {command}\n\n"
            f"**Response:** {response}\n\n---\n"
        )

        if not path.exists():
            meta = self._default_meta("event", "observed")
            header = (
                self._build_frontmatter(meta)
                + f"# Interaction Log — {now.strftime('%B %Y')}\n\n"
            )
            self._atomic_write(path, header)

        self._locked_append(path, entry)

    # ── write_correction ──────────────────────────────────────────────────

    def write_correction(self, what_went_wrong: str, fix: str) -> None:
        """Append a correction to ``corrections.md`` with a timestamp."""
        today = datetime.date.today().isoformat()
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = (
            f"\n### [{stamp}] Correction\n"
            f"- **Issue:** {what_went_wrong}\n"
            f"- **Fix:** {fix}\n"
            f"- **Applied:** {today}\n\n"
        )
        path = self._resolve("corrections.md")

        def _transform(content: str) -> str:
            meta, body = self._parse_frontmatter(content)
            meta["updated"] = today
            return self._build_frontmatter(meta) + body.rstrip("\n") + "\n" + entry

        self._locked_read_write(path, _transform)

    # ── update_goal ───────────────────────────────────────────────────────

    def update_goal(self, text: str, status: str) -> None:
        """Add or update an entry in ``goals.md``.

        If an existing goal contains *text* (case-insensitive), its
        checkbox status is updated in-place.  Otherwise a new goal line is
        appended.

        Parameters
        ----------
        text : str
            Goal description (used as a fuzzy key for matching).
        status : str
            One of ``pending``, ``active``, ``done`` / ``completed``.
        """
        today = datetime.date.today().isoformat()
        char_map = {
            "done": "x", "completed": "x", "active": "/", "pending": " ",
        }
        status_char = char_map.get(status.lower(), " ")
        path = self._resolve("goals.md")

        def _transform(content: str) -> str:
            meta, body = self._parse_frontmatter(content)
            meta["updated"] = today

            lines = body.split("\n")
            updated = False
            out: list[str] = []
            for line in lines:
                gm = re.match(r"^(\s*- \[)([x /])\]\s*(.+)", line)
                if gm and text.lower() in gm.group(3).lower():
                    # Strip old update annotations before rewriting
                    clean = re.sub(r"\s*\*\((?:added|updated) .*?\)\*", "", gm.group(3)).strip()
                    out.append(
                        f"{gm.group(1)}{status_char}] {clean}"
                        f" *(updated {today})*"
                    )
                    updated = True
                else:
                    out.append(line)

            if not updated:
                out.append(f"- [{status_char}] {text} *(added {today})*")

            return self._build_frontmatter(meta) + "\n".join(out) + "\n"

        self._locked_read_write(path, _transform)

    # ── search ────────────────────────────────────────────────────────────

    def search(self, query: str) -> list[str]:
        """Search vault files for lines matching all *query* keywords.

        Current backend: simple keyword/grep across ``*.md`` files.
        The interface is designed so a vector-index backend (stored in
        ``.index/``) can replace the body of this method without changing
        any calling code.

        Returns
        -------
        list[str]
            Matching lines prefixed with ``[relative/path:line_no]``.
        """
        keywords = query.lower().split()
        if not keywords:
            return []

        results: list[str] = []
        for md in sorted(self.vault_path.rglob("*.md")):
            rel = md.relative_to(self.vault_path)
            # Skip generated index and lock artefacts
            if ".index" in rel.parts or ".lock" in md.suffix:
                continue
            try:
                raw = md.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            meta, body = self._parse_frontmatter(raw)
            if meta.get("sensitive"):
                continue
            for lineno, line in enumerate(body.split("\n"), 1):
                if all(kw in line.lower() for kw in keywords):
                    results.append(f"[{rel}:{lineno}] {line.strip()}")
        return results

    # ── consolidate ───────────────────────────────────────────────────────

    def consolidate(self, period: str) -> None:
        """Run the periodic reflection pass for *period* (e.g. ``"2026-09"``).

        Three-stage pipeline:

        1. **Summarise** the month's raw interaction log into
           ``history/history_summary.md``.
        2. **Promote** recurring episodic mentions (≥ 3 occurrences) into
           ``memory/facts.md`` as ``inferred`` facts.
        3. **Flag** contradictions in ``memory/facts.md`` for manual review
           rather than auto-resolving them.
        """
        today = datetime.date.today().isoformat()

        # ── stage 1: summarise history log ────────────────────────────────
        log_path = self._resolve(f"history/log/{period}.md")
        if log_path.exists():
            _, log_body = self._parse_frontmatter(
                log_path.read_text(encoding="utf-8"),
            )
            commands = re.findall(r"\*\*Command:\*\*\s*(.+)", log_body)

            word_freq: dict[str, int] = {}
            for cmd in commands:
                for w in re.findall(r"\b[a-z]{4,}\b", cmd.lower()):
                    word_freq[w] = word_freq.get(w, 0) + 1
            top = sorted(word_freq.items(), key=lambda x: -x[1])[:10]

            summary = (
                f"\n## {period} (consolidated {today})\n"
                f"- **Interactions:** {len(commands)}\n"
            )
            if top:
                summary += (
                    "- **Top themes:** "
                    + ", ".join(f"{w} ({n}×)" for w, n in top)
                    + "\n"
                )
            summary += "\n"

            summary_path = self._resolve("history/history_summary.md")

            def _upd_summary(content: str) -> str:
                meta, body = self._parse_frontmatter(content)
                meta["updated"] = today
                return (
                    self._build_frontmatter(meta)
                    + body.rstrip("\n") + "\n" + summary
                )

            self._locked_read_write(summary_path, _upd_summary)

        # ── stage 2: promote recurring episodic items ─────────────────────
        ep_path = self._resolve(f"memory/episodic/{period}.md")
        if ep_path.exists():
            _, ep_body = self._parse_frontmatter(
                ep_path.read_text(encoding="utf-8"),
            )
            phrase_freq: dict[str, int] = {}
            for line in ep_body.split("\n"):
                m = re.match(r"- \[.*?\] (.+)", line)
                if m:
                    for w in re.findall(r"\b[a-z]{5,}\b", m.group(1).lower()):
                        phrase_freq[w] = phrase_freq.get(w, 0) + 1

            for word, count in phrase_freq.items():
                if count >= 3:
                    self.write_fact(
                        f"recurring mention: '{word}' appeared {count}× "
                        f"in {period} episodic log (auto-promoted)",
                        "inferred",
                    )

        # ── stage 3: flag contradictions ──────────────────────────────────
        facts_path = self._resolve("memory/facts.md")
        if facts_path.exists():
            _, facts_body = self._parse_frontmatter(
                facts_path.read_text(encoding="utf-8"),
            )
            by_key: dict[str, list[str]] = {}
            for fm in _FACT_RE.finditer(facts_body):
                txt = fm.group(3)
                if ":" in txt:
                    k = txt.split(":", 1)[0].strip().lower()
                    by_key.setdefault(k, []).append(txt.strip())

            conflicts = [
                f"- ⚠️ `{k}` → {sorted(set(vals))}"
                for k, vals in by_key.items()
                if len(set(vals)) > 1
            ]
            if conflicts:
                self._locked_append(
                    facts_path,
                    f"\n## Contradictions flagged ({today})\n"
                    + "\n".join(conflicts)
                    + "\n",
                )

    # ── load_context ──────────────────────────────────────────────────────

    def load_context(
        self,
        session_start: bool = True,
        *,
        include_sensitive: bool = False,
    ) -> str:
        """Assemble working context for a new or continuing session.

        **Load order:** ``model.md`` → ``vault_index.md`` → memory files
        (scratch, corrections, facts, preferences, about_me).

        Sensitive-flagged content is **excluded** by default.  Pass
        ``include_sensitive=True`` to override.

        Parameters
        ----------
        session_start : bool
            If ``True`` (default), load the full memory context suitable
            for initialising a fresh conversation.
        include_sensitive : bool
            If ``True``, include files and lines marked ``sensitive``.
        """

        def _load(file: str) -> str:
            body = self.read(file)
            if not body:
                return ""
            # File-level sensitive gate
            if self.last_meta.get("sensitive") and not include_sensitive:
                return ""
            # Line-level sensitive gate
            if not include_sensitive:
                body = "\n".join(
                    ln for ln in body.split("\n")
                    if "[sensitive]" not in ln.lower()
                )
            return body.strip()

        parts: list[str] = []

        # Always load model identity first
        if txt := _load("model.md"):
            parts.append(txt)

        # Vault structure orientation
        if txt := _load("vault_index.md"):
            parts.append(txt)

        if session_start:
            for f in (
                "memory/working/session_scratch.md",
                "corrections.md",
                "memory/facts.md",
                "memory/preferences.md",
                "about_me.md",
            ):
                if txt := _load(f):
                    parts.append(txt)

        return "\n\n---\n\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
#  CLI sanity checks
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    vault_root = Path(__file__).resolve().parent.parent / "vault"
    brain = SecondBrain(vault_root)
    print("=== SecondBrain Sanity Checks ===\n")

    # read
    body = brain.read("model.md")
    print(
        f"[read]             model.md -> {len(body)} chars, "
        f"meta keys: {list(brain.last_meta.keys())}"
    )

    # write_fact -- normal
    brain.write_fact("favorite editor: VS Code", "stated")
    print("[write_fact]       favorite editor: VS Code")

    # write_fact -- contradiction
    brain.write_fact("favorite editor: Neovim", "stated")
    print("[write_fact]       favorite editor: Neovim  (should flag contradiction)")

    # write_fact -- sensitive
    brain.write_fact("API key: sk-REDACTED-EXAMPLE", "stated", sensitive=True)
    print("[write_fact]       sensitive fact written")

    # log_episodic
    brain.log_episodic("SecondBrain module initialised and tested.")
    print("[log_episodic]     Logged init event")

    # log_history
    brain.log_history("run sanity checks", "All methods executed successfully.")
    print("[log_history]      Logged test interaction")

    # write_correction
    brain.write_correction(
        "Test scenario: no actual error",
        "No fix needed -- sanity check only.",
    )
    print("[write_correction] Logged test correction")

    # update_goal
    brain.update_goal("Implement Second Brain runtime module", "done")
    print("[update_goal]      Goal marked done")

    # search
    hits = brain.search("editor")
    print(f"[search]           'editor' -> {len(hits)} hit(s)")
    for h in hits[:5]:
        print(f"                   {h}")

    # load_context -- default (sensitive excluded)
    ctx = brain.load_context()
    print(f"\n[load_context]     {len(ctx)} chars  (sensitive=excluded)")
    assert "sk-REDACTED" not in ctx, "Sensitive content leaked into context!"

    # load_context -- with sensitive
    ctx_all = brain.load_context(include_sensitive=True)
    print(f"[load_context]     {len(ctx_all)} chars  (sensitive=included)")

    # consolidate (current month)
    month = datetime.datetime.now().strftime("%Y-%m")
    brain.consolidate(month)
    print(f"[consolidate]      Consolidated {month}")

    print("\n=== All sanity checks passed. ===")

