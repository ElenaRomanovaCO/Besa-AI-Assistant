"""
Lambda handler for processing Dead Letter Queue (DLQ) messages.

Triggered by SQS DLQ messages that failed processing after 3 retries.
Posts a user-friendly error message to Discord so users don't see
infinite "thinking..." state.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3

from backend.models.agent_models import ProcessingMessage
from backend.services.discord_service import DiscordService

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Environment variables
_BOT_TOKEN_SECRET_ARN = os.environ.get("DISCORD_BOT_TOKEN_SECRET_ARN", "")
_PUBLIC_KEY_SECRET_ARN = os.environ.get("DISCORD_PUBLIC_KEY_SECRET_ARN", "")
_APPLICATION_ID = os.environ.get("DISCORD_APPLICATION_ID", "")

_secrets_client = boto3.client("secretsmanager")
_discord_service: DiscordService | None = None

_ERROR_MESSAGE = (
    "I'm sorry, I wasn't able to process your question after several attempts. "
    "This might be due to high demand or a temporary issue. "
    "Please try again in a few minutes, or ask a workshop volunteer for help."
)


def _get_discord_service() -> DiscordService:
    """Lazy-init Discord service."""
    global _discord_service
    if _discord_service is None:
        bot_token = _secrets_client.get_secret_value(
            SecretId=_BOT_TOKEN_SECRET_ARN
        )["SecretString"]
        public_key = _secrets_client.get_secret_value(
            SecretId=_PUBLIC_KEY_SECRET_ARN
        )["SecretString"]
        _discord_service = DiscordService(
            bot_token=bot_token,
            application_id=_APPLICATION_ID,
            public_key=public_key,
        )
    return _discord_service


def handler(event: dict, context: Any) -> dict:
    """
    Process DLQ messages — notify users that their question failed.

    For each failed message:
    - Slash commands: edit the deferred interaction response with error message
    - Channel messages: post a threaded reply with error message
    """
    discord = _get_discord_service()
    processed = 0

    for record in event.get("Records", []):
        try:
            body = json.loads(record["body"])
            msg = ProcessingMessage.from_dict(body)

            logger.warning(
                "DLQ processing failed message: correlation_id=%s user=%s question=%s",
                msg.correlation_id,
                msg.user_name,
                msg.question[:100],
            )

            if msg.source == "slash_command" and msg.interaction_token:
                discord.edit_interaction_response(
                    interaction_token=msg.interaction_token,
                    content=_ERROR_MESSAGE,
                )
            elif msg.original_message_id:
                discord.post_thread_reply(
                    channel_id=msg.channel_id,
                    content=_ERROR_MESSAGE,
                    reply_to_message_id=msg.original_message_id,
                )

            processed += 1

        except Exception as e:
            # DLQ handler should never fail — log and continue
            logger.error(
                "DLQ handler error for record %s: %s",
                record.get("messageId", "unknown"),
                e,
            )

    logger.info("DLQ handler processed %d messages", processed)
    return {"statusCode": 200, "processed": processed}
