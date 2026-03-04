"""
Integration tests for admin_handler Lambda.

These tests exercise the full stack: HTTP routing → service layer → DynamoDB.
External services (Secrets Manager, Bedrock, Discord REST) are mocked.
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import boto3
import pytest
from moto import mock_aws


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _api_event(method: str, path: str, body: dict | None = None, claims: dict | None = None) -> dict:
    """Build a minimal API Gateway v1 proxy event."""
    event: dict = {
        "httpMethod": method.upper(),
        "path": path,
        "headers": {"Content-Type": "application/json"},
        "queryStringParameters": None,
        "body": json.dumps(body) if body else None,
        "requestContext": {
            "authorizer": {
                "claims": claims or {"sub": "test-user-id", "cognito:groups": "Admin,User"},
            }
        },
    }
    return event


def _make_lambda_ctx():
    ctx = MagicMock()
    ctx.function_name = "test-admin"
    ctx.aws_request_id = "test-request-id"
    return ctx


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def aws_env(monkeypatch):
    """Set required env vars and mock AWS with moto for the full test."""
    monkeypatch.setenv("CONFIG_TABLE_NAME", "besa-ai-assistant-config")
    monkeypatch.setenv("LOGS_TABLE_NAME", "besa-ai-assistant-logs")
    monkeypatch.setenv("RATE_LIMIT_TABLE_NAME", "besa-ai-assistant-rate-limits")
    monkeypatch.setenv("FAQ_BUCKET_NAME", "besa-ai-assistant-faq-123")
    monkeypatch.setenv("BEDROCK_KNOWLEDGE_BASE_ID", "TESTKBID")
    monkeypatch.setenv("BEDROCK_DATA_SOURCE_ID", "TESTDSID")
    monkeypatch.setenv("DISCORD_APPLICATION_ID", "1234567890")
    monkeypatch.setenv("DISCORD_GUILD_ID", "9876543210")
    monkeypatch.setenv("DISCORD_BOT_CHANNEL_ID", "1111111111")
    monkeypatch.setenv("DISCORD_BOT_TOKEN_SECRET_ARN", "arn:aws:secretsmanager:us-east-1:123:secret:test-token")
    monkeypatch.setenv("DISCORD_PUBLIC_KEY_SECRET_ARN", "arn:aws:secretsmanager:us-east-1:123:secret:test-key")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture(scope="function")
def tables(aws_env):
    """Create DynamoDB tables and return boto3 resource."""
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
# Tests: GET /api/configuration
# ---------------------------------------------------------------------------

class TestGetConfiguration:
    def test_returns_default_config_on_fresh_table(self, tables):
        """GET /api/configuration returns default config when table is empty."""
        # Import inside test to pick up env vars and mocked AWS clients
        import importlib
        import backend.handlers.admin_handler as handler_module

        # Reset module-level singletons
        handler_module._config_service = None

        event = _api_event("GET", "/api/configuration")
        response = handler_module.handler(event, _make_lambda_ctx())

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        # Config is serialised as DynamoDB item — check nested thresholds
        assert "thresholds" in body or "faq_similarity_threshold" in str(body)

    def test_returns_200_with_json_content_type(self, tables):
        import backend.handlers.admin_handler as handler_module
        handler_module._config_service = None

        event = _api_event("GET", "/api/configuration")
        response = handler_module.handler(event, _make_lambda_ctx())

        assert response["statusCode"] == 200
        assert "application/json" in response["headers"]["Content-Type"]


# ---------------------------------------------------------------------------
# Tests: PUT /api/configuration
# ---------------------------------------------------------------------------

class TestPutConfiguration:
    def test_saves_updated_threshold(self, tables):
        """PUT /api/configuration persists a new threshold value."""
        import backend.handlers.admin_handler as handler_module
        handler_module._config_service = None

        # First GET to prime the table with defaults
        handler_module.handler(_api_event("GET", "/api/configuration"), _make_lambda_ctx())
        handler_module._config_service._invalidate_cache()

        # PUT with updated threshold
        payload = {
            "thresholds": {
                "faq_similarity_threshold": 0.90,
                "discord_overlap_threshold": 0.70,
                "query_expansion_depth": 10,
            },
            "agents": {
                "enable_faq_agent": True,
                "enable_discord_agent": True,
                "enable_reasoning_agent": True,
                "enable_aws_docs_agent": False,
                "enable_orchestrator": True,
            },
            "rate_limit": {"max_requests_per_hour": 25},
        }
        event = _api_event("PUT", "/api/configuration", body=payload)
        response = handler_module.handler(event, _make_lambda_ctx())
        assert response["statusCode"] == 200

        # Verify persistence — new service instance reads updated value
        handler_module._config_service = None
        from backend.services.config_service import ConfigService
        svc = ConfigService("besa-ai-assistant-config")
        config = svc.load_config()
        assert config.thresholds.faq_similarity_threshold == 0.90

    def test_invalid_threshold_returns_400(self, tables):
        """PUT /api/configuration with out-of-range threshold returns 400."""
        import backend.handlers.admin_handler as handler_module
        handler_module._config_service = None

        payload = {
            "thresholds": {
                "faq_similarity_threshold": 2.0,  # Invalid — > 1.0
                "discord_overlap_threshold": 0.70,
                "query_expansion_depth": 10,
            }
        }
        event = _api_event("PUT", "/api/configuration", body=payload)
        response = handler_module.handler(event, _make_lambda_ctx())
        assert response["statusCode"] == 400

    def test_missing_body_returns_400(self, tables):
        """PUT /api/configuration with no body returns 400."""
        import backend.handlers.admin_handler as handler_module
        handler_module._config_service = None

        event = _api_event("PUT", "/api/configuration", body=None)
        response = handler_module.handler(event, _make_lambda_ctx())
        assert response["statusCode"] == 400


# ---------------------------------------------------------------------------
# Tests: POST /api/rate-limits/reset (Admin only)
# ---------------------------------------------------------------------------

class TestRateLimitReset:
    def test_admin_can_reset_user(self, tables):
        """POST /api/rate-limits/reset allows Admin to clear a user's counter."""
        import backend.handlers.admin_handler as handler_module
        handler_module._config_service = None
        handler_module._rate_limiter = None

        from backend.services.rate_limiter import RateLimiter
        rl = RateLimiter("besa-ai-assistant-rate-limits")
        # Exhaust limit for a user
        for _ in range(5):
            rl.check_and_increment("user-to-reset", max_per_hour=5)

        status_before = rl.get_status("user-to-reset", max_per_hour=5)
        assert status_before.allowed is False

        event = _api_event(
            "POST",
            "/api/rate-limits/reset",
            body={"user_id": "user-to-reset"},
            claims={"sub": "admin-id", "cognito:groups": "Admin"},
        )
        response = handler_module.handler(event, _make_lambda_ctx())
        assert response["statusCode"] == 200

        # Counter should be cleared
        status_after = rl.get_status("user-to-reset", max_per_hour=5)
        assert status_after.allowed is True

    def test_non_admin_cannot_reset(self, tables):
        """POST /api/rate-limits/reset returns 403 for non-admin callers."""
        import backend.handlers.admin_handler as handler_module
        handler_module._config_service = None
        handler_module._rate_limiter = None

        event = _api_event(
            "POST",
            "/api/rate-limits/reset",
            body={"user_id": "some-user"},
            claims={"sub": "regular-user-id", "cognito:groups": "User"},
        )
        response = handler_module.handler(event, _make_lambda_ctx())
        assert response["statusCode"] == 403


# ---------------------------------------------------------------------------
# Tests: Route handling
# ---------------------------------------------------------------------------

class TestRouting:
    def test_unknown_route_returns_404(self, tables):
        """Unregistered paths return 404."""
        import backend.handlers.admin_handler as handler_module
        handler_module._config_service = None

        event = _api_event("GET", "/api/does-not-exist")
        response = handler_module.handler(event, _make_lambda_ctx())
        assert response["statusCode"] == 404

    def test_cors_headers_present(self, tables):
        """All responses include CORS headers."""
        import backend.handlers.admin_handler as handler_module
        handler_module._config_service = None

        event = _api_event("GET", "/api/configuration")
        response = handler_module.handler(event, _make_lambda_ctx())

        assert "Access-Control-Allow-Origin" in response["headers"]
