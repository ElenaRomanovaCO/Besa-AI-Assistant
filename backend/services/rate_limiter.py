"""DynamoDB-backed per-user rate limiter using TTL-based counters."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

_WINDOW_SECONDS = 3600  # 1-hour sliding window


@dataclass
class RateLimitStatus:
    allowed: bool
    remaining: int
    reset_at_unix: int  # Unix timestamp when the window resets
    current_count: int

    @property
    def cooldown_seconds(self) -> int:
        return max(0, self.reset_at_unix - int(time.time()))

    @property
    def cooldown_minutes(self) -> int:
        return max(1, self.cooldown_seconds // 60)


class RateLimiter:
    """
    Per-user rate limiter using DynamoDB.
    Uses a single item per user with TTL for automatic cleanup.
    Counter resets after WINDOW_SECONDS (1 hour).
    """

    def __init__(self, table_name: str, region: str = "us-east-1"):
        self._dynamodb = boto3.resource("dynamodb", region_name=region)
        self._table = self._dynamodb.Table(table_name)

    def check_and_increment(
        self, user_id: str, max_per_hour: int
    ) -> RateLimitStatus:
        """
        Atomically check the rate limit and increment the counter.
        Returns RateLimitStatus with allowed=True if the request should proceed.
        """
        now = int(time.time())
        window_start = now - _WINDOW_SECONDS
        reset_at = now + _WINDOW_SECONDS
        pk = f"rate#{user_id}"

        try:
            # Atomic conditional update: increment if under limit and in window
            response = self._table.update_item(
                Key={"pk": pk, "sk": "rate_limit"},
                UpdateExpression=(
                    "SET #count = if_not_exists(#count, :zero) + :one, "
                    "#window_start = if_not_exists(#window_start, :now), "
                    "#ttl = :ttl"
                ),
                ConditionExpression=(
                    "(attribute_not_exists(#count) OR #count < :max) "
                    "AND (attribute_not_exists(#window_start) OR #window_start > :window_start)"
                ),
                ExpressionAttributeNames={
                    "#count": "count",
                    "#window_start": "window_start",
                    "#ttl": "ttl",
                },
                ExpressionAttributeValues={
                    ":zero": 0,
                    ":one": 1,
                    ":max": max_per_hour,
                    ":now": now,
                    ":window_start": window_start,
                    ":ttl": reset_at,
                },
                ReturnValues="ALL_NEW",
            )
            item = response["Attributes"]
            current_count = int(item.get("count", 1))
            remaining = max(0, max_per_hour - current_count)
            return RateLimitStatus(
                allowed=True,
                remaining=remaining,
                reset_at_unix=int(item.get("ttl", reset_at)),
                current_count=current_count,
            )

        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "ConditionalCheckFailedException":
                # Rate limit exceeded — fetch current count for error message
                current = self._get_current_count(user_id)
                return RateLimitStatus(
                    allowed=False,
                    remaining=0,
                    reset_at_unix=current.get("ttl", reset_at),
                    current_count=current.get("count", max_per_hour),
                )
            logger.error("DynamoDB error checking rate limit for %s: %s", user_id, e)
            # Fail open — allow the request on DynamoDB errors
            return RateLimitStatus(
                allowed=True,
                remaining=max_per_hour,
                reset_at_unix=reset_at,
                current_count=0,
            )

    def _get_current_count(self, user_id: str) -> dict:
        """Fetch current rate limit state for a user (read-only)."""
        try:
            response = self._table.get_item(
                Key={"pk": f"rate#{user_id}", "sk": "rate_limit"}
            )
            return response.get("Item", {})
        except ClientError:
            return {}

    def reset_user(self, user_id: str) -> bool:
        """Admin action: reset rate limit for a specific user."""
        try:
            self._table.delete_item(
                Key={"pk": f"rate#{user_id}", "sk": "rate_limit"}
            )
            logger.info("Rate limit reset for user %s", user_id)
            return True
        except ClientError as e:
            logger.error("Failed to reset rate limit for %s: %s", user_id, e)
            return False

    def get_status(self, user_id: str, max_per_hour: int) -> RateLimitStatus:
        """Read-only check of rate limit status (does not increment)."""
        item = self._get_current_count(user_id)
        now = int(time.time())
        count = int(item.get("count", 0))
        ttl = int(item.get("ttl", now + _WINDOW_SECONDS))
        return RateLimitStatus(
            allowed=count < max_per_hour,
            remaining=max(0, max_per_hour - count),
            reset_at_unix=ttl,
            current_count=count,
        )
