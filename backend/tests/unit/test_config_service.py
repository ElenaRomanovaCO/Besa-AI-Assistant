"""Unit tests for ConfigService with mocked DynamoDB."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from backend.models.config_models import SystemConfig, ThresholdConfig
from backend.services.config_service import ConfigService


class TestConfigService:
    def test_load_config_returns_default_when_empty(self, dynamodb_tables):
        """When DynamoDB has no config, should return defaults and seed them."""
        svc = ConfigService("besa-ai-assistant-config")
        config = svc.load_config()

        assert config.thresholds.faq_similarity_threshold == 0.75
        assert config.thresholds.discord_overlap_threshold == 0.70
        assert config.thresholds.query_expansion_depth == 10
        assert config.agents.enable_reasoning_agent is True

    def test_load_config_seeds_defaults_on_first_run(self, dynamodb_tables):
        """First load should write defaults to DynamoDB."""
        svc = ConfigService("besa-ai-assistant-config")
        svc.load_config()

        # Second load should read from DynamoDB
        svc2 = ConfigService("besa-ai-assistant-config")
        svc2._invalidate_cache()
        config2 = svc2.load_config()
        assert config2.thresholds.faq_similarity_threshold == 0.75

    def test_save_config_persists_changes(self, dynamodb_tables):
        """Saved config should be readable by a fresh service instance."""
        svc = ConfigService("besa-ai-assistant-config")
        config = svc.load_config()
        config.thresholds.faq_similarity_threshold = 0.90
        svc.save_config(config, updated_by="test-user")

        svc2 = ConfigService("besa-ai-assistant-config")
        loaded = svc2.load_config()
        assert loaded.thresholds.faq_similarity_threshold == 0.90

    def test_cache_returns_same_object_within_ttl(self, dynamodb_tables):
        """Second load within 5 minutes should return cached config."""
        svc = ConfigService("besa-ai-assistant-config")
        c1 = svc.load_config()
        c2 = svc.load_config()
        assert c1 is c2  # Same object from cache

    def test_cache_invalidated_after_save(self, dynamodb_tables):
        """Cache should be invalidated after a save operation."""
        svc = ConfigService("besa-ai-assistant-config")
        svc.load_config()  # Populate cache
        assert svc._cache is not None

        config = SystemConfig.default()
        config.thresholds.faq_similarity_threshold = 0.65
        svc.save_config(config)

        assert svc._cache is None  # Cache was invalidated

    def test_save_config_updates_updated_by(self, dynamodb_tables):
        """Saved config should record who made the change."""
        svc = ConfigService("besa-ai-assistant-config")
        config = svc.load_config()
        svc.save_config(config, updated_by="elena@test.com")

        svc2 = ConfigService("besa-ai-assistant-config")
        loaded = svc2.load_config()
        assert loaded.updated_by == "elena@test.com"

    def test_update_searchable_channels(self, dynamodb_tables):
        """update_searchable_channels should persist the channel list."""
        svc = ConfigService("besa-ai-assistant-config")
        result = svc.update_searchable_channels(["ch1", "ch2", "ch3"])
        assert result is True

        svc2 = ConfigService("besa-ai-assistant-config")
        channels = svc2.get_searchable_channels()
        assert set(channels) == {"ch1", "ch2", "ch3"}

    def test_reset_to_defaults(self, dynamodb_tables):
        """reset_to_defaults should overwrite custom config."""
        svc = ConfigService("besa-ai-assistant-config")
        config = svc.load_config()
        config.thresholds.faq_similarity_threshold = 0.95
        svc.save_config(config)

        svc.reset_to_defaults(updated_by="admin")
        svc._invalidate_cache()

        reset_config = svc.load_config()
        assert reset_config.thresholds.faq_similarity_threshold == 0.75


class TestSystemConfig:
    def test_to_dynamodb_item_roundtrip(self):
        """Serialization/deserialization roundtrip should preserve all fields."""
        config = SystemConfig.default()
        config.thresholds.faq_similarity_threshold = 0.85
        config.agents.enable_reasoning_agent = False
        config.searchable_channel_ids = ["ch1", "ch2"]

        item = config.to_dynamodb_item()
        restored = SystemConfig.from_dynamodb_item(item)

        assert restored.thresholds.faq_similarity_threshold == 0.85
        assert restored.agents.enable_reasoning_agent is False
        assert "ch1" in restored.searchable_channel_ids

    def test_threshold_config_validation_valid(self):
        """Valid thresholds should produce no errors."""
        tc = ThresholdConfig(
            faq_similarity_threshold=0.75,
            discord_overlap_threshold=0.70,
            query_expansion_depth=10,
        )
        errors = tc.validate()
        assert len(errors) == 0

    def test_threshold_config_validation_out_of_range(self):
        """Out-of-range thresholds should produce validation errors."""
        tc = ThresholdConfig(
            faq_similarity_threshold=1.5,  # Invalid
            discord_overlap_threshold=0.70,
            query_expansion_depth=20,  # Invalid
        )
        errors = tc.validate()
        assert len(errors) >= 2
