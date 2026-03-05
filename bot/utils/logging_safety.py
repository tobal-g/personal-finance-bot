"""Helpers to keep secrets out of logs."""

import re

_PATTERNS = (
    # Telegram bot token in API paths, e.g. /bot123456:ABC.../sendMessage
    re.compile(r"/bot[^/\s]+"),
    # Generic Telegram bot token
    re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b"),
    # OpenAI-style keys
    re.compile(r"\bsk-[A-Za-z0-9_-]{10,}\b"),
)


def redact_sensitive(value: object) -> str:
    """Return a string with common API key/token patterns redacted."""
    text = str(value)
    for pattern in _PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text
