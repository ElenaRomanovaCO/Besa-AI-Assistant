"""
Lambda handler for admin REST API endpoints.

Endpoints:
  GET  /api/configuration         — fetch system config
  PUT  /api/configuration         — update system config
  POST /api/faq/upload            — upload FAQ file (returns presigned URL or processes directly)
  GET  /api/faq/sync-status       — check Bedrock KB sync status
  GET  /api/faq/entries           — list FAQ entries (from S3)
  GET  /api/discord/channels      — list guild channels
  GET  /api/logs/queries          — paginated query log
  GET  /api/analytics/overview    — analytics summary
  POST /api/rate-limits/reset     — reset rate limit for a user (Admin only)
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Any

import boto3

from backend.services.config_service import ConfigService
from backend.services.discord_service import DiscordService
from backend.services.faq_ingestion import FAQIngestionService
from backend.services.rate_limiter import RateLimiter
from backend.models.config_models import SystemConfig

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_CONFIG_TABLE = os.environ.get("CONFIG_TABLE_NAME", "")
_LOGS_TABLE = os.environ.get("LOGS_TABLE_NAME", "")
_RATE_LIMIT_TABLE = os.environ.get("RATE_LIMIT_TABLE_NAME", "")
_FAQ_BUCKET = os.environ.get("FAQ_BUCKET_NAME", "")
_KNOWLEDGE_BASE_ID = os.environ.get("BEDROCK_KNOWLEDGE_BASE_ID", "")
_DATA_SOURCE_ID = os.environ.get("BEDROCK_DATA_SOURCE_ID", "")
_BOT_TOKEN_SECRET_ARN = os.environ.get("DISCORD_BOT_TOKEN_SECRET_ARN", "")
_PUBLIC_KEY_SECRET_ARN = os.environ.get("DISCORD_PUBLIC_KEY_SECRET_ARN", "")
_APPLICATION_ID = os.environ.get("DISCORD_APPLICATION_ID", "")
_GUILD_ID = os.environ.get("DISCORD_GUILD_ID", "")
_AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

_secrets_client = boto3.client("secretsmanager")
_dynamodb = boto3.resource("dynamodb", region_name=_AWS_REGION)

_config_service: ConfigService | None = None
_faq_service: FAQIngestionService | None = None
_rate_limiter: RateLimiter | None = None
_discord_service: DiscordService | None = None


def _get_config_service() -> ConfigService:
    global _config_service
    if _config_service is None:
        _config_service = ConfigService(_CONFIG_TABLE, region=_AWS_REGION)
    return _config_service


def _get_faq_service() -> FAQIngestionService:
    global _faq_service
    if _faq_service is None:
        _faq_service = FAQIngestionService(
            s3_bucket=_FAQ_BUCKET,
            knowledge_base_id=_KNOWLEDGE_BASE_ID,
            data_source_id=_DATA_SOURCE_ID,
            metadata_table_name=_CONFIG_TABLE,
            region=_AWS_REGION,
        )
    return _faq_service


def _get_discord_service() -> DiscordService:
    global _discord_service
    if _discord_service is None:
        bot_token = _secrets_client.get_secret_value(
            SecretId=_BOT_TOKEN_SECRET_ARN
        )["SecretString"]
        public_key = _secrets_client.get_secret_value(
            SecretId=_PUBLIC_KEY_SECRET_ARN
        )["SecretString"]
        _discord_service = DiscordService(
            bot_token=bot_token,
            application_id=_APPLICATION_ID,
            public_key=public_key,
        )
    return _discord_service


def _get_rate_limiter() -> RateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter(_RATE_LIMIT_TABLE, region=_AWS_REGION)
    return _rate_limiter


def _get_caller_user(event: dict) -> str:
    """Extract Cognito user ID from JWT claims (set by API Gateway authorizer)."""
    claims = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("claims", {})
    )
    return claims.get("sub") or claims.get("cognito:username", "unknown")


def _get_caller_role(event: dict) -> str:
    """Extract Cognito user role from custom claims."""
    claims = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("claims", {})
    )
    groups = claims.get("cognito:groups", "")
    if "Admin" in groups:
        return "Admin"
    return "User"


def _response(status: int, body: Any, headers: dict | None = None) -> dict:
    """Build API Gateway response."""
    default_headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": os.environ.get("ALLOWED_ORIGIN", "*"),
        "Access-Control-Allow-Headers": "Content-Type,Authorization",
    }
    if headers:
        default_headers.update(headers)
    return {
        "statusCode": status,
        "headers": default_headers,
        "body": json.dumps(body, default=str),
    }


def handler(event: dict, context: Any) -> dict:
    """Route API Gateway requests to appropriate handler functions."""
    method = event.get("httpMethod", "GET").upper()
    path = event.get("path", "/")
    logger.info("Admin API: %s %s", method, path)

    # Route table
    routes = {
        ("GET", "/api/configuration"): handle_get_config,
        ("PUT", "/api/configuration"): handle_put_config,
        ("POST", "/api/faq/upload"): handle_faq_upload,
        ("GET", "/api/faq/sync-status"): handle_faq_sync_status,
        ("GET", "/api/faq/entries"): handle_faq_entries,
        ("GET", "/api/discord/channels"): handle_discord_channels,
        ("GET", "/api/logs/queries"): handle_query_logs,
        ("GET", "/api/analytics/overview"): handle_analytics,
        ("POST", "/api/rate-limits/reset"): handle_rate_limit_reset,
    }

    handler_fn = routes.get((method, path))
    if not handler_fn:
        return _response(404, {"error": f"Route not found: {method} {path}"})

    try:
        return handler_fn(event)
    except Exception as e:
        logger.error("Handler error for %s %s: %s", method, path, e, exc_info=True)
        return _response(500, {"error": "Internal server error"})


def handle_get_config(event: dict) -> dict:
    """GET /api/configuration — return current system config."""
    config = _get_config_service().load_config()
    return _response(200, config.to_dynamodb_item())


def handle_put_config(event: dict) -> dict:
    """PUT /api/configuration — update system config."""
    caller = _get_caller_user(event)
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"error": "Invalid JSON body"})

    config_svc = _get_config_service()
    config = config_svc.load_config()

    # Update threshold fields
    if "faq_threshold" in body:
        val = float(body["faq_threshold"])
        if not 0.25 <= val <= 1.0:
            return _response(400, {"error": "faq_threshold must be 0.25–1.0"})
        config.thresholds.faq_similarity_threshold = val

    if "discord_threshold" in body:
        val = float(body["discord_threshold"])
        if not 0.25 <= val <= 1.0:
            return _response(400, {"error": "discord_threshold must be 0.25–1.0"})
        config.thresholds.discord_overlap_threshold = val

    if "query_expansion_depth" in body:
        val = int(body["query_expansion_depth"])
        if not 7 <= val <= 15:
            return _response(400, {"error": "query_expansion_depth must be 7–15"})
        config.thresholds.query_expansion_depth = val

    # Update agent toggles
    for agent_key in (
        "enable_faq_agent", "enable_discord_agent",
        "enable_reasoning_agent", "enable_aws_docs_agent", "enable_online_search_agent"
    ):
        if agent_key in body:
            setattr(config.agents, agent_key, bool(body[agent_key]))

    # Update rate limit
    if "max_queries_per_hour" in body:
        val = int(body["max_queries_per_hour"])
        if not 1 <= val <= 100:
            return _response(400, {"error": "max_queries_per_hour must be 1–100"})
        config.rate_limit.max_queries_per_hour = val

    # Update channel list
    if "searchable_channel_ids" in body:
        if not isinstance(body["searchable_channel_ids"], list):
            return _response(400, {"error": "searchable_channel_ids must be an array"})
        config.searchable_channel_ids = [str(c) for c in body["searchable_channel_ids"]]

    success = config_svc.save_config(config, updated_by=caller)
    if not success:
        return _response(500, {"error": "Failed to save configuration"})

    return _response(200, {"message": "Configuration updated", "config": config.to_dynamodb_item()})


def handle_faq_upload(event: dict) -> dict:
    """POST /api/faq/upload — upload a FAQ file and trigger Bedrock KB sync."""
    caller = _get_caller_user(event)
    body_raw = event.get("body", "")
    is_base64 = event.get("isBase64Encoded", False)

    if is_base64:
        file_content = base64.b64decode(body_raw)
    else:
        file_content = body_raw.encode("utf-8")

    # Get file format from query parameters or Content-Type header
    params = event.get("queryStringParameters") or {}
    file_format = params.get("format", "")
    if not file_format:
        content_type = event.get("headers", {}).get("content-type", "")
        format_map = {
            "text/csv": "csv",
            "application/json": "json",
            "text/markdown": "md",
        }
        file_format = format_map.get(content_type, "json")

    result = _get_faq_service().upload_and_sync(
        file_content=file_content,
        file_format=file_format,
        uploaded_by=caller,
    )

    if result.success:
        return _response(200, {
            "message": "FAQ uploaded and sync started",
            "entry_count": result.entry_count,
            "sync_job_id": result.sync_job_id,
            "status": result.status.value,
        })
    return _response(422, {
        "error": result.error_message or "FAQ upload failed",
        "entry_count": result.entry_count,
    })


def handle_faq_sync_status(event: dict) -> dict:
    """GET /api/faq/sync-status — get current Bedrock KB sync status."""
    status = _get_faq_service().get_sync_status()
    return _response(200, status)


def handle_faq_entries(event: dict) -> dict:
    """GET /api/faq/entries — list FAQ entries from S3 (metadata only)."""
    s3 = boto3.client("s3", region_name=_AWS_REGION)
    try:
        response = s3.list_objects_v2(Bucket=_FAQ_BUCKET, Prefix="faq/")
        entries = []
        for obj in response.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".md"):
                entries.append({
                    "id": key.replace("faq/", "").replace(".md", ""),
                    "s3_key": key,
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"].isoformat(),
                })
        return _response(200, {"entries": entries, "total": len(entries)})
    except Exception as e:
        logger.error("Failed to list FAQ entries: %s", e)
        return _response(500, {"error": "Failed to list FAQ entries"})


def handle_discord_channels(event: dict) -> dict:
    """GET /api/discord/channels — list guild channels with selection status."""
    if not _GUILD_ID:
        return _response(400, {"error": "GUILD_ID not configured"})

    config = _get_config_service().load_config()
    selected_ids = set(config.searchable_channel_ids)

    channels = _get_discord_service().get_guild_channels(_GUILD_ID)
    return _response(200, {
        "channels": [
            {
                "channel_id": ch.channel_id,
                "name": ch.name,
                "type": ch.channel_type,
                "topic": ch.topic,
                "is_selected": ch.channel_id in selected_ids,
            }
            for ch in channels
        ]
    })


def handle_query_logs(event: dict) -> dict:
    """GET /api/logs/queries — paginated query log with filters."""
    params = event.get("queryStringParameters") or {}
    limit = min(int(params.get("limit", 50)), 200)

    table = _dynamodb.Table(_LOGS_TABLE)
    try:
        response = table.scan(
            FilterExpression=boto3.dynamodb.conditions.Attr("log_type").eq("query"),
            Limit=limit,
        )
        items = response.get("Items", [])
        # Sort by timestamp descending
        items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        return _response(200, {
            "items": items,
            "count": len(items),
            "last_evaluated_key": response.get("LastEvaluatedKey"),
        })
    except Exception as e:
        logger.error("Failed to fetch query logs: %s", e)
        return _response(500, {"error": "Failed to fetch logs"})


def handle_analytics(event: dict) -> dict:
    """GET /api/analytics/overview — aggregated analytics stats."""
    table = _dynamodb.Table(_LOGS_TABLE)
    try:
        response = table.scan(
            FilterExpression=boto3.dynamodb.conditions.Attr("log_type").eq("query"),
        )
        items = response.get("Items", [])

        total = len(items)
        source_dist: dict[str, int] = {}
        total_time = 0
        for item in items:
            source = item.get("source", "Unknown")
            source_dist[source] = source_dist.get(source, 0) + 1
            total_time += int(item.get("response_time_ms", 0))

        avg_time = total_time // total if total > 0 else 0

        return _response(200, {
            "total_questions": total,
            "source_distribution": source_dist,
            "avg_response_time_ms": avg_time,
        })
    except Exception as e:
        logger.error("Failed to compute analytics: %s", e)
        return _response(500, {"error": "Failed to compute analytics"})


def handle_rate_limit_reset(event: dict) -> dict:
    """POST /api/rate-limits/reset — reset rate limit for a user (Admin only)."""
    if _get_caller_role(event) != "Admin":
        return _response(403, {"error": "Admin role required to reset rate limits"})

    try:
        body = json.loads(event.get("body") or "{}")
        user_id = body.get("user_id", "")
    except json.JSONDecodeError:
        return _response(400, {"error": "Invalid JSON"})

    if not user_id:
        return _response(400, {"error": "user_id is required"})

    success = _get_rate_limiter().reset_user(user_id)
    if success:
        return _response(200, {"message": f"Rate limit reset for user {user_id}"})
    return _response(500, {"error": "Failed to reset rate limit"})
