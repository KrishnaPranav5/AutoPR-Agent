"""Security controls, command allowlisting, environment sanitization, and path guards."""

import os
from pathlib import Path
from typing import Sequence

from auto_pr.sandbox.models import CommandDisallowedError, PathTraversalError

# Strictly allowlisted executable binaries for validation and build
ALLOWED_BINARIES: set[str] = {
    "pytest",
    "python",
    "python3",
    "py",
    "npm",
    "npx",
    "cargo",
    "go",
    "ruff",
    "mypy",
    "flake8",
    "pip",
    "uv",
    "git",
}

# Dangerous binaries explicitly forbidden
DISALLOWED_BINARIES: set[str] = {
    "rm",
    "rmdir",
    "del",
    "erase",
    "format",
    "shutdown",
    "powershell",
    "powershell.exe",
    "pwsh",
    "cmd",
    "cmd.exe",
    "bash",
    "sh",
    "zsh",
    "curl",
    "wget",
    "nc",
    "netcat",
    "telnet",
    "eval",
    "sudo",
    "su",
}

# Shell metacharacters that indicate attempts to chain or redirect commands
DANGEROUS_SHELL_TOKENS: set[str] = {
    ";",
    "&&",
    "||",
    "|",
    ">",
    "<",
    ">>",
    "&",
    "$",
    "`",
    "\n",
    "\r",
}

# Safe environment variable names permitted to pass to the sandbox process
SAFE_ENV_VAR_KEYS: set[str] = {
    "PATH",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "HOME",
    "LANG",
    "LC_ALL",
    "PYTHONPATH",
    "PYTHONIOENCODING",
    "PYTHONUTF8",
    "VIRTUAL_ENV",
}


def sanitize_environment(extra_env: dict[str, str] | None = None) -> dict[str, str]:
    """Build a sanitized environment dictionary stripped of host credentials.

    LLM API keys, database URLs, git tokens, and host secrets are completely
    excluded.
    """
    import sys

    clean_env: dict[str, str] = {}

    for key, value in os.environ.items():
        if key.upper() in SAFE_ENV_VAR_KEYS:
            clean_env[key] = value

    # Prepend virtual environment or active Python Scripts/bin to PATH
    scripts_dir = Path(sys.prefix) / ("Scripts" if os.name == "nt" else "bin")
    if scripts_dir.is_dir():
        current_path = clean_env.get("PATH", "")
        clean_env["PATH"] = f"{scripts_dir}{os.pathsep}{current_path}"

    # Always enforce UTF-8 for Python subprocesses
    clean_env["PYTHONUTF8"] = "1"
    clean_env["PYTHONIOENCODING"] = "utf-8"

    # Merge safe extra environment variables if provided
    if extra_env:
        for k, v in extra_env.items():
            k_upper = k.upper()
            if not any(secret in k_upper for secret in ("TOKEN", "KEY", "SECRET", "PASS", "AUTH")):
                clean_env[k] = v

    return clean_env


def validate_command(command: Sequence[str] | str) -> list[str]:
    """Validate tokenized command against allowlist and shell injection guards.

    Returns:
        Tokenized list of arguments.
    Raises:
        CommandDisallowedError: If command or arguments violate security rules.
    """
    import shlex

    if isinstance(command, str):
        try:
            tokens = shlex.split(command, posix=(os.name != "nt"))
        except ValueError:
            tokens = command.strip().split()
    else:
        tokens = list(command)

    if not tokens:
        raise CommandDisallowedError("Cannot execute an empty command.")

    # 1. Check root binary
    raw_binary = tokens[0]
    binary_name = Path(raw_binary).name.lower()
    if binary_name.endswith(".exe"):
        binary_name = binary_name[:-4]

    if binary_name in DISALLOWED_BINARIES:
        raise CommandDisallowedError(
            f"Command binary '{binary_name}' is explicitly forbidden in sandbox execution."
        )

    if binary_name not in ALLOWED_BINARIES:
        raise CommandDisallowedError(
            f"Command binary '{binary_name}' is not in the sandbox allowlist ({sorted(ALLOWED_BINARIES)})."
        )

    # Check if this is a python -c invocation
    is_python_c = binary_name in ("python", "python3", "py") and "-c" in tokens

    # 2. Check for shell injection operators inside arguments
    for token in tokens:
        # Check if entire token is a shell control operator
        if token in DANGEROUS_SHELL_TOKENS:
            raise CommandDisallowedError(
                f"Command contains illegal shell metacharacter '{token}'."
            )

        # Check for dangerous metacharacters within token
        for dangerous in (";", "&&", "||", "|", ">", "<", ">>", "&", "`", "$"):
            if dangerous == ";" and is_python_c:
                continue  # Semicolons are valid Python syntax inside python -c
            if dangerous in token:
                raise CommandDisallowedError(
                    f"Command argument '{token}' contains illegal shell metacharacter '{dangerous}'."
                )

    return tokens


def validate_path_containment(target_path: Path | str, sandbox_root: Path | str) -> Path:
    """Ensure target path is strictly located within sandbox root directory.

    Raises:
        PathTraversalError: If the path attempts to traverse outside sandbox root.
    """
    root_resolved = Path(sandbox_root).resolve()
    target_resolved = Path(target_path).resolve()

    try:
        # commonpath will raise ValueError if on different drives (on Windows)
        common = Path(os.path.commonpath([root_resolved, target_resolved])).resolve()
        if common != root_resolved:
            raise PathTraversalError(
                f"Path traversal detected: '{target_path}' resolves outside sandbox root '{sandbox_root}'."
            )
    except ValueError as err:
        raise PathTraversalError(
            f"Path traversal detected: '{target_path}' is on a different drive or invalid relative to sandbox root: {err}"
        ) from err

    return target_resolved
