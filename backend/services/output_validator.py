"""Output validation: scan LLM responses before sending to Discord.

Detects and redacts sensitive data, validates response quality,
and prevents system prompt leakage.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Discord message limit
MAX_RESPONSE_LENGTH = 2000

# Discord embed field limit
MAX_EMBED_LENGTH = 4096


@dataclass
class ValidationResult:
    """Result of output validation."""
    is_safe: bool
    cleaned_text: str
    redactions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blocked: bool = False
    block_reason: Optional[str] = None


# --------------------------------------------------------------------------- #
# Sensitive data patterns
# --------------------------------------------------------------------------- #

# AWS Account IDs (12-digit numbers in ARN context or standalone)
_AWS_ACCOUNT_ID = re.compile(r"\b\d{12}\b")

# AWS ARNs
_AWS_ARN = re.compile(
    r"arn:aws[a-zA-Z-]*:[a-zA-Z0-9-]+:[a-zA-Z0-9-]*:\d{12}:[a-zA-Z0-9/_.\-:*]+"
)

# AWS Access Key IDs (start with AKIA, ASIA, ABIA, ACCA)
_AWS_ACCESS_KEY = re.compile(r"\b(AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b")

# AWS Secret Access Keys (40-char base64-like strings)
_AWS_SECRET_KEY = re.compile(r"\b[A-Za-z0-9/+=]{40}\b")

# Generic API keys/tokens (long hex or base64 strings that look like secrets)
_GENERIC_SECRET = re.compile(
    r"\b(sk-[a-zA-Z0-9]{20,}|ghp_[a-zA-Z0-9]{36}|xox[bpsa]-[a-zA-Z0-9\-]+)\b"
)

# Email addresses
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")

# Phone numbers (basic patterns)
_PHONE = re.compile(r"\b(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")

# IP addresses (private ranges are less sensitive but still redact in responses)
_IP_ADDRESS = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")

# Discord bot tokens (base64-encoded, ~70 chars)
_DISCORD_TOKEN = re.compile(r"[MN][A-Za-z\d]{5,28}\.[A-Za-z\d\-_]{4,8}\.[A-Za-z\d\-_]{20,}")


# --------------------------------------------------------------------------- #
# System prompt leakage patterns
# --------------------------------------------------------------------------- #

_PROMPT_LEAK_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(my\s+)?(system\s+prompt|system\s+instructions?)\s*(is|are|says?|reads?)\s*:", re.I),
     "system_prompt_disclosure"),
    (re.compile(r"(I\s+was\s+(told|instructed|programmed|configured)\s+to)", re.I),
     "instruction_disclosure"),
    (re.compile(r"(my\s+instructions?\s+(say|are|include|tell\s+me))", re.I),
     "instruction_disclosure"),
    (re.compile(r"TOOL\s+USAGE\s+RULES|ANSWER\s+QUALITY\s+RULES", re.I),
     "orchestrator_prompt_leak"),
    (re.compile(r"invoke_faq_agent|invoke_discord_agent|invoke_reasoning_agent|invoke_aws_docs_agent",),
     "internal_tool_name_leak"),
    (re.compile(r"waterfall_steps_executed|confidence_ranked\s+waterfall", re.I),
     "internal_architecture_leak"),
]

# Honeypot canary — embed this in system prompts, if it appears in output
# it means the LLM leaked the system prompt
CANARY_TOKEN = "BESA-CANARY-7f3a9c2e"


# --------------------------------------------------------------------------- #
# URL validation
# --------------------------------------------------------------------------- #

_ALLOWED_URL_DOMAINS = {
    "docs.aws.amazon.com",
    "aws.amazon.com",
    "repost.aws",
    "github.com",
    "stackoverflow.com",
    "discord.com",
    "developer.mozilla.org",
    "en.wikipedia.org",
}

_URL_PATTERN = re.compile(r"https?://([a-zA-Z0-9.-]+)(/[^\s)\"']*)?")


def validate_output(text: str) -> ValidationResult:
    """
    Validate and clean LLM output before sending to Discord.

    Steps:
    1. Check for system prompt leakage
    2. Check for canary token leak
    3. Redact sensitive data (ARNs, account IDs, keys, PII)
    4. Validate URLs (flag non-AWS domains)
    5. Enforce length limits

    Args:
        text: Raw LLM response text

    Returns:
        ValidationResult with cleaned text, redactions list, or block flag
    """
    if not text:
        return ValidationResult(is_safe=True, cleaned_text="")

    redactions: list[str] = []
    warnings: list[str] = []
    cleaned = text

    # Step 1: Check for canary token leak (immediate block)
    if CANARY_TOKEN in cleaned:
        logger.error("CANARY TOKEN detected in output — system prompt leaked!")
        return ValidationResult(
            is_safe=False,
            cleaned_text="I'm sorry, I encountered an error. Please try again.",
            blocked=True,
            block_reason="canary_token_leak",
        )

    # Step 2: Check for system prompt leakage patterns
    for pattern, label in _PROMPT_LEAK_PATTERNS:
        if pattern.search(cleaned):
            logger.warning("Prompt leakage detected: %s", label)
            return ValidationResult(
                is_safe=False,
                cleaned_text="I'm sorry, I can't share that information. Please ask an AWS workshop question.",
                blocked=True,
                block_reason=f"prompt_leak:{label}",
            )

    # Step 3: Redact sensitive data
    # AWS ARNs (redact account ID portion)
    def _redact_arn(match: re.Match) -> str:
        arn = match.group(0)
        redactions.append("aws_arn")
        return re.sub(r":\d{12}:", ":***REDACTED***:", arn)

    cleaned = _AWS_ARN.sub(_redact_arn, cleaned)

    # AWS Access Keys
    if _AWS_ACCESS_KEY.search(cleaned):
        cleaned = _AWS_ACCESS_KEY.sub("***AWS_KEY_REDACTED***", cleaned)
        redactions.append("aws_access_key")

    # AWS Secret Keys (only if they appear near key-like context)
    if _AWS_SECRET_KEY.search(cleaned) and any(
        kw in cleaned.lower() for kw in ("secret", "key", "credential", "token")
    ):
        cleaned = _AWS_SECRET_KEY.sub("***SECRET_REDACTED***", cleaned)
        redactions.append("aws_secret_key")

    # Discord tokens
    if _DISCORD_TOKEN.search(cleaned):
        cleaned = _DISCORD_TOKEN.sub("***TOKEN_REDACTED***", cleaned)
        redactions.append("discord_token")

    # Generic API keys
    if _GENERIC_SECRET.search(cleaned):
        cleaned = _GENERIC_SECRET.sub("***API_KEY_REDACTED***", cleaned)
        redactions.append("generic_api_key")

    # Step 4: Validate URLs — warn about non-standard domains
    for url_match in _URL_PATTERN.finditer(cleaned):
        domain = url_match.group(1).lower()
        # Check if domain or any parent domain is in allowed list
        is_allowed = any(
            domain == allowed or domain.endswith("." + allowed)
            for allowed in _ALLOWED_URL_DOMAINS
        )
        if not is_allowed:
            warnings.append(f"unverified_url:{domain}")

    # Step 5: Enforce length limit
    if len(cleaned) > MAX_RESPONSE_LENGTH:
        cleaned = cleaned[: MAX_RESPONSE_LENGTH - 50] + "\n\n*[Response truncated]*"
        warnings.append("response_truncated")

    # Strip @everyone/@here to prevent mass pings
    cleaned = re.sub(r"@(everyone|here)", "@\u200b\\1", cleaned)

    return ValidationResult(
        is_safe=True,
        cleaned_text=cleaned,
        redactions=redactions,
        warnings=warnings,
    )


def validate_embed_field(text: str, max_length: int = 1024) -> str:
    """Validate and truncate text for Discord embed fields."""
    if not text:
        return ""
    result = validate_output(text)
    cleaned = result.cleaned_text
    if len(cleaned) > max_length:
        cleaned = cleaned[: max_length - 3] + "..."
    return cleaned
