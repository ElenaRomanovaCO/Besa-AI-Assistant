"""Configuration and system settings data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ThresholdConfig:
    """Confidence threshold settings for each knowledge source."""

    faq_similarity_threshold: float = 0.75  # Min cosine similarity for FAQ match
    discord_overlap_threshold: float = 0.70  # Min keyword overlap % for Discord match
    query_expansion_depth: int = 10  # Keywords to generate (7–15)
    max_faq_results: int = 3
    max_discord_results: int = 5

    def validate(self) -> list[str]:
        errors = []
        if not 0.25 <= self.faq_similarity_threshold <= 1.0:
            errors.append("faq_similarity_threshold must be between 0.25 and 1.0")
        if not 0.25 <= self.discord_overlap_threshold <= 1.0:
            errors.append("discord_overlap_threshold must be between 0.25 and 1.0")
        if not 7 <= self.query_expansion_depth <= 15:
            errors.append("query_expansion_depth must be between 7 and 15")
        return errors


@dataclass
class AgentConfig:
    """Toggle settings for individual agents."""

    enable_faq_agent: bool = True
    enable_discord_agent: bool = True
    enable_reasoning_agent: bool = True
    enable_aws_docs_agent: bool = False  # Requires awslabs MCP package in layer; disabled until added
    enable_online_search_agent: bool = False

    def active_agents(self) -> list[str]:
        active = []
        if self.enable_faq_agent:
            active.append("faq")
        if self.enable_discord_agent:
            active.append("discord")
        if self.enable_reasoning_agent:
            active.append("reasoning")
        if self.enable_aws_docs_agent:
            active.append("aws_docs")
        if self.enable_online_search_agent:
            active.append("online_search")
        return active


@dataclass
class RateLimitConfig:
    """Rate limiting settings."""

    max_queries_per_hour: int = 20
    cooldown_message_template: str = (
        "You've reached the question limit ({max} per hour). "
        "Please wait {remaining_minutes} minutes before asking again."
    )

    def format_cooldown_message(self, max_queries: int, remaining_seconds: int) -> str:
        remaining_minutes = max(1, remaining_seconds // 60)
        return self.cooldown_message_template.format(
            max=max_queries,
            remaining_minutes=remaining_minutes,
        )


@dataclass
class SystemConfig:
    """Full system configuration stored in DynamoDB."""

    config_id: str = "system"  # DynamoDB partition key (singleton)
    thresholds: ThresholdConfig = field(default_factory=ThresholdConfig)
    agents: AgentConfig = field(default_factory=AgentConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    searchable_channel_ids: list[str] = field(default_factory=list)
    log_retention_days: int = 90
    cost_alert_threshold_usd: float = 100.0
    updated_at: datetime = field(default_factory=datetime.utcnow)
    updated_by: Optional[str] = None

    def to_dynamodb_item(self) -> dict:
        """Serialize for DynamoDB storage."""
        return {
            "config_id": self.config_id,
            "sk": "config",
            "faq_threshold": str(self.thresholds.faq_similarity_threshold),
            "discord_threshold": str(self.thresholds.discord_overlap_threshold),
            "query_expansion_depth": self.thresholds.query_expansion_depth,
            "max_faq_results": self.thresholds.max_faq_results,
            "max_discord_results": self.thresholds.max_discord_results,
            "enable_faq_agent": self.agents.enable_faq_agent,
            "enable_discord_agent": self.agents.enable_discord_agent,
            "enable_reasoning_agent": self.agents.enable_reasoning_agent,
            "enable_aws_docs_agent": self.agents.enable_aws_docs_agent,
            "enable_online_search_agent": self.agents.enable_online_search_agent,
            "max_queries_per_hour": self.rate_limit.max_queries_per_hour,
            "searchable_channel_ids": self.searchable_channel_ids,
            "log_retention_days": self.log_retention_days,
            "cost_alert_threshold_usd": str(self.cost_alert_threshold_usd),
            "updated_at": self.updated_at.isoformat(),
            "updated_by": self.updated_by or "",
        }

    @classmethod
    def from_dynamodb_item(cls, item: dict) -> "SystemConfig":
        """Deserialize from DynamoDB item."""
        thresholds = ThresholdConfig(
            faq_similarity_threshold=float(item.get("faq_threshold", 0.75)),
            discord_overlap_threshold=float(item.get("discord_threshold", 0.70)),
            query_expansion_depth=int(item.get("query_expansion_depth", 10)),
            max_faq_results=int(item.get("max_faq_results", 3)),
            max_discord_results=int(item.get("max_discord_results", 5)),
        )
        agents = AgentConfig(
            enable_faq_agent=bool(item.get("enable_faq_agent", True)),
            enable_discord_agent=bool(item.get("enable_discord_agent", True)),
            enable_reasoning_agent=bool(item.get("enable_reasoning_agent", True)),
            enable_aws_docs_agent=bool(item.get("enable_aws_docs_agent", True)),
            enable_online_search_agent=bool(item.get("enable_online_search_agent", False)),
        )
        rate_limit = RateLimitConfig(
            max_queries_per_hour=int(item.get("max_queries_per_hour", 20)),
        )
        updated_at_raw = item.get("updated_at", "")
        try:
            updated_at = datetime.fromisoformat(updated_at_raw)
        except (ValueError, TypeError):
            updated_at = datetime.utcnow()

        return cls(
            config_id=item.get("config_id", "system"),
            thresholds=thresholds,
            agents=agents,
            rate_limit=rate_limit,
            searchable_channel_ids=list(item.get("searchable_channel_ids", [])),
            log_retention_days=int(item.get("log_retention_days", 90)),
            cost_alert_threshold_usd=float(item.get("cost_alert_threshold_usd", 100.0)),
            updated_at=updated_at,
            updated_by=item.get("updated_by") or None,
        )

    @classmethod
    def default(cls) -> "SystemConfig":
        return cls()
