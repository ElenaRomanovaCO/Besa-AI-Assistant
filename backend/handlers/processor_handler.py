"""
Lambda handler for agent processing (SQS-triggered).

Triggered by SQS messages published by webhook_handler or poller_handler.
Runs the full multi-agent waterfall and posts the response to Discord.
This Lambda can run for up to 15 minutes (configured in CDK).
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any

import boto3

from backend.agents.aws_docs_agent import AWSDocsAgent
from backend.agents.discord_agent import DiscordAgent
from backend.agents.faq_agent import FAQAgent
from backend.agents.orchestrator import OrchestratorAgent
from backend.agents.reasoning_agent import ReasoningAgent
from backend.models.agent_models import BotResponse, ProcessingMessage, QuestionContext
from backend.models.agent_models import WaterfallConfig
from backend.services.config_service import ConfigService
from backend.services.discord_service import DiscordService
from backend.services.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Environment variables
_BOT_TOKEN_SECRET_ARN = os.environ.get("DISCORD_BOT_TOKEN_SECRET_ARN", "")
_PUBLIC_KEY_SECRET_ARN = os.environ.get("DISCORD_PUBLIC_KEY_SECRET_ARN", "")
_APPLICATION_ID = os.environ.get("DISCORD_APPLICATION_ID", "")
_CONFIG_TABLE = os.environ.get("CONFIG_TABLE_NAME", "")
_LOGS_TABLE = os.environ.get("LOGS_TABLE_NAME", "")
_RATE_LIMIT_TABLE = os.environ.get("RATE_LIMIT_TABLE_NAME", "")
_KNOWLEDGE_BASE_ID = os.environ.get("BEDROCK_KNOWLEDGE_BASE_ID", "")
_AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

_secrets_client = boto3.client("secretsmanager")
_dynamodb = boto3.resource("dynamodb", region_name=_AWS_REGION)

# Lazy-initialized service singletons (warm Lambda reuse)
_discord_service: DiscordService | None = None
_config_service: ConfigService | None = None
_rate_limiter: RateLimiter | None = None
_orchestrator: OrchestratorAgent | None = None


def _init_services() -> tuple[
    DiscordService, ConfigService, RateLimiter, OrchestratorAgent
]:
    """Initialize all services, reusing across warm Lambda invocations."""
    global _discord_service, _config_service, _rate_limiter, _orchestrator

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

    if _config_service is None:
        _config_service = ConfigService(_CONFIG_TABLE, region=_AWS_REGION)

    if _rate_limiter is None:
        _rate_limiter = RateLimiter(_RATE_LIMIT_TABLE, region=_AWS_REGION)

    if _orchestrator is None:
        faq_agent = FAQAgent(
            knowledge_base_id=_KNOWLEDGE_BASE_ID,
            region=_AWS_REGION,
        )
        discord_agent = DiscordAgent(
            discord_service=_discord_service,
            region=_AWS_REGION,
        )
        reasoning_agent = ReasoningAgent(region=_AWS_REGION)
        aws_docs_agent = AWSDocsAgent(region=_AWS_REGION)
        _orchestrator = OrchestratorAgent(
            faq_agent=faq_agent,
            discord_agent=discord_agent,
            reasoning_agent=reasoning_agent,
            aws_docs_agent=aws_docs_agent,
            region=_AWS_REGION,
        )

    return _discord_service, _config_service, _rate_limiter, _orchestrator


def handler(event: dict, context: Any) -> dict:
    """
    SQS-triggered Lambda handler.
    Processes one or more SQS messages (batch size = 1 recommended for agent workloads).
    """
    discord, config_svc, rate_limiter, orchestrator = _init_services()
    failed_records = []

    for record in event.get("Records", []):
        message_id = record.get("messageId", "unknown")
        try:
            body = json.loads(record["body"])
            processing_msg = ProcessingMessage.from_dict(body)
            _process_question(
                processing_msg, discord, config_svc, rate_limiter, orchestrator
            )
        except Exception as e:
            logger.error(
                "Failed to process SQS record %s: %s", message_id, e, exc_info=True
            )
            failed_records.append({"itemIdentifier": message_id})

    # Return failed records so SQS can retry them
    if failed_records:
        return {"batchItemFailures": failed_records}
    return {"statusCode": 200}


def _process_question(
    msg: ProcessingMessage,
    discord: DiscordService,
    config_svc: ConfigService,
    rate_limiter: RateLimiter,
    orchestrator: OrchestratorAgent,
) -> None:
    """Process a single question through the agent waterfall."""
    start_time = time.time()
    correlation_id = msg.correlation_id
    logger.info(
        "Processing question: correlation_id=%s user=%s source=%s",
        correlation_id,
        msg.user_name,
        msg.source,
    )

    # Load system config
    system_config = config_svc.load_config()
    waterfall_config = WaterfallConfig(
        faq_threshold=system_config.thresholds.faq_similarity_threshold,
        discord_overlap_threshold=system_config.thresholds.discord_overlap_threshold,
        query_expansion_depth=system_config.thresholds.query_expansion_depth,
        max_discord_results=system_config.thresholds.max_discord_results,
        max_faq_results=system_config.thresholds.max_faq_results,
        enable_reasoning_agent=system_config.agents.enable_reasoning_agent,
        enable_discord_agent=system_config.agents.enable_discord_agent,
        enable_aws_docs_agent=system_config.agents.enable_aws_docs_agent,
        searchable_channel_ids=system_config.searchable_channel_ids,
        rate_limit_per_hour=system_config.rate_limit.max_queries_per_hour,
    )

    # Check rate limit
    rate_status = rate_limiter.check_and_increment(
        user_id=msg.user_id,
        max_per_hour=waterfall_config.rate_limit_per_hour,
    )

    if not rate_status.allowed:
        cooldown_msg = system_config.rate_limit.format_cooldown_message(
            max_queries=waterfall_config.rate_limit_per_hour,
            remaining_seconds=rate_status.cooldown_seconds,
        )
        _post_response_to_discord(discord, msg, cooldown_msg, is_error=True)
        return

    # Build question context
    question_context = QuestionContext(
        question=msg.question,
        user_id=msg.user_id,
        user_name=msg.user_name,
        guild_id=msg.guild_id,
        channel_id=msg.channel_id,
        interaction_token=msg.interaction_token,
        application_id=msg.application_id,
        original_message_id=msg.original_message_id,
        is_private=msg.is_private,
        correlation_id=correlation_id,
    )

    # Run the orchestrator waterfall
    try:
        bot_response = orchestrator.handle_question(
            question=msg.question,
            context=question_context,
            config=waterfall_config,
        )
    except Exception as e:
        logger.error(
            "Orchestrator error for correlation_id=%s: %s", correlation_id, e
        )
        _post_response_to_discord(
            discord,
            msg,
            "I encountered an error while processing your question. Please try again.",
            is_error=True,
        )
        return

    # Post response to Discord
    processing_time_ms = int((time.time() - start_time) * 1000)
    _post_response_to_discord(discord, msg, bot_response=bot_response)

    # Log query to DynamoDB
    _log_query(
        msg=msg,
        bot_response=bot_response,
        processing_time_ms=processing_time_ms,
    )

    logger.info(
        "Completed: correlation_id=%s source=%s confidence=%.2f time=%dms",
        correlation_id,
        bot_response.primary_source.value,
        bot_response.primary_answer.confidence_score if bot_response.primary_answer else 0,
        processing_time_ms,
    )


def _post_response_to_discord(
    discord: DiscordService,
    msg: ProcessingMessage,
    text: str = "",
    bot_response: BotResponse | None = None,
    is_error: bool = False,
) -> None:
    """
    Post agent response to Discord.
    - Slash commands: edit the deferred interaction response
    - Channel messages: post a threaded reply
    """
    if bot_response and bot_response.primary_answer:
        answer = bot_response.primary_answer
        embed = DiscordService.format_answer_embed(
            answer=answer.answer,
            source=answer.source_type.value,
            confidence=answer.confidence_score,
            source_urls=answer.source_urls,
            requires_verification=answer.requires_verification,
        )
        embeds = [embed]
        content = ""  # Use embed for rich formatting
    else:
        embeds = None
        content = text or "I'm sorry, I couldn't find an answer to your question."

    if msg.source == "slash_command" and msg.interaction_token:
        # Edit the deferred interaction response
        discord.edit_interaction_response(
            interaction_token=msg.interaction_token,
            content=content,
            embeds=embeds,
        )
    else:
        # Post as a threaded reply to the original channel message
        discord.post_thread_reply(
            channel_id=msg.channel_id,
            content=content,
            reply_to_message_id=msg.original_message_id,
            embeds=embeds,
        )


def _log_query(
    msg: ProcessingMessage,
    bot_response: BotResponse,
    processing_time_ms: int,
) -> None:
    """Log query details to DynamoDB for admin analytics."""
    try:
        table = _dynamodb.Table(_LOGS_TABLE)
        log_id = f"query#{msg.correlation_id}"
        primary = bot_response.primary_answer

        table.put_item(
            Item={
                "log_id": log_id,
                "log_type": "query",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "correlation_id": msg.correlation_id,
                "user_id": msg.user_id,
                "user_name": msg.user_name,
                "question": msg.question[:1000],
                "source": bot_response.primary_source.value,
                "confidence": str(primary.confidence_score if primary else 0),
                "response_time_ms": processing_time_ms,
                "waterfall_steps": bot_response.waterfall_steps_executed,
                "channel_id": msg.channel_id,
                "guild_id": msg.guild_id,
                # TTL for 90-day auto-expiry
                "ttl": int(time.time()) + (90 * 24 * 3600),
            }
        )
    except Exception as e:
        logger.warning("Failed to log query %s: %s", msg.correlation_id, e)
