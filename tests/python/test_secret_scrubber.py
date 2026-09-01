"""Unit tests for SecretScrubber: regex pattern redaction and Shannon entropy detection."""

from security.secret_scrubber import SecretScrubber


def test_secret_scrubber_api_keys():
    scrubber = SecretScrubber()
    sample = "Export OPENAI_API_KEY=sk-1234567890abcdef1234567890abcdef and GITHUB_TOKEN=ghp_1234567890abcdef1234567890abcdef1234"
    scrubbed = scrubber.scrub_text(sample)
    assert "sk-1234567890" not in scrubbed
    assert "ghp_1234567890" not in scrubbed
    assert "[REDACTED_SECRET]" in scrubbed


def test_secret_scrubber_private_keys():
    scrubber = SecretScrubber()
    sample = """
-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA0Y1234567890abcdef...
-----END RSA PRIVATE KEY-----
"""
    scrubbed = scrubber.scrub_text(sample)
    assert "MIIEowIBAAKCAQEA" not in scrubbed
    assert "[REDACTED_SECRET]" in scrubbed


def test_secret_scrubber_password_parameters():
    scrubber = SecretScrubber()
    sample = "postgres://admin:SuperSecretPass123!@localhost:5432/db"
    scrubbed = scrubber.scrub_text(sample)
    assert "SuperSecretPass123!" not in scrubbed


def test_secret_scrubber_dict():
    scrubber = SecretScrubber()
    data = {
        "user": "Alice",
        "api_key": "sk-1234567890abcdef1234567890abcdef",
        "nested": {
            "token": "ghp_1234567890abcdef1234567890abcdef1234",
            "safe_val": 42
        }
    }
    cleaned = scrubber.scrub_dict(data)
    assert cleaned["user"] == "Alice"
    assert cleaned["api_key"] == "[REDACTED_SECRET]"
    assert cleaned["nested"]["token"] == "[REDACTED_SECRET]"
    assert cleaned["nested"]["safe_val"] == 42
