"""Discord REST API client for posting responses and fetching channel data."""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Optional

import httpx

from backend.models.discord_models import DiscordChannel, DiscordMessage

logger = logging.getLogger(__name__)

DISCORD_API_BASE = "https://discord.com/api/v10"


class DiscordService:
    """
    Thin wrapper around Discord REST API.
    Used by Lambda handlers to post responses and fetch channel data.
    All outbound calls use the bot token stored in Secrets Manager.
    """

    def __init__(self, bot_token: str, application_id: str, public_key: str):
        self._bot_token = bot_token
        self._application_id = application_id
        self._public_key = public_key
        self._headers = {
            "Authorization": f"Bot {bot_token}",
            "Content-Type": "application/json",
            "User-Agent": "BeSaAIAssistant/1.0",
        }

    # -------------------------------------------------------------------------
    # Signature verification
    # -------------------------------------------------------------------------

    def verify_discord_signature(
        self,
        raw_body: bytes,
        signature: str,
        timestamp: str,
    ) -> bool:
        """
        Verify Discord webhook interaction signature using Ed25519.
        Must be called before processing any Discord interaction.
        """
        try:
            from nacl.signing import VerifyKey
            from nacl.exceptions import BadSignatureError

            verify_key = VerifyKey(bytes.fromhex(self._public_key))
            message = (timestamp + raw_body.decode("utf-8")).encode()
            verify_key.verify(message, bytes.fromhex(signature))
            return True
        except Exception as e:
            logger.warning("Discord signature verification failed: %s", e)
            return False

    # -------------------------------------------------------------------------
    # Interaction responses (slash commands)
    # -------------------------------------------------------------------------

    def acknowledge_interaction(
        self,
        interaction_id: str,
        interaction_token: str,
        ephemeral: bool = False,
    ) -> bool:
        """
        Send a deferred response to a Discord interaction within 3 seconds.
        Discord shows "Bot is thinking..." until we edit the response.
        """
        flags = 64 if ephemeral else 0
        payload = {
            "type": 5,  # DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE
            "data": {"flags": flags},
        }
        url = f"{DISCORD_API_BASE}/interactions/{interaction_id}/{interaction_token}/callback"
        try:
            with httpx.Client(timeout=2.5) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
                return True
        except Exception as e:
            logger.error("Failed to acknowledge interaction %s: %s", interaction_id, e)
            return False

    def edit_interaction_response(
        self,
        interaction_token: str,
        content: str,
        embeds: Optional[list[dict]] = None,
    ) -> bool:
        """
        Edit a deferred interaction response with the actual answer.
        Interaction tokens are valid for 15 minutes.
        """
        payload: dict = {"content": content}
        if embeds:
            payload["embeds"] = embeds

        url = (
            f"{DISCORD_API_BASE}/webhooks/{self._application_id}"
            f"/{interaction_token}/messages/@original"
        )
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.patch(url, json=payload)
                resp.raise_for_status()
                return True
        except Exception as e:
            logger.error("Failed to edit interaction response: %s", e)
            return False

    # -------------------------------------------------------------------------
    # Channel message replies (channel monitoring)
    # -------------------------------------------------------------------------

    def post_thread_reply(
        self,
        channel_id: str,
        content: str,
        reply_to_message_id: Optional[str] = None,
        embeds: Optional[list[dict]] = None,
    ) -> Optional[str]:
        """
        Post a message to a channel, optionally as a thread reply.
        Returns the new message ID on success, None on failure.
        """
        payload: dict = {"content": content}
        if reply_to_message_id:
            payload["message_reference"] = {
                "message_id": reply_to_message_id,
                "fail_if_not_exists": False,
            }
        if embeds:
            payload["embeds"] = embeds

        url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages"
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, json=payload, headers=self._headers)
                resp.raise_for_status()
                return resp.json().get("id")
        except Exception as e:
            logger.error("Failed to post message to channel %s: %s", channel_id, e)
            return None

    # -------------------------------------------------------------------------
    # Channel history (for polling-based monitoring)
    # -------------------------------------------------------------------------

    def get_channel_messages(
        self,
        channel_id: str,
        after_message_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[DiscordMessage]:
        """
        Fetch messages from a Discord channel, optionally after a specific message ID.
        Strips bot messages and empty content automatically.
        """
        params: dict = {"limit": limit}
        if after_message_id:
            params["after"] = after_message_id

        url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages"
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(url, params=params, headers=self._headers)
                resp.raise_for_status()
                raw_messages = resp.json()

            guild_id = self._get_channel_guild_id(channel_id)
            messages = []
            for msg in raw_messages:
                # Skip bot messages and empty content
                if msg.get("author", {}).get("bot"):
                    continue
                if not msg.get("content", "").strip():
                    continue
                messages.append(DiscordMessage.from_discord_api(msg, guild_id=guild_id))
            return sorted(messages, key=lambda m: m.timestamp)
        except Exception as e:
            logger.error("Failed to fetch messages from channel %s: %s", channel_id, e)
            return []

    def get_thread_messages(
        self, thread_id: str, guild_id: str = ""
    ) -> list[DiscordMessage]:
        """Fetch all messages from a Discord thread."""
        url = f"{DISCORD_API_BASE}/channels/{thread_id}/messages"
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    url, params={"limit": 50}, headers=self._headers
                )
                resp.raise_for_status()
                return [
                    DiscordMessage.from_discord_api(msg, guild_id=guild_id)
                    for msg in resp.json()
                    if not msg.get("author", {}).get("bot")
                ]
        except Exception as e:
            logger.error("Failed to fetch thread %s: %s", thread_id, e)
            return []

    # -------------------------------------------------------------------------
    # Guild/channel metadata
    # -------------------------------------------------------------------------

    def get_guild_channels(self, guild_id: str) -> list[DiscordChannel]:
        """Fetch all text channels in a guild."""
        url = f"{DISCORD_API_BASE}/guilds/{guild_id}/channels"
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(url, headers=self._headers)
                resp.raise_for_status()
                channels = []
                for ch in resp.json():
                    if ch.get("type") in (0, 5):  # GUILD_TEXT or GUILD_NEWS
                        channels.append(
                            DiscordChannel(
                                channel_id=ch["id"],
                                name=ch["name"],
                                channel_type=ch["type"],
                                topic=ch.get("topic"),
                            )
                        )
                return sorted(channels, key=lambda c: c.name)
        except Exception as e:
            logger.error("Failed to fetch guild channels for %s: %s", guild_id, e)
            return []

    def _get_channel_guild_id(self, channel_id: str) -> str:
        """Fetch guild ID for a channel (cached in caller usually)."""
        url = f"{DISCORD_API_BASE}/channels/{channel_id}"
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(url, headers=self._headers)
                resp.raise_for_status()
                return resp.json().get("guild_id", "")
        except Exception:
            return ""

    # -------------------------------------------------------------------------
    # Response formatting helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def format_answer_embed(
        answer: str,
        source: str,
        confidence: float,
        source_urls: list[str] = [],
        requires_verification: bool = False,
    ) -> dict:
        """
        Build a Discord embed for a bot answer.
        Embeds support richer formatting than plain text.
        """
        source_emoji = {
            "FAQ": "📚",
            "Discord History": "💬",
            "AI Reasoning": "🤖",
            "AWS Documentation": "📖",
            "Multiple Sources": "🔀",
        }.get(source, "ℹ️")

        color = {
            "FAQ": 0x00B300,           # Green — high confidence
            "Discord History": 0x5865F2,  # Blurple — Discord color
            "AI Reasoning": 0xFF6B2B,    # Orange — use with caution
            "AWS Documentation": 0xFF9900,  # AWS orange
        }.get(source, 0x808080)

        confidence_pct = int(confidence * 100)
        fields = [
            {
                "name": "Source",
                "value": f"{source_emoji} {source}",
                "inline": True,
            },
            {
                "name": "Confidence",
                "value": f"{confidence_pct}%",
                "inline": True,
            },
        ]
        if source_urls:
            links = "\n".join(f"• [View]({url})" for url in source_urls[:3])
            fields.append({"name": "References", "value": links, "inline": False})
        if requires_verification:
            fields.append(
                {
                    "name": "⚠️ Note",
                    "value": "This answer was synthesized by AI. Please verify before applying to production.",
                    "inline": False,
                }
            )

        # Discord embed content limit is 4096 chars
        if len(answer) > 4000:
            answer = answer[:3997] + "..."

        return {
            "title": "BeSa AI Answer",
            "description": answer,
            "color": color,
            "fields": fields,
            "footer": {"text": "AWS Workshop AI Assistant"},
        }

    @staticmethod
    def truncate_for_discord(text: str, max_len: int = 2000) -> str:
        """Ensure text fits within Discord's 2000-char message limit."""
        if len(text) <= max_len:
            return text
        return text[: max_len - 3] + "..."
