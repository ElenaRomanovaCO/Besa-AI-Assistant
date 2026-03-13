"""Input sanitization: prompt injection defense and input validation.

Applied at the earliest entry point (webhook/poller handlers) BEFORE
messages are published to SQS. Rejects or cleans malicious inputs.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

# Maximum allowed question length (Discord slash commands default to 100,
# but channel messages can be longer)
MAX_QUESTION_LENGTH = 500

# Minimum question length to process (skip noise)
MIN_QUESTION_LENGTH = 3


class RejectionReason(str, Enum):
    TOO_LONG = "too_long"
    TOO_SHORT = "too_short"
    PROMPT_INJECTION = "prompt_injection"
    CONTROL_CHARACTERS = "control_characters"
    EMPTY_AFTER_SANITIZE = "empty_after_sanitize"


@dataclass
class SanitizationResult:
    """Result of input sanitization."""
    is_safe: bool
    cleaned_text: str
    rejection_reason: Optional[RejectionReason] = None
    matched_pattern: Optional[str] = None

    @property
    def should_block(self) -> bool:
        return not self.is_safe


# --------------------------------------------------------------------------- #
# Prompt injection detection patterns
# --------------------------------------------------------------------------- #

# Patterns that indicate prompt injection attempts.
# Each tuple: (compiled regex, human-readable label)
_INJECTION_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Direct instruction override
    (re.compile(r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions|prompts|rules|context)", re.I),
     "ignore_previous_instructions"),
    (re.compile(r"disregard\s+(all\s+)?(previous|prior|above|earlier|your)\s+(instructions|prompts|rules|guidelines)", re.I),
     "disregard_instructions"),
    (re.compile(r"forget\s+(all\s+)?(previous|prior|your)\s+(instructions|rules|context|training)", re.I),
     "forget_instructions"),
    (re.compile(r"override\s+(your|all|the|my)(\s+\w+)?\s+(instructions|rules|guidelines|prompt)", re.I),
     "override_instructions"),

    # Role-play / identity hijacking
    (re.compile(r"(you\s+are\s+now|act\s+as\s+if\s+you\s+are|pretend\s+(to\s+be|you\s+are)|roleplay\s+as|from\s+now\s+on\s+you\s+are)", re.I),
     "role_play_injection"),
    (re.compile(r"(switch\s+to|enter|activate)\s+(developer|admin|sudo|root|god|unrestricted|jailbreak)\s+(mode|access)", re.I),
     "mode_switch_injection"),
    (re.compile(r"(DAN|do\s+anything\s+now|STAN|DUDE|AIM)\s*(mode|prompt)?", re.I),
     "known_jailbreak_name"),

    # System prompt extraction
    (re.compile(r"(what\s+(is|are)\s+your\s+(system\s+)?prompt|show\s+me\s+your\s+(system\s+)?prompt|reveal\s+your\s+(instructions|prompt|rules))", re.I),
     "system_prompt_extraction"),
    (re.compile(r"(print|output|display|repeat|echo)\s+(your\s+)?(system\s+)?(prompt|instructions|rules|guidelines)", re.I),
     "system_prompt_extraction"),
    (re.compile(r"(what\s+were\s+you\s+told|what\s+instructions\s+were\s+you\s+given)", re.I),
     "system_prompt_extraction"),

    # Delimiter injection (trying to close/open system prompt blocks)
    (re.compile(r"<\s*/?\s*(system|prompt|instruction|context|message)\s*>", re.I),
     "xml_delimiter_injection"),
    (re.compile(r"```\s*(system|prompt|instruction)", re.I),
     "code_block_delimiter_injection"),
    (re.compile(r"---\s*(system|end\s+of\s+system|new\s+instruction)", re.I),
     "separator_delimiter_injection"),
    (re.compile(r"\[INST\]|\[/INST\]|\[SYSTEM\]|\[/SYSTEM\]", re.I),
     "llama_format_injection"),

    # Output manipulation
    (re.compile(r"(respond|answer|reply)\s+(only\s+)?(with|in)\s+(json|xml|python|code|base64)", re.I),
     "output_format_manipulation"),
    (re.compile(r"(translate|convert)\s+(everything|this|all)\s+(to|into)\s+", re.I),
     "output_redirect"),

    # Instruction injection via context
    (re.compile(r"(new\s+instructions?|updated\s+instructions?|revised\s+prompt)\s*:", re.I),
     "injected_instructions"),
    (re.compile(r"(the\s+real\s+question\s+is|actually\s+I\s+need\s+you\s+to|instead\s+(of\s+that\s+)?do)", re.I),
     "instruction_redirect"),

    # Encoding/obfuscation attempts
    (re.compile(r"base64\s*(decode|encode)\s*:?\s*[A-Za-z0-9+/=]{20,}", re.I),
     "base64_obfuscation"),
]


# --------------------------------------------------------------------------- #
# Zero-width and invisible characters
# --------------------------------------------------------------------------- #

_INVISIBLE_CHARS = re.compile(
    r"[\u200b\u200c\u200d\u200e\u200f"    # Zero-width spaces/joiners
    r"\u202a-\u202e"                        # Bidi overrides
    r"\u2060-\u2064"                        # Word joiners, invisible separators
    r"\ufeff"                               # BOM / zero-width no-break space
    r"\u00ad"                               # Soft hyphen
    r"\u034f"                               # Combining grapheme joiner
    r"\u180e"                               # Mongolian vowel separator
    r"]"
)


def sanitize_input(text: str) -> SanitizationResult:
    """
    Sanitize user input for safety.

    Steps:
    1. Strip invisible/zero-width characters
    2. Remove control characters (keep newlines, tabs)
    3. Normalize Unicode (NFC — canonical decomposition + composition)
    4. Check length bounds
    5. Detect prompt injection patterns

    Args:
        text: Raw user input

    Returns:
        SanitizationResult with cleaned text or rejection details
    """
    if not text or not text.strip():
        return SanitizationResult(
            is_safe=False,
            cleaned_text="",
            rejection_reason=RejectionReason.EMPTY_AFTER_SANITIZE,
        )

    # Step 1: Remove invisible/zero-width characters
    cleaned = _INVISIBLE_CHARS.sub("", text)

    # Step 2: Remove control characters (keep \n, \r, \t)
    cleaned = "".join(
        ch for ch in cleaned
        if ch in ("\n", "\r", "\t") or not unicodedata.category(ch).startswith("C")
    )

    # Step 3: Normalize Unicode (prevent homoglyph attacks)
    cleaned = unicodedata.normalize("NFC", cleaned)

    # Collapse excessive whitespace (more than 3 consecutive newlines → 2)
    cleaned = re.sub(r"\n{4,}", "\n\n\n", cleaned)
    cleaned = cleaned.strip()

    if not cleaned:
        return SanitizationResult(
            is_safe=False,
            cleaned_text="",
            rejection_reason=RejectionReason.EMPTY_AFTER_SANITIZE,
        )

    # Step 4: Length bounds
    if len(cleaned) < MIN_QUESTION_LENGTH:
        return SanitizationResult(
            is_safe=False,
            cleaned_text=cleaned,
            rejection_reason=RejectionReason.TOO_SHORT,
        )

    if len(cleaned) > MAX_QUESTION_LENGTH:
        return SanitizationResult(
            is_safe=False,
            cleaned_text=cleaned[:MAX_QUESTION_LENGTH],
            rejection_reason=RejectionReason.TOO_LONG,
        )

    # Step 5: Prompt injection detection
    injection_match = detect_injection(cleaned)
    if injection_match:
        logger.warning(
            "Prompt injection detected: pattern=%s input_preview=%s",
            injection_match,
            cleaned[:80],
        )
        return SanitizationResult(
            is_safe=False,
            cleaned_text=cleaned,
            rejection_reason=RejectionReason.PROMPT_INJECTION,
            matched_pattern=injection_match,
        )

    return SanitizationResult(is_safe=True, cleaned_text=cleaned)


def detect_injection(text: str) -> Optional[str]:
    """
    Check text against known prompt injection patterns.

    Returns:
        Pattern label if injection detected, None if clean.
    """
    for pattern, label in _INJECTION_PATTERNS:
        if pattern.search(text):
            return label
    return None


def sanitize_for_embed(text: str) -> str:
    """
    Sanitize text for safe inclusion in Discord embeds.
    Strips any markdown/HTML that could break embed rendering.
    """
    # Remove @everyone and @here mentions (Discord-specific)
    text = re.sub(r"@(everyone|here)", "@\u200b\\1", text)
    # Remove Discord invite links
    text = re.sub(r"(https?://)?(www\.)?discord\.(gg|com/invite)/\S+", "[invite link removed]", text)
    # Truncate to Discord embed field limit
    if len(text) > 1024:
        text = text[:1021] + "..."
    return text
