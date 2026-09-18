"""Unit tests for sandbox security, command allowlisting, path validation, and env sanitization."""

import os
from pathlib import Path
import pytest

from auto_pr.sandbox.security import (
    validate_command,
    validate_path_containment,
    sanitize_environment,
)
from auto_pr.sandbox.models import (
    CommandDisallowedError,
    PathTraversalError,
)


def test_command_allowlisting_valid() -> None:
    """Verify that permitted toolchain binaries pass validation."""
    assert validate_command(["pytest", "tests/"]) == ["pytest", "tests/"]
    assert validate_command(["python", "-m", "unittest"]) == ["python", "-m", "unittest"]
    assert validate_command("ruff check .") == ["ruff", "check", "."]
    assert validate_command(["git", "status"]) == ["git", "status"]
    assert validate_command("npm test") == ["npm", "test"]


def test_command_disallowed_dangerous_binaries() -> None:
    """Verify that dangerous binaries are rejected immediately."""
    dangerous_commands = [
        ["rm", "-rf", "/"],
        ["del", "C:\\some_file.txt"],
        ["powershell", "-Command", "Get-Process"],
        ["cmd", "/c", "dir"],
        ["curl", "https://malicious.com"],
        ["wget", "https://malicious.com"],
        ["nc", "-lvp", "4444"],
        ["format", "C:"],
        ["shutdown", "/s"],
    ]

    for cmd in dangerous_commands:
        with pytest.raises(CommandDisallowedError):
            validate_command(cmd)


def test_command_disallowed_shell_injection_metacharacters() -> None:
    """Verify that shell metacharacters attempting chaining or piping are rejected."""
    injections = [
        ["pytest", ";", "rm", "-rf", "."],
        ["python", "-c", "print(1)", "&&", "python", "-c", "print(2)"],
        ["npm", "test", "|", "cat"],
        ["pytest", ">", "out.txt"],
        ["pytest", "`whoami`"],
        ["python", "$EVIL_VAR"],
    ]

    for cmd in injections:
        with pytest.raises(CommandDisallowedError) as exc_info:
            validate_command(cmd)
        assert "illegal shell metacharacter" in str(exc_info.value)


def test_path_traversal_prevention(tmp_path: Path) -> None:
    """Verify that paths attempting to escape sandbox root are rejected."""
    sandbox_root = tmp_path / "sandbox"
    sandbox_root.mkdir()

    # Valid internal path
    internal = sandbox_root / "src" / "app.py"
    assert validate_path_containment(internal, sandbox_root) == internal.resolve()

    # Traversal escaping sandbox
    with pytest.raises(PathTraversalError):
        validate_path_containment(sandbox_root / ".." / "other_dir", sandbox_root)

    with pytest.raises(PathTraversalError):
        validate_path_containment("/etc/passwd", sandbox_root)


def test_environment_sanitization() -> None:
    """Verify that host credentials and secrets are stripped from sandbox environment."""
    # Inject temporary secrets into os.environ
    os.environ["SECRET_API_KEY"] = "super-secret-key-12345"
    os.environ["GITHUB_TOKEN"] = "ghp_mocktoken1234567890123456789012345"
    os.environ["DATABASE_PASSWORD"] = "dbpass123"

    try:
        clean_env = sanitize_environment(extra_env={"CUSTOM_UNSAFE_TOKEN": "token123", "SAFE_VAR": "val"})

        # Secrets must NOT be present
        assert "SECRET_API_KEY" not in clean_env
        assert "GITHUB_TOKEN" not in clean_env
        assert "DATABASE_PASSWORD" not in clean_env
        assert "CUSTOM_UNSAFE_TOKEN" not in clean_env

        # Safe vars must be present
        assert clean_env.get("SAFE_VAR") == "val"
        assert clean_env.get("PYTHONUTF8") == "1"
        assert "PATH" in clean_env
    finally:
        os.environ.pop("SECRET_API_KEY", None)
        os.environ.pop("GITHUB_TOKEN", None)
        os.environ.pop("DATABASE_PASSWORD", None)
