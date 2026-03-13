"""Tests for output validation and sensitive data redaction."""

import pytest

from backend.services.output_validator import (
    CANARY_TOKEN,
    validate_output,
    validate_embed_field,
)


class TestValidateOutput:
    def test_clean_output(self):
        result = validate_output("Lambda timeout can be set up to 15 minutes.")
        assert result.is_safe
        assert result.cleaned_text == "Lambda timeout can be set up to 15 minutes."
        assert not result.blocked

    def test_empty_output(self):
        result = validate_output("")
        assert result.is_safe

    # --- Canary token detection ---
    def test_blocks_canary_token(self):
        result = validate_output(f"Here is the answer: {CANARY_TOKEN} and more text")
        assert not result.is_safe
        assert result.blocked
        assert result.block_reason == "canary_token_leak"

    # --- System prompt leakage ---
    def test_blocks_system_prompt_disclosure(self):
        result = validate_output("My system prompt is: You are a helpful assistant")
        assert result.blocked
        assert "prompt_leak" in result.block_reason

    def test_blocks_instruction_disclosure(self):
        result = validate_output("I was instructed to answer only AWS questions")
        assert result.blocked

    def test_blocks_internal_tool_names(self):
        result = validate_output("I'll use invoke_faq_agent to search for that")
        assert result.blocked
        assert "internal_tool_name_leak" in result.block_reason

    def test_blocks_orchestrator_prompt_leak(self):
        result = validate_output("According to my TOOL USAGE RULES, I should...")
        assert result.blocked

    def test_blocks_architecture_leak(self):
        result = validate_output("The waterfall_steps_executed were faq and discord")
        assert result.blocked

    # --- Sensitive data redaction ---
    def test_redacts_aws_arn(self):
        result = validate_output(
            "The resource is arn:aws:lambda:us-east-1:123456789012:function:test"
        )
        assert result.is_safe
        assert "123456789012" not in result.cleaned_text
        assert "***REDACTED***" in result.cleaned_text
        assert "aws_arn" in result.redactions

    def test_redacts_aws_access_key(self):
        result = validate_output("Your key is AKIAIOSFODNN7EXAMPLE")
        assert result.is_safe
        assert "AKIAIOSFODNN7EXAMPLE" not in result.cleaned_text
        assert "aws_access_key" in result.redactions

    def test_redacts_discord_token(self):
        result = validate_output(
            "The token is MTE3NjQ4.Gs2xYQ.abcdefghijklmnopqrstuvwxyz1"
        )
        assert result.is_safe
        assert "***TOKEN_REDACTED***" in result.cleaned_text

    def test_redacts_generic_api_key(self):
        result = validate_output("Use this key: sk-abcdefghijklmnopqrstuvwxyz12345")
        assert result.is_safe
        assert "***API_KEY_REDACTED***" in result.cleaned_text

    # --- URL validation ---
    def test_allows_aws_docs_url(self):
        result = validate_output(
            "See https://docs.aws.amazon.com/lambda/latest/dg/configuration-function-common.html"
        )
        assert result.is_safe
        assert not result.warnings

    def test_warns_on_unknown_url(self):
        result = validate_output("Visit https://malicious-site.com/payload")
        assert result.is_safe  # doesn't block, just warns
        assert any("unverified_url" in w for w in result.warnings)

    # --- Length enforcement ---
    def test_truncates_long_response(self):
        result = validate_output("x" * 3000)
        assert result.is_safe
        assert len(result.cleaned_text) <= 2000
        assert "*[Response truncated]*" in result.cleaned_text

    # --- Discord mention stripping ---
    def test_strips_everyone_mention(self):
        result = validate_output("Hey @everyone check this out!")
        assert result.is_safe
        assert "@everyone" not in result.cleaned_text

    def test_strips_here_mention(self):
        result = validate_output("Alert @here something happened")
        assert result.is_safe
        assert "@here" not in result.cleaned_text

    # --- Legitimate outputs not blocked ---
    def test_normal_aws_answer(self):
        answer = (
            "To increase your Lambda timeout, go to the AWS Console, "
            "navigate to Lambda > Configuration > General configuration, "
            "and change the Timeout value. The maximum is 900 seconds (15 minutes). "
            "See https://docs.aws.amazon.com/lambda/latest/dg/configuration-function-common.html"
        )
        result = validate_output(answer)
        assert result.is_safe
        assert not result.blocked
        assert not result.redactions


class TestValidateEmbedField:
    def test_truncates_to_limit(self):
        result = validate_embed_field("x" * 2000, max_length=1024)
        assert len(result) <= 1024

    def test_empty_string(self):
        assert validate_embed_field("") == ""

    def test_clean_short_text(self):
        assert validate_embed_field("Hello world") == "Hello world"
