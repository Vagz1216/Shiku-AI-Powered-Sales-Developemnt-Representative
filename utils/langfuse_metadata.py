"""Small helpers for enriching Langfuse observations without coupling callers to SDK details."""

from __future__ import annotations

import logging
from typing import Any

from config.settings import settings

logger = logging.getLogger(__name__)


def trace_metadata_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, bool, int, float)):
        return str(value)
    if isinstance(value, (list, tuple, set)):
        return ", ".join(trace_metadata_value(item) for item in value)
    return str(value)


def trace_metadata(values: dict[str, Any]) -> dict[str, str]:
    return {key: trace_metadata_value(value) for key, value in values.items()}


def update_current_span_metadata(values: dict[str, Any]) -> None:
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return
    try:
        from langfuse import get_client

        get_client().update_current_span(metadata=trace_metadata(values))
    except Exception as exc:
        logger.debug("Failed to update Langfuse span metadata: %s", exc)
