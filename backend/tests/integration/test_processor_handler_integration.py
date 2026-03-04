"""
Integration tests for processor_handler Lambda.

Tests the full SQS-message → rate-limiter → orchestrator → Discord response flow.
Bedrock and Discord REST calls are mocked; DynamoDB is provided by moto.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock

import boto3
import pytest
from moto import mock_aws

from backend.models.agent_models import (
    BotResponse,
    ProcessingMessage,
    RankedAnswer,
    SourceType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_processing_message(
    question: str = "How do I increase Lambda timeout?",
    user_id: str = "user-123",
    user_name: str = "TestUser",
    source: str = "slash_command",
    interaction_token: str = "test-token",
) -> dict:
    msg = ProcessingMessage(
        question=question,
        user_id=user_id,
        user_name=user_name,
        guild_id="guild-123",
        channel_id="channel-123",
        source=source,
        interaction_token=interaction_token,
        application_id="app-123",
    )
    return msg.to_dict()


def _sqs_event(messages: list[dict], message_id_prefix: str = "msg") -> dict:
    return {
        "Records": [
            {
                "messageId": f"{message_id_prefix}-{i}",
                "body": json.dumps(m),
                "attributes": {},
                "messageAttributes": {},
            }
            for i, m in enumerate(messages)
        ]
    }


def _make_bot_response(confidence: float = 0.85) -> BotResponse:
    answer = RankedAnswer(
        rank=1,
        source_type=SourceType.FAQ,
        answer="Go to Lambda console → Configuration → General configuration → Timeout.",
        confidence_score=confidence,
        source_urls=[],
    )
    return BotResponse(
        answers=[answer],
        primary_source=SourceType.FAQ,
        total_processing_time_ms=500,
        correlation_id=str(uuid.uuid4()),
    )


def _mock_discord():
    mock = MagicMock()
    mock.edit_interaction_response.return_value = True
    mock.post_thread_reply.return_value = "msg-id-123"
    return mock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def aws_env(monkeypatch):
    monkeypatch.setenv("CONFIG_TABLE_NAME", "besa-ai-assistant-config")
    monkeypatch.setenv("LOGS_TABLE_NAME", "besa-ai-assistant-logs")
    monkeypatch.setenv("RATE_LIMIT_TABLE_NAME", "besa-ai-assistant-rate-limits")
    monkeypatch.setenv("BEDROCK_KNOWLEDGE_BASE_ID", "TESTKBID")
    monkeypatch.setenv("DISCORD_APPLICATION_ID", "1234567890")
    monkeypatch.setenv("DISCORD_BOT_TOKEN_SECRET_ARN", "arn:aws:secretsmanager:us-east-1:123:secret:test-token")
    monkeypatch.setenv("DISCORD_PUBLIC_KEY_SECRET_ARN", "arn:aws:secretsmanager:us-east-1:123:secret:test-key")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture(scope="function")
def dynamodb_tables(aws_env):
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

        dynamodb.create_table(
            TableName="besa-ai-assistant-config",
            KeySchema=[
                {"AttributeName": "config_id", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "config_id", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
                {"AttributeName": "pk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "pk-sk-index",
                    "KeySchema": [
                        {"AttributeName": "pk", "KeyType": "HASH"},
                        {"AttributeName": "sk", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
        )

        dynamodb.create_table(
            TableName="besa-ai-assistant-rate-limits",
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        dynamodb.create_table(
            TableName="besa-ai-assistant-logs",
            KeySchema=[{"AttributeName": "log_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "log_id", "AttributeType": "S"},
                {"AttributeName": "log_type", "AttributeType": "S"},
                {"AttributeName": "timestamp", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "log-type-timestamp-index",
                    "KeySchema": [
                        {"AttributeName": "log_type", "KeyType": "HASH"},
                        {"AttributeName": "timestamp", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
        )

        yield dynamodb


# ---------------------------------------------------------------------------
# Shared setup: inject mocks into processor module
# ---------------------------------------------------------------------------

def _setup_processor(dynamodb_tables, orchestrator_mock):
    """Inject pre-built service mocks into processor_handler module singletons."""
    import backend.handlers.processor_handler as proc
    from backend.services.config_service import ConfigService
    from backend.services.rate_limiter import RateLimiter

    mock_discord = _mock_discord()
    proc._discord_service = mock_discord
    proc._config_service = ConfigService("besa-ai-assistant-config")
    proc._rate_limiter = RateLimiter("besa-ai-assistant-rate-limits")
    proc._orchestrator = orchestrator_mock
    return proc, mock_discord


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSlashCommandFlow:
    def test_successful_answer_edits_deferred_response(self, dynamodb_tables):
        """Slash command → orchestrator succeeds → edits the deferred interaction."""
        mock_orch = MagicMock()
        mock_orch.handle_question.return_value = _make_bot_response(confidence=0.90)

        proc, mock_discord = _setup_processor(dynamodb_tables, mock_orch)

        event = _sqs_event([_make_processing_message(source="slash_command", interaction_token="tok-abc")])
        result = proc.handler(event, MagicMock())

        assert result == {"statusCode": 200}
        mock_discord.edit_interaction_response.assert_called_once()
        mock_discord.post_thread_reply.assert_not_called()

    def test_channel_message_posts_thread_reply(self, dynamodb_tables):
        """Channel message source → orchestrator succeeds → posts thread reply."""
        mock_orch = MagicMock()
        mock_orch.handle_question.return_value = _make_bot_response()

        proc, mock_discord = _setup_processor(dynamodb_tables, mock_orch)

        msg = _make_processing_message(source="channel_message", interaction_token=None)
        event = _sqs_event([msg])
        result = proc.handler(event, MagicMock())

        assert result == {"statusCode": 200}
        mock_discord.post_thread_reply.assert_called_once()
        mock_discord.edit_interaction_response.assert_not_called()


class TestRateLimiting:
    def test_rate_limited_user_receives_cooldown_message(self, dynamodb_tables):
        """When a user exhausts their rate limit, they get a message and the orchestrator is skipped."""
        mock_orch = MagicMock()
        proc, mock_discord = _setup_processor(dynamodb_tables, mock_orch)

        # Exhaust the limit for this user
        config = proc._config_service.load_config()
        max_req = config.rate_limit.max_queries_per_hour
        for _ in range(max_req):
            proc._rate_limiter.check_and_increment("rate-limited-user", max_per_hour=max_req)

        msg = _make_processing_message(user_id="rate-limited-user")
        event = _sqs_event([msg])
        result = proc.handler(event, MagicMock())

        assert result == {"statusCode": 200}
        # Orchestrator should NOT have run
        mock_orch.handle_question.assert_not_called()
        # Discord should still receive a response (the rate-limit message)
        mock_discord.edit_interaction_response.assert_called_once()

    def test_user_within_limit_is_processed(self, dynamodb_tables):
        """A user under their limit should have their question processed normally."""
        mock_orch = MagicMock()
        mock_orch.handle_question.return_value = _make_bot_response()
        proc, mock_discord = _setup_processor(dynamodb_tables, mock_orch)

        msg = _make_processing_message(user_id="fresh-user")
        event = _sqs_event([msg])
        result = proc.handler(event, MagicMock())

        assert result == {"statusCode": 200}
        mock_orch.handle_question.assert_called_once()

    def test_different_users_have_independent_limits(self, dynamodb_tables):
        """Exhausting one user's limit does not affect another user."""
        mock_orch = MagicMock()
        mock_orch.handle_question.return_value = _make_bot_response()
        proc, mock_discord = _setup_processor(dynamodb_tables, mock_orch)

        config = proc._config_service.load_config()
        max_req = config.rate_limit.max_queries_per_hour

        # Exhaust user-A
        for _ in range(max_req):
            proc._rate_limiter.check_and_increment("user-A", max_per_hour=max_req)

        # user-B should still be processed
        msg = _make_processing_message(user_id="user-B")
        event = _sqs_event([msg])
        proc.handler(event, MagicMock())
        mock_orch.handle_question.assert_called_once()


