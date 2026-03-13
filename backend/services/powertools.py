"""Shared AWS Lambda Powertools configuration.

Provides pre-configured Logger, Tracer, and Metrics instances for use
across all Lambda handlers. Import from here instead of creating new instances.

Usage in handlers:
    from backend.services.powertools import logger, tracer, metrics
"""

from __future__ import annotations

try:
    from aws_lambda_powertools import Logger, Metrics, Tracer

    logger = Logger(service="besa-ai-assistant")
    tracer = Tracer(service="besa-ai-assistant")
    metrics = Metrics(namespace="BeSaAI", service="besa-ai-assistant")

    POWERTOOLS_AVAILABLE = True

except ImportError:
    # Fallback for local development / testing without powertools installed
    import logging

    logger = logging.getLogger("besa-ai-assistant")  # type: ignore[assignment]
    tracer = None  # type: ignore[assignment]
    metrics = None  # type: ignore[assignment]

    POWERTOOLS_AVAILABLE = False
