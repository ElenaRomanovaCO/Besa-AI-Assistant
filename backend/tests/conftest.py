"""Shared test fixtures and helpers."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
import boto3
from moto import mock_aws

# Configure test environment variables before any imports
os.environ.update({
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SECURITY_TOKEN": "testing",
    "AWS_SESSION_TOKEN": "testing",
    "CONFIG_TABLE_NAME": "besa-ai-assistant-config",
    "LOGS_TABLE_NAME": "besa-ai-assistant-logs",
    "RATE_LIMIT_TABLE_NAME": "besa-ai-assistant-rate-limits",
    "STATE_TABLE_NAME": "besa-ai-assistant-state",
    "FAQ_BUCKET_NAME": "besa-ai-assistant-faq-123456789",
    "BEDROCK_KNOWLEDGE_BASE_ID": "TESTKNOWLEDGEBASEID",
    "BEDROCK_DATA_SOURCE_ID": "TESTDATASOURCEID",
    "DISCORD_APPLICATION_ID": "1234567890",
    "DISCORD_GUILD_ID": "9876543210",
    "DISCORD_BOT_CHANNEL_ID": "1111111111",
    "PROCESSING_QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/123456789/test-queue.fifo",
    "DISCORD_BOT_TOKEN_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:123:secret:test-token",
    "DISCORD_PUBLIC_KEY_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:123:secret:test-key",
})


@pytest.fixture(scope="function")
def aws_credentials():
    """Mocked AWS credentials for moto."""
    with mock_aws():
        yield


@pytest.fixture
def dynamodb_tables(aws_credentials):
    """Create DynamoDB tables for testing."""
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

    # Config table
    config_table = dynamodb.create_table(
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

    # Rate limit table
    rate_table = dynamodb.create_table(
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

    # Logs table
    logs_table = dynamodb.create_table(
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

    return {
        "config": config_table,
        "rate_limits": rate_table,
        "logs": logs_table,
    }


@pytest.fixture
def mock_discord_service():
    """Mock DiscordService for tests that don't need real Discord API calls."""
    mock = MagicMock()
    mock.verify_discord_signature.return_value = True
    mock.acknowledge_interaction.return_value = True
    mock.edit_interaction_response.return_value = True
    mock.post_thread_reply.return_value = "1234567890"
    mock.get_channel_messages.return_value = []
    mock.get_guild_channels.return_value = []
    return mock


@pytest.fixture
def sample_faq_csv() -> str:
    return (
        "id,question,answer,category,tags\n"
        "faq-1,How do I increase Lambda timeout?,Go to Lambda console → Configuration → General configuration → Timeout.,Lambda,lambda;timeout;configuration\n"
        "faq-2,What is the maximum Lambda memory?,Lambda supports 128MB to 10240MB (10GB).,Lambda,lambda;memory;limits\n"
        "faq-3,How do I connect Lambda to DynamoDB?,Use boto3 with appropriate IAM role. No VPC needed for DynamoDB access.,Lambda,lambda;dynamodb;boto3\n"
    )


@pytest.fixture
def sample_faq_json() -> str:
    import json
    return json.dumps([
        {
            "id": "faq-1",
            "question": "How do I increase Lambda timeout?",
            "answer": "Go to Lambda console → Configuration → General configuration → Timeout.",
            "category": "Lambda",
            "tags": ["lambda", "timeout"],
        },
        {
            "id": "faq-2",
            "question": "What is the maximum Lambda memory?",
            "answer": "Lambda supports 128MB to 10240MB (10GB).",
            "category": "Lambda",
            "tags": ["lambda", "memory"],
        },
    ])
