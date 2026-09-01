"""LUNA Secret Scrubber & Privacy Redaction Module.

Identifies and redacts credentials, API keys, private certificates, and high-entropy
tokens from telemetry logs, terminal I/O streams, and training datasets before persistence.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Pattern, Tuple


class SecretScrubber:
    """Scrubs sensitive secrets, tokens, and credentials from text strings and structured logs."""

    # Pre-compiled high-confidence regular expressions for common credential patterns
    PATTERNS: List[Tuple[str, Pattern[str]]] = [
        ("OPENAI_KEY", re.compile(r"sk-[a-zA-Z0-9]{20,60}")),
        ("GITHUB_TOKEN", re.compile(r"gh[pousr]-[A-Za-z0-9_]{36,255}")),
        ("AWS_KEY", re.compile(r"(?:AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}")),
        ("AWS_SECRET", re.compile(r"(?i)aws_secret_access_key\s*=\s*[A-Za-z0-9/+=]{40}")),
        ("GENERIC_BEARER", re.compile(r"(?i)bearer\s+[a-zA-Z0-9_\-\.]{20,}")),
        ("PRIVATE_KEY", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")),
        ("PASSWORD_PARAM", re.compile(r"(?i)(password|passwd|pwd|secret|api_key|apikey|auth_token)\s*[:=]\s*['\"]?([^\s'\"]{4,})['\"]?")),
        ("URI_CREDENTIAL", re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://([^:]+):([^@]+)@")),
        ("SLACK_TOKEN", re.compile(r"xox[baprs]-[0-9a-zA-Z]{10,48}")),
        ("JWT_TOKEN", re.compile(r"eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+")),
    ]

    def __init__(self, entropy_threshold: float = 4.3, min_token_len: int = 16) -> None:
        """Initialize scrubber.

        Args:
            entropy_threshold: Shannon entropy threshold above which isolated strings are flagged.
            min_token_len: Minimum character length for entropy-based token detection.
        """
        self.entropy_threshold = entropy_threshold
        self.min_token_len = min_token_len

    @staticmethod
    def calculate_shannon_entropy(data: str) -> float:
        """Calculate the Shannon entropy of a string."""
        if not data:
            return 0.0
        entropy = 0.0
        length = len(data)
        frequencies: Dict[str, int] = {}
        for char in data:
            frequencies[char] = frequencies.get(char, 0) + 1

        for count in frequencies.values():
            p_x = count / length
            entropy -= p_x * math.log2(p_x)
        return entropy

    def scrub_text(self, text: str, replacement: str = "[REDACTED_SECRET]") -> str:
        """Scrub known secret patterns and high-entropy tokens from input text.

        Args:
            text: Input string.
            replacement: Text to substitute for identified secrets.

        Returns:
            Sanitized text string.
        """
        if not text:
            return ""

        scrubbed = text

        # 1. Pattern matching replacements
        for name, pattern in self.PATTERNS:
            if name == "PASSWORD_PARAM":
                # Only redact the value group
                scrubbed = pattern.sub(r"\1=[REDACTED_SECRET]", scrubbed)
            elif name == "URI_CREDENTIAL":
                scrubbed = pattern.sub(r"protocol://[REDACTED_USER]:[REDACTED_SECRET]@", scrubbed)
            else:
                scrubbed = pattern.sub(replacement, scrubbed)

        # 2. Token-level Shannon entropy scan for isolated high-entropy strings
        words = scrubbed.split()
        sanitized_words: List[str] = []
        for word in words:
            # Strip common punctuation around token
            cleaned = word.strip("'\":;,\r\n()[]{}")
            if len(cleaned) >= self.min_token_len and not cleaned.startswith("[REDACTED"):
                # Exclude standard file paths, URLs or alphabetic english text
                if not (cleaned.startswith("http") or "/" in cleaned or "\\" in cleaned):
                    # Check if token contains mix of digits or special chars
                    has_digits = any(c.isdigit() for c in cleaned)
                    has_upper = any(c.isupper() for c in cleaned)
                    has_lower = any(c.islower() for c in cleaned)
                    if (has_digits and (has_upper or has_lower)) or any(c in "-_+=." for c in cleaned):
                        entropy = self.calculate_shannon_entropy(cleaned)
                        if entropy >= self.entropy_threshold:
                            word = word.replace(cleaned, replacement)
            sanitized_words.append(word)

        return " ".join(sanitized_words)

    def scrub_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively scrub strings within dictionary structures."""
        cleaned: Dict[str, Any] = {}
        for key, value in data.items():
            # Check key name
            if any(term in key.lower() for term in ["password", "secret", "token", "api_key", "apikey"]):
                cleaned[key] = "[REDACTED_SECRET]"
            elif isinstance(value, str):
                cleaned[key] = self.scrub_text(value)
            elif isinstance(value, dict):
                cleaned[key] = self.scrub_dict(value)
            elif isinstance(value, list):
                cleaned[key] = [
                    self.scrub_text(v) if isinstance(v, str) else (self.scrub_dict(v) if isinstance(v, dict) else v)
                    for v in value
                ]
            else:
                cleaned[key] = value
        return cleaned


_GLOBAL_SCRUBBER: SecretScrubber = SecretScrubber()


def get_default_scrubber() -> SecretScrubber:
    """Return default singleton SecretScrubber."""
    return _GLOBAL_SCRUBBER
