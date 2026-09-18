"""Secret and credential redaction engine.

Protects prompts, logs, database audit records, and agent communications
from accidental exposure of credentials, tokens, and private keys.
"""

import re
from typing import Any

# Regular expressions for common secret formats
SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("GITHUB_TOKEN", re.compile(r"gh[pous]_[A-Za-z0-9_]{36,255}")),
    ("GITHUB_PAT", re.compile(r"github_pat_[A-Za-z0-9_]{82}")),
    ("AWS_KEY", re.compile(r"(?:AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}")),
    ("OPENAI_KEY", re.compile(r"sk-[a-zA-Z0-9_-]{20,}")),
    ("GEMINI_KEY", re.compile(r"AIza[0-9A-Za-z-_]{35}")),
    ("SLACK_TOKEN", re.compile(r"xox[baprs]-[0-9]{12}-[0-9]{12}-[a-zA-Z0-9]{24,}")),
    ("BEARER_TOKEN", re.compile(r"(?i)bearer\s+[a-zA-Z0-9_\-\.]{20,}")),
    (
        "PRIVATE_KEY",
        re.compile(
            r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"
        ),
    ),
]

# Sensitive keys in dictionary structures
SENSITIVE_KEY_SUBSTRINGS = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "auth",
    "credential",
    "private_key",
    "access_key",
)

# Dynamically registered secrets (e.g. loaded from environment at startup)
_REGISTERED_SECRETS: set[str] = set()


def register_secret_to_redact(secret: str) -> None:
    """Register a specific secret string to be redacted dynamically."""
    if secret and len(secret.strip()) >= 6:
        _REGISTERED_SECRETS.add(secret.strip())


def clear_registered_secrets() -> None:
    """Clear all dynamically registered secrets (useful in test teardown)."""
    _REGISTERED_SECRETS.clear()


def redact_text(text: str) -> str:
    """Redact known secret patterns and registered secrets from text string."""
    if not text or not isinstance(text, str):
        return text

    sanitized = text

    # Redact dynamically registered secrets first
    for secret in _REGISTERED_SECRETS:
        if secret in sanitized:
            sanitized = sanitized.replace(secret, "[REDACTED_CUSTOM_SECRET]")

    # Redact pattern-matched secrets
    for name, pattern in SECRET_PATTERNS:
        sanitized = pattern.sub(f"[REDACTED_{name}]", sanitized)

    return sanitized


def is_sensitive_key(key: str) -> bool:
    """Check whether a dictionary key name indicates sensitive content."""
    k_lower = key.lower()
    return any(substr in k_lower for substr in SENSITIVE_KEY_SUBSTRINGS)


def redact_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively redact sensitive key-values and text in a dictionary."""
    result: dict[str, Any] = {}
    for k, v in data.items():
        if is_sensitive_key(str(k)):
            result[k] = "[REDACTED_SENSITIVE_VALUE]"
        else:
            result[k] = redact_data(v)
    return result


def redact_data(obj: Any) -> Any:
    """Recursively redact arbitrary data structures (strings, lists, dicts)."""
    if isinstance(obj, str):
        return redact_text(obj)
    if isinstance(obj, dict):
        return redact_dict(obj)
    if isinstance(obj, (list, tuple, set)):
        items = [redact_data(item) for item in obj]
        if isinstance(obj, tuple):
            return tuple(items)
        if isinstance(obj, set):
            return set(items)
        return items
    return obj
