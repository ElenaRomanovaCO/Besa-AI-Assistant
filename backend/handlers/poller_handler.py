"""
Lambda handler for polling Discord channel messages.

Triggered by EventBridge Scheduler every 60 seconds.
Fetches new messages from #ask-besa-ai-assistant and queues them for processing.

This enables channel message monitoring without a long-running bot process.
Trade-off: up to 60-second latency before processing begins.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

import boto3

from backend.models.agent_models import ProcessingMessage
from backend.services.config_service import ConfigService
from backend.services.discord_service import DiscordService

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Environment variables
_BOT_TOKEN_SECRET_ARN = os.environ.get("DISCORD_BOT_TOKEN_SECRET_ARN", "")
_PUBLIC_KEY_SECRET_ARN = os.environ.get("DISCORD_PUBLIC_KEY_SECRET_ARN", "")
_APPLICATION_ID = os.environ.get("DISCORD_APPLICATION_ID", "")
_BOT_CHANNEL_ID = os.environ.get("DISCORD_BOT_CHANNEL_ID", "")
_GUILD_ID = os.environ.get("DISCORD_GUILD_ID", "")
_SQS_QUEUE_URL = os.environ.get("PROCESSING_QUEUE_URL", "")
_CONFIG_TABLE = os.environ.get("CONFIG_TABLE_NAME", "")
_STATE_TABLE = os.environ.get("STATE_TABLE_NAME", "")
_AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

_secrets_client = boto3.client("secretsmanager")
_sqs_client = boto3.client("sqs")
_dynamodb = boto3.resource("dynamodb", region_name=_AWS_REGION)

_discord_service: DiscordService | None = None
_config_service: ConfigService | None = None


def _get_discord_service() -> DiscordService:
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


def _get_config_service() -> ConfigService:
    global _config_service
    if _config_service is None:
        _config_service = ConfigService(_CONFIG_TABLE, region=_AWS_REGION)
    return _config_service


def _get_last_message_id() -> str | None:
    """Read the last processed message ID from DynamoDB poll state."""
    try:
        table = _dynamodb.Table(_STATE_TABLE)
        response = table.get_item(
            Key={"pk": f"poll_state#{_BOT_CHANNEL_ID}", "sk": "last_message"}
        )
        return response.get("Item", {}).get("message_id")
    except Exception as e:
        logger.warning("Failed to read poll state: %s", e)
        return None


def _save_last_message_id(message_id: str) -> None:
    """Persist the last processed message ID to DynamoDB."""
    try:
        table = _dynamodb.Table(_STATE_TABLE)
        table.put_item(
            Item={
                "pk": f"poll_state#{_BOT_CHANNEL_ID}",
                "sk": "last_message",
                "message_id": message_id,
            }
        )
    except Exception as e:
        logger.warning("Failed to save poll state: %s", e)


def handler(event: dict, context: Any) -> dict:
    """
    Poll the bot channel for new messages and queue them for processing.
    Called every 60 seconds by EventBridge Scheduler.
    """
    if not _BOT_CHANNEL_ID:
        logger.error("BOT_CHANNEL_ID not configured — skipping poll")
        return {"statusCode": 200, "queued": 0}

    discord = _get_discord_service()
    last_message_id = _get_last_message_id()

    # Fetch new messages since last poll
    messages = discord.get_channel_messages(
        channel_id=_BOT_CHANNEL_ID,
        after_message_id=last_message_id,
        limit=50,
    )

    if not messages:
        logger.debug("No new messages in channel %s", _BOT_CHANNEL_ID)
        return {"statusCode": 200, "queued": 0}

    logger.info("Found %d new messages to process", len(messages))

    queued_count = 0
    new_last_id = last_message_id

    for msg in messages:
        # Skip short messages (likely not questions)
        if len(msg.content.strip()) < 10:
            continue

        correlation_id = str(uuid.uuid4())
        processing_msg = ProcessingMessage(
            question=msg.content,
            user_id=msg.author_id,
            user_name=msg.author_name,
            guild_id=_GUILD_ID,
            channel_id=_BOT_CHANNEL_ID,
            source="channel_message",
            correlation_id=correlation_id,
            original_message_id=msg.message_id,
        )

        try:
            _sqs_client.send_message(
                QueueUrl=_SQS_QUEUE_URL,
                MessageBody=json.dumps(processing_msg.to_dict()),
                MessageGroupId=msg.author_id,
                MessageDeduplicationId=correlation_id,
            )
            queued_count += 1
            new_last_id = msg.message_id
            logger.info(
                "Queued message from %s: correlation_id=%s",
                msg.author_name,
                correlation_id,
            )
        except Exception as e:
            logger.error("Failed to queue message %s: %s", msg.message_id, e)

    # Update poll state to the latest message ID
    if new_last_id and new_last_id != last_message_id:
        _save_last_message_id(new_last_id)

    return {"statusCode": 200, "queued": queued_count}
