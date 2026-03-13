"""
BeSa AI Assistant — Load Test (Locust)

Simulates Discord webhook interactions to stress-test the API Gateway
and webhook Lambda under concurrent load.

Usage:
    pip install locust
    locust -f backend/tests/load/locustfile.py --host https://<API_GATEWAY_URL>

    # Headless mode (100 users, 10/s spawn rate, 5 minutes):
    locust -f backend/tests/load/locustfile.py \
        --host https://<API_GATEWAY_URL> \
        --headless -u 100 -r 10 --run-time 5m

Environment variables:
    WEBHOOK_URL: Full webhook URL (e.g., https://xyz.execute-api.us-east-1.amazonaws.com/prod/discord/webhook)
    DISCORD_PUBLIC_KEY: Discord public key for signature generation (optional — tests without sig verify)

Notes:
    - These tests hit the real API Gateway but use invalid Discord signatures,
      so webhook Lambda will reject with 401. This tests the infrastructure
      path (API GW → Lambda cold start → response) without processing real questions.
    - For full end-to-end load testing, use the /signed-webhook task with valid signatures.
"""

from __future__ import annotations

import json
import os
import time
import uuid

from locust import HttpUser, between, task


# Sample questions that represent realistic workshop queries
SAMPLE_QUESTIONS = [
    "How do I create an S3 bucket with versioning enabled?",
    "What is the difference between SQS and SNS?",
    "How do I set up a VPC with private subnets?",
    "My Lambda function is timing out, how do I debug it?",
    "How do I configure IAM roles for cross-account access?",
    "What is the best practice for DynamoDB partition key design?",
    "How do I enable CloudWatch alarms for my Lambda?",
    "What is the difference between Application and Network Load Balancer?",
    "How do I use AWS CDK to deploy a Lambda function?",
    "My API Gateway is returning 502 errors, what should I check?",
    "How do I set up CI/CD with CodePipeline?",
    "What are the limits for Lambda concurrent executions?",
    "How do I encrypt data at rest in DynamoDB?",
    "What is AWS Bedrock and how do I use it?",
    "How do I configure a custom domain for API Gateway?",
]


def _make_discord_interaction(question: str) -> dict:
    """Build a mock Discord slash command interaction payload."""
    return {
        "type": 2,  # APPLICATION_COMMAND
        "id": str(uuid.uuid4().int)[:18],
        "application_id": "000000000000000000",
        "channel_id": "000000000000000001",
        "guild_id": "000000000000000002",
        "token": f"mock-token-{uuid.uuid4().hex[:16]}",
        "data": {
            "id": "000000000000000003",
            "name": "ask",
            "options": [
                {"name": "question", "type": 3, "value": question},
            ],
        },
        "member": {
            "user": {
                "id": str(uuid.uuid4().int)[:18],
                "username": f"loadtest-user-{uuid.uuid4().hex[:6]}",
                "discriminator": "0000",
            },
        },
    }


class DiscordWebhookUser(HttpUser):
    """Simulates Discord sending webhook interactions to the bot."""

    wait_time = between(1, 5)  # 1-5 seconds between requests per user

    @task(10)
    def ask_question(self):
        """Send a slash command interaction (most common action)."""
        question = SAMPLE_QUESTIONS[int(time.time() * 1000) % len(SAMPLE_QUESTIONS)]
        payload = _make_discord_interaction(question)

        # Send without valid Discord signature — will get 401
        # This still tests: API GW routing, Lambda cold start, request parsing
        self.client.post(
            "/discord/webhook",
            json=payload,
            headers={
                "Content-Type": "application/json",
                "X-Signature-Ed25519": "0" * 128,
                "X-Signature-Timestamp": str(int(time.time())),
            },
            name="/discord/webhook [ask]",
        )

    @task(2)
    def ping(self):
        """Send a Discord PING interaction (health check)."""
        self.client.post(
            "/discord/webhook",
            json={"type": 1},  # PING
            headers={
                "Content-Type": "application/json",
                "X-Signature-Ed25519": "0" * 128,
                "X-Signature-Timestamp": str(int(time.time())),
            },
            name="/discord/webhook [ping]",
        )

    @task(1)
    def invalid_payload(self):
        """Send an invalid payload to test error handling."""
        self.client.post(
            "/discord/webhook",
            data="not json",
            headers={
                "Content-Type": "application/json",
                "X-Signature-Ed25519": "0" * 128,
                "X-Signature-Timestamp": str(int(time.time())),
            },
            name="/discord/webhook [invalid]",
        )


class AdminAPIUser(HttpUser):
    """Simulates admin UI API calls (lower frequency)."""

    wait_time = between(3, 10)

    @task(5)
    def get_configuration(self):
        """Fetch bot configuration."""
        self.client.get(
            "/api/configuration",
            name="/api/configuration [GET]",
        )

    @task(3)
    def get_logs(self):
        """Fetch query logs."""
        self.client.get(
            "/api/logs/queries",
            name="/api/logs/queries [GET]",
        )

    @task(2)
    def get_analytics(self):
        """Fetch analytics overview."""
        self.client.get(
            "/api/analytics/overview",
            name="/api/analytics/overview [GET]",
        )

    @task(1)
    def get_faq_entries(self):
        """Fetch FAQ entries."""
        self.client.get(
            "/api/faq/entries",
            name="/api/faq/entries [GET]",
        )
