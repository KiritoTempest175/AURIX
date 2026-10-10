"""Typed Git operations must reject untrusted directories and shell injection."""
import subprocess
import pytest
from ai_brain.developer_tools import DeveloperTools


def test_without_trusted_root_denies_project(tmp_path):
    tools = DeveloperTools({"security": {"allowed_project_paths": []}})
    with pytest.raises(PermissionError):
        tools.repo(str(tmp_path))


def test_untrusted_sibling_prefix_is_rejected(tmp_path):
    root = tmp_path / "trusted"
    sibling = tmp_path / "trusted-evil"
    root.mkdir()
    sibling.mkdir()
    tools = DeveloperTools({"security": {"allowed_project_paths": [str(root)]}})
    with pytest.raises(PermissionError):
        tools.repo(str(sibling))


def test_ambiguous_project_requires_explicit_target(tmp_path):
    a = tmp_path / "one"
    b = tmp_path / "two"
    a.mkdir()
    b.mkdir()
    tools = DeveloperTools({"security": {"allowed_project_paths": [str(a), str(b)]}})
    with pytest.raises(ValueError, match="Specify"):
        tools.repo("")


def test_git_never_runs_through_shell(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    tool = DeveloperTools({"security": {"allowed_project_paths": [str(root)]}})
    kwargs_seen = {}
    def fake_run(argv, **kwargs):
        kwargs_seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)
    tool.commit(str(root), 'Update files; rm -rf /')
    assert kwargs_seen["shell"] is False
