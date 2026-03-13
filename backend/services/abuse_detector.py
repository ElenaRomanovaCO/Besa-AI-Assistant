"""Abuse detection: track per-user injection attempts and auto-block repeat offenders.

Uses the existing rate-limit DynamoDB table to track injection attempt counts.
If a user triggers input sanitization >3 times in 1 hour, they are temporarily
blocked (separate from the normal query rate limit).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Block threshold: number of injection attempts before temporary block
_MAX_ATTEMPTS_PER_HOUR = 3

# Block duration: 1 hour
_BLOCK_WINDOW_SECONDS = 3600


@dataclass
class AbuseStatus:
    """Result of abuse check."""
    is_blocked: bool
    attempt_count: int
    block_remaining_seconds: int = 0


class AbuseDetector:
    """
    Tracks per-user prompt injection attempts using DynamoDB.

    Uses the same rate-limit table with a different key prefix to avoid
    creating a new table. Injection attempts are counted in a 1-hour
    sliding window. After _MAX_ATTEMPTS_PER_HOUR attempts, the user
    is temporarily blocked.
    """

    def __init__(self, table_name: str, region: str = "us-east-1"):
        self._dynamodb = boto3.resource("dynamodb", region_name=region)
        self._table = self._dynamodb.Table(table_name)

    def record_attempt(self, user_id: str, pattern: str = "") -> AbuseStatus:
        """
        Record an injection attempt and check if the user should be blocked.

        Args:
            user_id: Discord user ID
            pattern: The injection pattern that was detected (for logging)

        Returns:
            AbuseStatus indicating whether the user is now blocked
        """
        now = int(time.time())
        reset_at = now + _BLOCK_WINDOW_SECONDS
        pk = f"abuse#{user_id}"

        try:
            response = self._table.update_item(
                Key={"pk": pk, "sk": "injection_count"},
                UpdateExpression=(
                    "SET #count = if_not_exists(#count, :zero) + :one, "
                    "#window_start = if_not_exists(#window_start, :now), "
                    "#ttl = :ttl, "
                    "#last_pattern = :pattern"
                ),
                ConditionExpression=(
                    "attribute_not_exists(#window_start) OR #window_start > :window_start"
                ),
                ExpressionAttributeNames={
                    "#count": "count",
                    "#window_start": "window_start",
                    "#ttl": "ttl",
                    "#last_pattern": "last_pattern",
                },
                ExpressionAttributeValues={
                    ":zero": 0,
                    ":one": 1,
                    ":now": now,
                    ":window_start": now - _BLOCK_WINDOW_SECONDS,
                    ":ttl": reset_at,
                    ":pattern": pattern or "unknown",
                },
                ReturnValues="ALL_NEW",
            )
            item = response["Attributes"]
            count = int(item.get("count", 1))
            is_blocked = count > _MAX_ATTEMPTS_PER_HOUR

            if is_blocked:
                logger.warning(
                    "User %s blocked: %d injection attempts in window (last pattern: %s)",
                    user_id, count, pattern,
                )

            return AbuseStatus(
                is_blocked=is_blocked,
                attempt_count=count,
                block_remaining_seconds=max(0, int(item.get("ttl", reset_at)) - now),
            )

        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "ConditionalCheckFailedException":
                # Window expired — reset and record first attempt in new window
                try:
                    self._table.put_item(
                        Item={
                            "pk": pk,
                            "sk": "injection_count",
                            "count": 1,
                            "window_start": now,
                            "ttl": reset_at,
                            "last_pattern": pattern or "unknown",
                        }
                    )
                except ClientError:
                    pass
                return AbuseStatus(is_blocked=False, attempt_count=1)
            logger.error("DynamoDB error recording abuse for %s: %s", user_id, e)
            # Fail open — don't block on DynamoDB errors
            return AbuseStatus(is_blocked=False, attempt_count=0)

    def is_blocked(self, user_id: str) -> AbuseStatus:
        """
        Check if a user is currently blocked (read-only, no increment).

        Args:
            user_id: Discord user ID

        Returns:
            AbuseStatus
        """
        now = int(time.time())
        try:
            response = self._table.get_item(
                Key={"pk": f"abuse#{user_id}", "sk": "injection_count"}
            )
            item = response.get("Item")
            if not item:
                return AbuseStatus(is_blocked=False, attempt_count=0)

            count = int(item.get("count", 0))
            ttl = int(item.get("ttl", 0))

            # Check if window has expired
            if ttl <= now:
                return AbuseStatus(is_blocked=False, attempt_count=0)

            return AbuseStatus(
                is_blocked=count > _MAX_ATTEMPTS_PER_HOUR,
                attempt_count=count,
                block_remaining_seconds=max(0, ttl - now),
            )
        except ClientError as e:
            logger.error("DynamoDB error checking abuse for %s: %s", user_id, e)
            return AbuseStatus(is_blocked=False, attempt_count=0)

    def reset_user(self, user_id: str) -> bool:
        """Admin action: reset abuse tracking for a user."""
        try:
            self._table.delete_item(
                Key={"pk": f"abuse#{user_id}", "sk": "injection_count"}
            )
            logger.info("Abuse tracking reset for user %s", user_id)
            return True
        except ClientError as e:
            logger.error("Failed to reset abuse tracking for %s: %s", user_id, e)
            return False
