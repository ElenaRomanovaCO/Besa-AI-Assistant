"""Unit tests for RateLimiter."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from backend.services.rate_limiter import RateLimiter


class TestRateLimiter:
    def test_first_request_is_allowed(self, dynamodb_tables):
        rl = RateLimiter("besa-ai-assistant-rate-limits")
        status = rl.check_and_increment("user-1", max_per_hour=20)
        assert status.allowed is True
        assert status.current_count == 1
        assert status.remaining == 19

    def test_requests_within_limit_are_allowed(self, dynamodb_tables):
        rl = RateLimiter("besa-ai-assistant-rate-limits")
        for i in range(5):
            status = rl.check_and_increment("user-2", max_per_hour=10)
            assert status.allowed is True
        assert status.current_count == 5

    def test_request_at_limit_is_denied(self, dynamodb_tables):
        rl = RateLimiter("besa-ai-assistant-rate-limits")
        # Use up all slots
        for _ in range(3):
            rl.check_and_increment("user-3", max_per_hour=3)
        # 4th request should be denied
        status = rl.check_and_increment("user-3", max_per_hour=3)
        assert status.allowed is False
        assert status.remaining == 0

    def test_different_users_have_separate_limits(self, dynamodb_tables):
        rl = RateLimiter("besa-ai-assistant-rate-limits")
        # User A uses up limit
        for _ in range(3):
            rl.check_and_increment("user-A", max_per_hour=3)

        # User B should still be allowed
        status_b = rl.check_and_increment("user-B", max_per_hour=3)
        assert status_b.allowed is True

    def test_reset_user_allows_requests_again(self, dynamodb_tables):
        rl = RateLimiter("besa-ai-assistant-rate-limits")
        # Exhaust limit
        for _ in range(3):
            rl.check_and_increment("user-reset", max_per_hour=3)

        denied = rl.check_and_increment("user-reset", max_per_hour=3)
        assert denied.allowed is False

        # Reset and try again
        rl.reset_user("user-reset")
        allowed = rl.check_and_increment("user-reset", max_per_hour=3)
        assert allowed.allowed is True

    def test_get_status_does_not_increment(self, dynamodb_tables):
        rl = RateLimiter("besa-ai-assistant-rate-limits")
        rl.check_and_increment("user-status", max_per_hour=10)

        before = rl.get_status("user-status", max_per_hour=10)
        after = rl.get_status("user-status", max_per_hour=10)

        assert before.current_count == after.current_count

    def test_cooldown_seconds_positive_when_denied(self, dynamodb_tables):
        rl = RateLimiter("besa-ai-assistant-rate-limits")
        for _ in range(2):
            rl.check_and_increment("user-cooldown", max_per_hour=2)

        denied = rl.check_and_increment("user-cooldown", max_per_hour=2)
        assert denied.allowed is False
        assert denied.cooldown_seconds > 0
        assert denied.cooldown_minutes >= 1
