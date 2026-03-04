"""Discord interaction and message data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Optional


class InteractionType(IntEnum):
    PING = 1
    APPLICATION_COMMAND = 2
    MESSAGE_COMPONENT = 3
    APPLICATION_COMMAND_AUTOCOMPLETE = 4
    MODAL_SUBMIT = 5


class InteractionResponseType(IntEnum):
    PONG = 1
    CHANNEL_MESSAGE_WITH_SOURCE = 4
    DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE = 5
    DEFERRED_UPDATE_MESSAGE = 6
    UPDATE_MESSAGE = 7


class MessageFlags(IntEnum):
    EPHEMERAL = 64  # Only visible to the invoking user


@dataclass
class SlashCommand:
    """Parsed slash command from Discord interaction."""

    name: str
    options: dict = field(default_factory=dict)

    @property
    def question(self) -> Optional[str]:
        """Extract question text from command options."""
        return self.options.get("question") or self.options.get("text")


@dataclass
class InteractionContext:
    """Parsed Discord interaction payload."""

    interaction_id: str
    interaction_token: str
    application_id: str
    interaction_type: InteractionType
    guild_id: str
    channel_id: str
    user_id: str
    user_name: str
    command: Optional[SlashCommand] = None

    @classmethod
    def from_payload(cls, payload: dict) -> "InteractionContext":
        """Parse from raw Discord interaction JSON payload."""
        user = payload.get("member", {}).get("user", payload.get("user", {}))
        command = None
        if payload.get("data"):
            opts = {}
            for opt in payload["data"].get("options", []):
                opts[opt["name"]] = opt.get("value")
            command = SlashCommand(name=payload["data"]["name"], options=opts)

        return cls(
            interaction_id=payload["id"],
            interaction_token=payload["token"],
            application_id=payload["application_id"],
            interaction_type=InteractionType(payload["type"]),
            guild_id=payload.get("guild_id", ""),
            channel_id=payload.get("channel_id", ""),
            user_id=user.get("id", ""),
            user_name=user.get("username", "unknown"),
            command=command,
        )


@dataclass
class DiscordMessage:
    """A message retrieved from Discord channel history."""

    message_id: str
    channel_id: str
    author_id: str
    author_name: str
    content: str
    timestamp: datetime
    thread_id: Optional[str] = None
    guild_id: Optional[str] = None

    @property
    def url(self) -> str:
        """Construct Discord message jump URL."""
        if self.guild_id and self.thread_id:
            return f"https://discord.com/channels/{self.guild_id}/{self.thread_id}/{self.message_id}"
        if self.guild_id:
            return f"https://discord.com/channels/{self.guild_id}/{self.channel_id}/{self.message_id}"
        return f"https://discord.com/channels/@me/{self.channel_id}/{self.message_id}"

    def to_searchable_text(self) -> str:
        """Return lowercased text for keyword matching."""
        return self.content.lower()

    @classmethod
    def from_discord_api(cls, data: dict, guild_id: str = "") -> "DiscordMessage":
        """Parse from Discord REST API message object."""
        return cls(
            message_id=data["id"],
            channel_id=data.get("channel_id", ""),
            author_id=data["author"]["id"],
            author_name=data["author"]["username"],
            content=data.get("content", ""),
            timestamp=datetime.fromisoformat(
                data["timestamp"].replace("Z", "+00:00")
            ),
            thread_id=data.get("thread", {}).get("id"),
            guild_id=guild_id,
        )


@dataclass
class RankedMessage:
    """A Discord message scored by keyword overlap."""

    message: DiscordMessage
    overlap_score: float  # 0.0 to 1.0
    matched_keywords: list[str] = field(default_factory=list)
    thread_context: list[DiscordMessage] = field(default_factory=list)


@dataclass
class DiscordResult:
    """Result from Discord history search."""

    messages: list[RankedMessage]
    confidence_score: float  # Highest overlap score (0.0 to 1.0)
    keywords_used: list[str] = field(default_factory=list)
    source: str = "Discord History"

    @property
    def has_results(self) -> bool:
        return bool(self.messages)

    @property
    def top_message(self) -> Optional[RankedMessage]:
        return self.messages[0] if self.messages else None


@dataclass
class DiscordChannel:
    """A Discord channel in the guild."""

    channel_id: str
    name: str
    channel_type: int  # 0 = GUILD_TEXT, 11 = PUBLIC_THREAD, etc.
    topic: Optional[str] = None
    is_selected: bool = False  # Whether configured as searchable

    @property
    def is_text_channel(self) -> bool:
        return self.channel_type in (0, 5)  # GUILD_TEXT or GUILD_NEWS
