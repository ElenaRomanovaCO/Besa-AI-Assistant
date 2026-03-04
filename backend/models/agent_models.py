"""Core data models shared across all agents and the orchestrator."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class SourceType(str, Enum):
    FAQ = "FAQ"
    DISCORD_HISTORY = "Discord History"
    AI_REASONING = "AI Reasoning"
    AWS_DOCS = "AWS Documentation"
    MERGED = "Multiple Sources"
    UNKNOWN = "Unknown"


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class QuestionContext:
    """Metadata about a student's question from Discord."""

    question: str
    user_id: str
    user_name: str
    guild_id: str
    channel_id: str
    # For slash command interactions — used to edit the deferred response
    interaction_token: Optional[str] = None
    application_id: Optional[str] = None
    # For channel message replies — used to create a thread reply
    original_message_id: Optional[str] = None
    thread_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    is_private: bool = False  # /ask-private — ephemeral response
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class SourceResult:
    """Result from a single knowledge source."""

    source_type: SourceType
    answer: str
    confidence_score: float  # 0.0 to 1.0
    metadata: dict = field(default_factory=dict)
    # Source-specific links and references
    source_urls: list[str] = field(default_factory=list)
    # Whether this source should be skipped (error, disabled)
    skipped: bool = False
    skip_reason: Optional[str] = None


@dataclass
class RankedAnswer:
    """A ranked, attributed answer ready for Discord delivery."""

    rank: int
    source_type: SourceType
    answer: str
    confidence_score: float
    source_urls: list[str] = field(default_factory=list)
    requires_verification: bool = False
    reasoning_steps: list[str] = field(default_factory=list)


@dataclass
class BotResponse:
    """Final response sent to Discord."""

    answers: list[RankedAnswer]
    primary_source: SourceType
    total_processing_time_ms: int
    correlation_id: str
    waterfall_steps_executed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def primary_answer(self) -> Optional[RankedAnswer]:
        return self.answers[0] if self.answers else None

    @property
    def has_high_confidence_answer(self) -> bool:
        return bool(self.answers and self.answers[0].confidence_score >= 0.75)


@dataclass
class WaterfallConfig:
    """Configuration for the orchestrator waterfall logic."""

    faq_threshold: float = 0.75
    discord_overlap_threshold: float = 0.70
    query_expansion_depth: int = 10
    max_discord_results: int = 5
    max_faq_results: int = 3
    enable_reasoning_agent: bool = True
    enable_discord_agent: bool = True
    enable_aws_docs_agent: bool = True
    enable_online_search_agent: bool = False
    searchable_channel_ids: list[str] = field(default_factory=list)
    rate_limit_per_hour: int = 20


@dataclass
class ProcessingMessage:
    """SQS message payload for async agent processing."""

    question: str
    user_id: str
    user_name: str
    guild_id: str
    channel_id: str
    source: str  # "slash_command" | "channel_message"
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    # Slash command fields
    interaction_token: Optional[str] = None
    application_id: Optional[str] = None
    is_private: bool = False
    # Channel message fields
    original_message_id: Optional[str] = None
    thread_id: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "user_id": self.user_id,
            "user_name": self.user_name,
            "guild_id": self.guild_id,
            "channel_id": self.channel_id,
            "source": self.source,
            "correlation_id": self.correlation_id,
            "interaction_token": self.interaction_token,
            "application_id": self.application_id,
            "is_private": self.is_private,
            "original_message_id": self.original_message_id,
            "thread_id": self.thread_id,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProcessingMessage":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
