"""Unit tests for secret and credential redaction engine."""

from auto_pr.security.redaction import (
    redact_text,
    redact_dict,
    redact_data,
    register_secret_to_redact,
)


def test_redact_github_tokens() -> None:
    raw_text = "Cloning with token ghp_1234567890abcdefghijklmnopqrstuvwxyz12 and secret"
    redacted = redact_text(raw_text)
    assert "ghp_1234567890abcdefghijklmnopqrstuvwxyz12" not in redacted
    assert "[REDACTED_GITHUB_TOKEN]" in redacted


def test_redact_openai_key() -> None:
    raw_text = "Using OpenAI key sk-abcdef1234567890abcdef1234567890 in client initialization"
    redacted = redact_text(raw_text)
    assert "sk-abcdef1234567890abcdef1234567890" not in redacted
    assert "[REDACTED_OPENAI_KEY]" in redacted


def test_redact_bearer_token() -> None:
    raw_text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz123"
    redacted = redact_text(raw_text)
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz123" not in redacted
    assert "[REDACTED_BEARER_TOKEN]" in redacted


def test_redact_private_key() -> None:
    raw_text = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEA0Y1+abcdefghijklmnopqrstuvwxyz\n"
        "-----END RSA PRIVATE KEY-----"
    )
    redacted = redact_text(raw_text)
    assert "MIIEowIBAAKCAQEA0Y1+abcdefghijklmnopqrstuvwxyz" not in redacted
    assert "[REDACTED_PRIVATE_KEY]" in redacted


def test_dynamic_secret_registration() -> None:
    custom_secret = "super-secret-vault-password-xyz"
    register_secret_to_redact(custom_secret)

    sample = f"Connecting using {custom_secret} on port 5432"
    redacted = redact_text(sample)
    assert custom_secret not in redacted
    assert "[REDACTED_CUSTOM_SECRET]" in redacted


def test_redact_nested_dictionary() -> None:
    payload = {
        "user": "developer",
        "api_key": "raw_sensitive_string",
        "github_token": "ghp_1234567890abcdefghijklmnopqrstuvwxyz12",
        "nested": {
            "password": "my_db_password",
            "safe_field": "public_data",
            "auth_header": "Bearer secret_jwt_token_value_12345",
        },
        "tags": ["env:prod", "sk-proj-1234567890abcdef1234567890"],
    }
    redacted = redact_dict(payload)

    # Key-based redaction
    assert redacted["api_key"] == "[REDACTED_SENSITIVE_VALUE]"
    assert redacted["github_token"] == "[REDACTED_SENSITIVE_VALUE]"
    assert redacted["nested"]["password"] == "[REDACTED_SENSITIVE_VALUE]"
    assert redacted["nested"]["auth_header"] == "[REDACTED_SENSITIVE_VALUE]"

    # Safe field untouched
    assert redacted["user"] == "developer"
    assert redacted["nested"]["safe_field"] == "public_data"

    # Pattern-based redaction inside list
    assert "sk-proj-1234567890abcdef1234567890" not in redacted["tags"][1]
    assert "[REDACTED_OPENAI_KEY]" in redacted["tags"][1]
