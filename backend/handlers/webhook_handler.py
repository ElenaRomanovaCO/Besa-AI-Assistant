"""
Lambda handler for Discord interactions endpoint (slash commands).

Responsibilities:
- Validate Discord Ed25519 signature (MUST be < 3 seconds)
- Respond to PING with PONG
- Acknowledge slash commands with a deferred response (type 5)
- Publish question to SQS for async processing
- Return 200 immediately (never block on agent processing)
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

import boto3

from backend.models.discord_models import InteractionContext, InteractionType
from backend.models.agent_models import ProcessingMessage
from backend.services.discord_service import DiscordService

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Environment variables injected by CDK
_BOT_TOKEN_SECRET_ARN = os.environ.get("DISCORD_BOT_TOKEN_SECRET_ARN", "")
_PUBLIC_KEY_SECRET_ARN = os.environ.get("DISCORD_PUBLIC_KEY_SECRET_ARN", "")
_APPLICATION_ID = os.environ.get("DISCORD_APPLICATION_ID", "")
_GUILD_ID = os.environ.get("DISCORD_GUILD_ID", "")
_SQS_QUEUE_URL = os.environ.get("PROCESSING_QUEUE_URL", "")

# Cached clients (reused across Lambda warm invocations)
_secrets_client = boto3.client("secretsmanager")
_sqs_client = boto3.client("sqs")
_discord_service: DiscordService | None = None


def _get_discord_service() -> DiscordService:
    """Lazy-init Discord service, caching across warm Lambda invocations."""
    global _discord_service
    if _discord_service is None:
        bot_token = _get_secret(_BOT_TOKEN_SECRET_ARN)
        public_key = _get_secret(_PUBLIC_KEY_SECRET_ARN)
        _discord_service = DiscordService(
            bot_token=bot_token,
            application_id=_APPLICATION_ID,
            public_key=public_key,
        )
    return _discord_service


def _get_secret(secret_arn: str) -> str:
    """Retrieve secret value from AWS Secrets Manager."""
    try:
        response = _secrets_client.get_secret_value(SecretId=secret_arn)
        return response.get("SecretString", "")
    except Exception as e:
        logger.error("Failed to retrieve secret %s: %s", secret_arn, e)
        raise


def handler(event: dict, context: Any) -> dict:
    """
    Lambda handler for Discord interactions webhook.
    Must respond within 3 seconds for Discord slash command interactions.
    """
    # Extract raw body and headers
    raw_body = event.get("body", "")
    if event.get("isBase64Encoded"):
        import base64
        raw_body = base64.b64decode(raw_body).decode("utf-8")

    headers = {k.lower(): v for k, v in event.get("headers", {}).items()}
    signature = headers.get("x-signature-ed25519", "")
    timestamp = headers.get("x-signature-timestamp", "")

    # Step 1: Verify Discord signature (REQUIRED — 401 on failure)
    discord = _get_discord_service()
    if not discord.verify_discord_signature(
        raw_body=raw_body.encode("utf-8"),
        signature=signature,
        timestamp=timestamp,
    ):
        logger.warning("Invalid Discord signature — rejecting request")
        return {"statusCode": 401, "body": "Invalid signature"}

    # Step 2: Parse payload
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.error("Invalid JSON payload")
        return {"statusCode": 400, "body": "Invalid JSON"}

    interaction_type = payload.get("type")

    # Step 3: Handle PING (Discord verification handshake)
    if interaction_type == InteractionType.PING:
        logger.info("Received PING from Discord — responding with PONG")
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"type": 1}),  # PONG
        }

    # Step 4: Handle slash command interactions
    if interaction_type == InteractionType.APPLICATION_COMMAND:
        return _handle_slash_command(payload, discord)

    logger.info("Unhandled interaction type: %s", interaction_type)
    return {"statusCode": 200, "body": "OK"}


def _handle_slash_command(payload: dict, discord: DiscordService) -> dict:
    """Process a slash command interaction."""
    try:
        interaction = InteractionContext.from_payload(payload)
    except Exception as e:
        logger.error("Failed to parse interaction: %s", e)
        return {"statusCode": 400, "body": "Invalid interaction payload"}

    command_name = interaction.command.name if interaction.command else "unknown"
    question = interaction.command.question if interaction.command else ""

    if not question:
        # Commands like /faq and /help are handled with immediate responses
        return _handle_info_command(command_name, interaction)

    logger.info(
        "Slash command: /%s from user=%s correlation_id will be assigned",
        command_name,
        interaction.user_name,
    )

    # Determine if response should be ephemeral (/ask-private)
    is_private = command_name == "ask-private"

    # Acknowledge immediately with deferred response (Discord "thinking...")
    ack_success = discord.acknowledge_interaction(
        interaction_id=interaction.interaction_id,
        interaction_token=interaction.interaction_token,
        ephemeral=is_private,
    )
    if not ack_success:
        logger.error("Failed to acknowledge interaction %s", interaction.interaction_id)
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "type": 4,
                "data": {"content": "Sorry, I'm having trouble processing your request. Please try again."},
            }),
        }

    # Publish to SQS for async processing
    correlation_id = str(uuid.uuid4())
    message = ProcessingMessage(
        question=question,
        user_id=interaction.user_id,
        user_name=interaction.user_name,
        guild_id=interaction.guild_id or _GUILD_ID,
        channel_id=interaction.channel_id,
        source="slash_command",
        correlation_id=correlation_id,
        interaction_token=interaction.interaction_token,
        application_id=_APPLICATION_ID,
        is_private=is_private,
    )

    try:
        _sqs_client.send_message(
            QueueUrl=_SQS_QUEUE_URL,
            MessageBody=json.dumps(message.to_dict()),
            MessageGroupId=interaction.user_id,  # FIFO — group by user
            MessageDeduplicationId=correlation_id,
        )
        logger.info(
            "Published to SQS: correlation_id=%s user=%s",
            correlation_id,
            interaction.user_name,
        )
    except Exception as e:
        logger.error("Failed to publish to SQS: %s", e)
        # Edit the deferred response with an error message
        discord.edit_interaction_response(
            interaction_token=interaction.interaction_token,
            content="Sorry, I couldn't queue your question. Please try again in a moment.",
        )

    # Return 200 — Discord ack was already sent via acknowledge_interaction
    return {"statusCode": 200, "body": "Queued"}


def _handle_info_command(command_name: str, interaction: InteractionContext) -> dict:
    """Handle non-question commands that return immediate responses."""
    responses = {
        "faq": (
            "**BeSa AI FAQ** 📚\n"
            "Use `/ask <question>` to get an answer from our knowledge base.\n"
            "Use `/ask-private <question>` for a private response only you can see.\n"
            "Questions are answered from: FAQ → Discord History → AI Reasoning → AWS Docs"
        ),
        "help": (
            "**BeSa AI Help** 🤖\n"
            "`/ask <question>` — Ask a public question\n"
            "`/ask-private <question>` — Ask a private question\n"
            "`/faq` — View help and commands\n\n"
            "You can also type your question in this channel."
        ),
    }
    content = responses.get(command_name, "Unknown command.")
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"type": 4, "data": {"content": content, "flags": 64}}),
    }