class TestErrorHandling:
    def test_orchestrator_failure_returns_batch_item_failure(self, dynamodb_tables):
        """When the orchestrator raises, the SQS record is returned as a batch failure."""
        mock_orch = MagicMock()
        mock_orch.handle_question.side_effect = RuntimeError("Bedrock unavailable")

        proc, mock_discord = _setup_processor(dynamodb_tables, mock_orch)

        msg = _make_processing_message(user_id="crash-user")
        event = _sqs_event([msg], message_id_prefix="fail")
        result = proc.handler(event, MagicMock())

        assert "batchItemFailures" in result
        assert result["batchItemFailures"][0]["itemIdentifier"] == "fail-0"

    def test_malformed_sqs_body_returns_batch_failure(self, dynamodb_tables):
        """A record with invalid JSON body should be returned as a batch failure."""
        mock_orch = MagicMock()
        proc, _ = _setup_processor(dynamodb_tables, mock_orch)

        event = {
            "Records": [
                {
                    "messageId": "bad-msg-0",
                    "body": "not valid json {{{{",
                    "attributes": {},
                    "messageAttributes": {},
                }
            ]
        }
        result = proc.handler(event, MagicMock())

        assert "batchItemFailures" in result
        assert result["batchItemFailures"][0]["itemIdentifier"] == "bad-msg-0"

    def test_partial_batch_failure_only_returns_failed_items(self, dynamodb_tables):
        """With 3 messages where the 2nd fails, only the 2nd is in batchItemFailures."""
        call_count = 0

        def flaky(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("Transient error")
            return _make_bot_response()

        mock_orch = MagicMock()
        mock_orch.handle_question.side_effect = flaky
        proc, _ = _setup_processor(dynamodb_tables, mock_orch)

        messages = [
            _make_processing_message(user_id=f"user-{i}", interaction_token=f"tok-{i}")
            for i in range(3)
        ]
        event = {
            "Records": [
                {"messageId": f"msg-{i}", "body": json.dumps(m), "attributes": {}, "messageAttributes": {}}
                for i, m in enumerate(messages)
            ]
        }
        result = proc.handler(event, MagicMock())

        assert "batchItemFailures" in result
        assert len(result["batchItemFailures"]) == 1
        assert result["batchItemFailures"][0]["itemIdentifier"] == "msg-1"
