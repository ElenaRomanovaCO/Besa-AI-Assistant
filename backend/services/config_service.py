"""DynamoDB-backed configuration service with in-memory caching."""

from __future__ import annotations

import json
import logging
import time
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from backend.models.config_models import SystemConfig

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 300  # 5-minute cache


class ConfigService:
    """
    Manages system configuration in DynamoDB with an in-memory write-through cache.
    Configuration changes applied immediately (cache invalidated on write).
    """

    def __init__(self, table_name: str, region: str = "us-east-1"):
        self._table_name = table_name
        self._dynamodb = boto3.resource("dynamodb", region_name=region)
        self._table = self._dynamodb.Table(table_name)
        self._cache: Optional[SystemConfig] = None
        self._cache_loaded_at: float = 0.0

    def _is_cache_valid(self) -> bool:
        return (
            self._cache is not None
            and (time.time() - self._cache_loaded_at) < _CACHE_TTL_SECONDS
        )

    def _invalidate_cache(self) -> None:
        self._cache = None
        self._cache_loaded_at = 0.0

    def load_config(self) -> SystemConfig:
        """
        Load system configuration. Returns cached value if fresh.
        Falls back to default config if DynamoDB is unavailable.
        """
        if self._is_cache_valid():
            return self._cache  # type: ignore[return-value]

        try:
            response = self._table.get_item(Key={"config_id": "system", "sk": "config"})
            item = response.get("Item")
            if item:
                config = SystemConfig.from_dynamodb_item(item)
            else:
                logger.info("No config found in DynamoDB, using defaults and seeding.")
                config = SystemConfig.default()
                self._seed_defaults(config)
            self._cache = config
            self._cache_loaded_at = time.time()
            return config
        except ClientError as e:
            logger.error("DynamoDB error loading config: %s", e)
            if self._cache is not None:
                logger.warning("Returning stale cached config due to DynamoDB error.")
                return self._cache
            return SystemConfig.default()

    def save_config(self, config: SystemConfig, updated_by: str = "system") -> bool:
        """
        Save configuration to DynamoDB and invalidate cache.
        Returns True on success, False on error.
        """
        from datetime import datetime
        config.updated_at = datetime.utcnow()
        config.updated_by = updated_by

        try:
            item = config.to_dynamodb_item()
            self._table.put_item(Item=item)
            self._invalidate_cache()
            logger.info("Config saved by %s", updated_by)
            self._write_audit_log(config, updated_by)
            return True
        except ClientError as e:
            logger.error("DynamoDB error saving config: %s", e)
            return False

    def _seed_defaults(self, config: SystemConfig) -> None:
        """Write default config to DynamoDB on first run."""
        try:
            self._table.put_item(Item=config.to_dynamodb_item())
            logger.info("Seeded default configuration to DynamoDB.")
        except ClientError as e:
            logger.error("Failed to seed default config: %s", e)

    def _write_audit_log(self, config: SystemConfig, updated_by: str) -> None:
        """Write audit entry to DynamoDB (best-effort)."""
        try:
            import time as _time
            audit_table = self._dynamodb.Table(self._table_name.replace("config", "logs"))
            audit_table.put_item(
                Item={
                    "log_id": f"audit-{int(_time.time() * 1000)}",
                    "log_type": "config_change",
                    "updated_by": updated_by,
                    "timestamp": config.updated_at.isoformat(),
                    "config_snapshot": json.dumps(config.to_dynamodb_item()),
                }
            )
        except Exception:
            pass  # Audit logging is best-effort; never block the main path

    def update_searchable_channels(
        self, channel_ids: list[str], updated_by: str = "system"
    ) -> bool:
        """Update the list of searchable Discord channel IDs."""
        config = self.load_config()
        config.searchable_channel_ids = channel_ids
        return self.save_config(config, updated_by=updated_by)

    def get_searchable_channels(self) -> list[str]:
        return self.load_config().searchable_channel_ids

    def reset_to_defaults(self, updated_by: str = "system") -> bool:
        """Reset configuration to factory defaults."""
        return self.save_config(SystemConfig.default(), updated_by=updated_by)
