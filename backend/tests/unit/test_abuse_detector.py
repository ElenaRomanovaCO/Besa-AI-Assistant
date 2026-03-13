"""Tests for abuse detection service."""

import pytest
import boto3
from moto import mock_aws

from backend.services.abuse_detector import AbuseDetector


@pytest.fixture
def abuse_table():
    """Create a mocked DynamoDB rate-limit table for abuse tracking."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.create_table(
            TableName="test-rate-limits",
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
        yield table


@pytest.fixture
def detector(abuse_table):
    return AbuseDetector("test-rate-limits", region="us-east-1")


class TestAbuseDetector:
    def test_first_attempt_not_blocked(self, detector):
        status = detector.record_attempt("user1", "test_pattern")
        assert not status.is_blocked
        assert status.attempt_count == 1

    def test_under_threshold_not_blocked(self, detector):
        for i in range(3):
            status = detector.record_attempt("user1", "test_pattern")
        assert not status.is_blocked
        assert status.attempt_count == 3

    def test_over_threshold_blocked(self, detector):
        for i in range(4):
            status = detector.record_attempt("user1", "test_pattern")
        assert status.is_blocked
        assert status.attempt_count == 4

    def test_different_users_independent(self, detector):
        for _ in range(4):
            detector.record_attempt("user1", "test")
        status = detector.record_attempt("user2", "test")
        assert not status.is_blocked
        assert status.attempt_count == 1

    def test_is_blocked_read_only(self, detector):
        # Not blocked initially
        status = detector.is_blocked("user1")
        assert not status.is_blocked

        # Block the user
        for _ in range(4):
            detector.record_attempt("user1", "test")

        # Read-only check
        status = detector.is_blocked("user1")
        assert status.is_blocked
        assert status.attempt_count == 4

    def test_reset_user(self, detector):
        for _ in range(4):
            detector.record_attempt("user1", "test")

        # Reset
        assert detector.reset_user("user1") is True

        # Should no longer be blocked
        status = detector.is_blocked("user1")
        assert not status.is_blocked
