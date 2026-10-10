"""Narrow, typed Git tools. Never pass model text to a shell.

Every path must be inside an explicitly configured workspace. Git writes and
publishing are separately authorized by the central Tier-3 policy.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from security.config_loader import load_config

_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")


class DeveloperTools:
    def __init__(self, config=None):
        cfg = config if config is not None else load_config()
        self.allowed = [
            Path(p).expanduser().resolve()
            for p in cfg.get("security", {}).get("allowed_project_paths", [])
            if isinstance(p, str) and p.strip()
        ]

    def repo(self, raw: str) -> Path:
        """Resolve precisely one configured Git worktree; never guess between projects."""
        if raw:
            target = Path(raw).expanduser().resolve()
        elif len(self.allowed) == 1:
            target = self.allowed[0]
        else:
            raise ValueError("Specify the project path or configure exactly one trusted project root")
        if not any(target == root or root in target.parents for root in self.allowed):
            raise PermissionError("Project is outside configured trusted roots")
        if not (target / ".git").exists():
            raise ValueError("Target is not a Git worktree root")
        return target

    def _run(self, repo: Path, args: list[str], timeout: int = 30) -> str:
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GIT_OPTIONAL_LOCKS"] = "0"
        # Argument array only. No cmd.exe, PowerShell or shell interpolation.
        try:
            completed = subprocess.run(
                ["git", "-C", str(repo), *args],
                shell=False, capture_output=True, text=True,
                errors="replace", timeout=timeout, env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Git operation exceeded time limit") from exc
        except FileNotFoundError as exc:
            raise RuntimeError("Git for Windows is not installed") from exc
        output = (completed.stdout + "\n" + completed.stderr).strip()
        if completed.returncode != 0:
            raise RuntimeError(f"Git operation returned exit code {completed.returncode}")
        return output[:8000]

    def active_branch(self, raw: str) -> str:
        repo = self.repo(raw)
        branch = self._run(repo, ["branch", "--show-current"]).strip()
        if not _BRANCH.fullmatch(branch) or branch.startswith("-"):
            raise ValueError("Detached HEAD or unsupported branch name")
        return branch

    def status(self, raw: str) -> str:
        repo = self.repo(raw)
        branch = self.active_branch(raw)
        output = self._run(repo, ["status", "--short", "--branch"])
        return f"Repository: {repo.name} / {branch}\n{output or 'Clean tree'}"

    def commit(self, raw: str, message: str) -> str:
        repo = self.repo(raw)
        clean = message.strip()
        if not clean or len(clean) > 180 or "\n" in clean:
            raise ValueError("Provide a concise single-line commit message")
        # No automatic git add -A; must use user-staged files to avoid
        # accidentally publishing secrets, personal data, or generated weights.
        return self._run(repo, ["commit", "-m", clean], timeout=60)

    def push(self, raw: str, branch: str) -> str:
        repo = self.repo(raw)
        active = self.active_branch(raw)
        if branch != active or not _BRANCH.fullmatch(branch):
            raise ValueError("Only the verified currently checked-out branch can be pushed")
        # Never force push, never accept a user-controlled remote name.
        return self._run(repo, ["push", "origin", branch], timeout=60)
