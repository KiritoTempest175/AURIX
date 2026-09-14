import time

from security.permissions import (
    ActionCategory,
    PermissionManager,
)

from ai_brain.tool_executor import (
    ToolExecutor,
)


def test_trust_token_requires_exact_resource():
    manager = PermissionManager()

    token = manager.grant_trust_token(
        category=ActionCategory.FILE_DELETE,
        target_resource="path=C:/test/file.txt",
        request_fingerprint="abc123",
    )

    assert token.is_valid(
        ActionCategory.FILE_DELETE,
        "path=C:/test/file.txt",
        "abc123",
    )

    assert not token.is_valid(
        ActionCategory.FILE_DELETE,
        "path=C:/test/file.txt.backup",
        "abc123",
    )


def test_trust_token_rejects_changed_fingerprint():
    manager = PermissionManager()

    token = manager.grant_trust_token(
        category=ActionCategory.SHELL_EXEC,
        target_resource="command=echo hello",
        request_fingerprint="approved",
    )

    assert not token.is_valid(
        ActionCategory.SHELL_EXEC,
        "command=echo hello",
        "changed",
    )


def test_token_is_single_use():
    manager = PermissionManager()

    token = manager.grant_trust_token(
        category=ActionCategory.FILE_DELETE,
        target_resource="path=test.txt",
        request_fingerprint="fingerprint",
    )

    first = manager.validate_action(
        category=ActionCategory.FILE_DELETE,
        target_resource="path=test.txt",
        token_id=token.token_id,
        operation="delete_item",
        operation_args={
            "path": "test.txt"
        },
        request_fingerprint="fingerprint",
    )

    assert first is True

    second = manager.validate_action(
        category=ActionCategory.FILE_DELETE,
        target_resource="path=test.txt",
        token_id=token.token_id,
        operation="delete_item",
        operation_args={
            "path": "test.txt"
        },
        request_fingerprint="fingerprint",
    )

    assert second is False


def test_existing_file_overwrite_requires_confirmation(
    tmp_path,
):
    file_path = (
        tmp_path
        / "important.txt"
    )

    file_path.write_text(
        "original",
        encoding="utf-8",
    )

    manager = PermissionManager(
        config={
            "security": {
                "trust_token_required": True,
                "allowed_project_paths": [
                    str(tmp_path)
                ],
            }
        }
    )

    required = manager.requires_trust_token(
        category=ActionCategory.FILE_WRITE,
        target_resource=f"path={file_path}",
        operation="write_file",
        operation_args={
            "path": str(file_path),
            "content": "changed",
            "append": False,
        },
    )

    assert required is True


def test_new_file_inside_workspace_is_allowed(
    tmp_path,
):
    file_path = (
        tmp_path
        / "new_file.txt"
    )

    manager = PermissionManager(
        config={
            "security": {
                "trust_token_required": True,
                "allowed_project_paths": [
                    str(tmp_path)
                ],
            }
        }
    )

    required = manager.requires_trust_token(
        category=ActionCategory.FILE_WRITE,
        target_resource=f"path={file_path}",
        operation="write_file",
        operation_args={
            "path": str(file_path),
            "content": "hello",
            "append": False,
        },
    )

    assert required is False


def test_move_always_requires_confirmation(
    tmp_path,
):
    source = (
        tmp_path
        / "one.txt"
    )

    destination = (
        tmp_path
        / "two.txt"
    )

    manager = PermissionManager(
        config={
            "security": {
                "trust_token_required": True,
                "allowed_project_paths": [
                    str(tmp_path)
                ],
            }
        }
    )

    required = manager.requires_trust_token(
        category=ActionCategory.FILE_WRITE,
        target_resource=(
            f"source={source}"
            f"|destination={destination}"
        ),
        operation="move_item",
        operation_args={
            "source": str(source),
            "destination": str(destination),
        },
    )

    assert required is True


def test_pending_security_request_expires():
    executor = ToolExecutor()

    reply = executor.execute(
        "shell_exec",
        {
            "command": "echo test"
        },
    )

    assert reply.startswith(
        "TRUST_TOKEN_REQUIRED:"
    )

    request_id = reply.split(
        ":",
        2,
    )[1]

    executor._pending_actions[
        request_id
    ]["expires_at"] = (
        time.time() - 1
    )

    result = executor.confirm_pending(
        request_id
    )

    assert "expired" in result.lower()


def test_changed_pending_action_is_rejected():
    executor = ToolExecutor()

    reply = executor.execute(
        "shell_exec",
        {
            "command": "echo safe"
        },
    )

    assert reply.startswith(
        "TRUST_TOKEN_REQUIRED:"
    )

    request_id = reply.split(
        ":",
        2,
    )[1]

    executor._pending_actions[
        request_id
    ]["args"]["command"] = (
        "echo changed"
    )

    result = executor.confirm_pending(
        request_id
    )

    assert (
        "changed" in result.lower()
        or "cancelled" in result.lower()
    )


def test_youtube_download_is_file_write():
    executor = ToolExecutor()

    category = executor._get_category(
        "youtube",
        {
            "action": "download",
            "url": "https://example.com/video",
        },
    )

    assert (
        category
        == ActionCategory.FILE_WRITE
    )


def test_move_target_binds_source_and_destination():
    executor = ToolExecutor()

    target = executor._get_target(
        "move_item",
        {
            "source": "C:/one.txt",
            "destination": "D:/two.txt",
        },
    )

    assert "source=C:/one.txt" in target
    assert "destination=D:/two.txt" in target