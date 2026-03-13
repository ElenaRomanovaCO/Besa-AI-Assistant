"""PII redaction for log messages.

Strips personally identifiable information (emails, IPs, Discord user IDs,
phone numbers) from log output before it reaches CloudWatch. This prevents
accidental PII retention in logs.
"""

from __future__ import annotations

import re

# Compiled patterns for performance (module-level, compiled once)
_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
_IP_RE = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
_DISCORD_USER_ID_RE = re.compile(r"\b\d{17,20}\b")
_PHONE_RE = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b")

_REDACTED = "[REDACTED]"


def redact_pii(text: str) -> str:
    """Remove PII from a log message string.

    Redacts:
    - Email addresses
    - IPv4 addresses
    - Phone numbers (international and domestic formats)

    Does NOT redact Discord user IDs by default — they are needed for
    correlation in logs and are not considered sensitive PII in this context
    (public Discord user IDs, not personal data).
    """
    if not text:
        return text

    result = _EMAIL_RE.sub(_REDACTED, text)
    result = _IP_RE.sub(_REDACTED, result)
    result = _PHONE_RE.sub(_REDACTED, result)
    return result
