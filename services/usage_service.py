"""LLM usage ledger and estimated cost helpers."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from config import settings
from utils.db_connection import dict_from_row, get_conn, sql_group_concat_distinct

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0
    request_count: int = 0


@dataclass(frozen=True)
class Price:
    input_usd_per_1m: float = 0.0
    cached_input_usd_per_1m: float = 0.0
    output_usd_per_1m: float = 0.0
    source: str | None = None


def _get_int(obj: Any, attr: str, default: int = 0) -> int:
    value = getattr(obj, attr, default)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _usage_from_obj(usage: Any) -> TokenUsage:
    input_details = getattr(usage, "input_tokens_details", None)
    output_details = getattr(usage, "output_tokens_details", None)
    return TokenUsage(
        input_tokens=_get_int(usage, "input_tokens"),
        output_tokens=_get_int(usage, "output_tokens"),
        cached_input_tokens=_get_int(input_details, "cached_tokens"),
        reasoning_output_tokens=_get_int(output_details, "reasoning_tokens"),
        total_tokens=_get_int(usage, "total_tokens"),
        request_count=_get_int(usage, "requests", 1),
    )


def extract_usage(result: Any) -> TokenUsage:
    """Extract aggregate token usage from an OpenAI Agents SDK run result."""
    totals = TokenUsage()
    raw_responses = getattr(result, "raw_responses", None) or []

    usages = [getattr(response, "usage", None) for response in raw_responses]
    usages = [usage for usage in usages if usage is not None]
    if not usages:
        context_wrapper = getattr(result, "context_wrapper", None)
        context_usage = getattr(context_wrapper, "usage", None)
        if context_usage is not None:
            usages = [context_usage]

    for usage in usages:
        current = _usage_from_obj(usage)
        totals = TokenUsage(
            input_tokens=totals.input_tokens + current.input_tokens,
            output_tokens=totals.output_tokens + current.output_tokens,
            cached_input_tokens=totals.cached_input_tokens + current.cached_input_tokens,
            reasoning_output_tokens=totals.reasoning_output_tokens + current.reasoning_output_tokens,
            total_tokens=totals.total_tokens + current.total_tokens,
            request_count=totals.request_count + current.request_count,
        )

    return totals


def count_tool_calls(result: Any) -> int:
    count = 0
    for item in getattr(result, "new_items", None) or []:
        if type(item).__name__ == "ToolCallItem":
            count += 1
    return count


def _pricing_path() -> str:
    path = settings.llm_pricing_file
    if os.path.isabs(path):
        return path
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), path)


@lru_cache(maxsize=1)
def load_pricing() -> dict[str, Any]:
    path = _pricing_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("LLM pricing file not found: %s", path)
    except json.JSONDecodeError as e:
        logger.warning("LLM pricing file is invalid JSON: %s", e)
    return {"models": []}


def pricing_version() -> str | None:
    value = load_pricing().get("version")
    return str(value) if value else None


def _provider_family(provider: str) -> str:
    if provider.startswith("Org"):
        provider = provider.removeprefix("Org")
    if provider.startswith("Groq"):
        return "Groq"
    if provider.startswith("Cerebras"):
        return "Cerebras"
    if provider == "OpenRouter":
        return "OpenRouter-Auto"
    return provider


def find_price(provider: str, model: str) -> Price:
    provider_family = _provider_family(provider)
    model_lower = model.lower()
    best: dict[str, Any] | None = None

    for entry in load_pricing().get("models", []):
        entry_provider = str(entry.get("provider", ""))
        entry_model = str(entry.get("model", "")).lower()
        if entry_provider == provider_family and entry_model == model_lower:
            best = entry
            break
        if entry_provider == provider_family and entry_model and entry_model in model_lower:
            best = entry

    if not best:
        return Price(source="unpriced")

    return Price(
        input_usd_per_1m=float(best.get("input_usd_per_1m") or 0),
        cached_input_usd_per_1m=float(best.get("cached_input_usd_per_1m") or 0),
        output_usd_per_1m=float(best.get("output_usd_per_1m") or 0),
        source=str(best.get("source") or "configured"),
    )


def estimate_cost(provider: str, model: str, usage: TokenUsage) -> tuple[float, str | None]:
    price = find_price(provider, model)
    uncached_input_tokens = max(usage.input_tokens - usage.cached_input_tokens, 0)
    cost = (
        (uncached_input_tokens / 1_000_000) * price.input_usd_per_1m
        + (usage.cached_input_tokens / 1_000_000) * price.cached_input_usd_per_1m
        + (usage.output_tokens / 1_000_000) * price.output_usd_per_1m
    )
    return round(cost, 8), price.source


def record_llm_usage(
    *,
    organization_id: int | None = None,
    user_id: int | None = None,
    ai_usage_action_id: int | None = None,
    request_id: str | None,
    agent_name: str,
    provider: str,
    model: str,
    usage: TokenUsage,
    latency_ms: float,
    fallback_triggered: bool,
    attempt_count: int,
    tool_call_count: int,
    routing_mode: str | None = None,
    billing_source: str = "platform",
    provider_credential_id: int | None = None,
    status: str = "success",
    error: str | None = None,
) -> dict[str, Any]:
    estimated_cost_usd, pricing_source = estimate_cost(provider, model, usage)
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO llm_usage_events ("
            "organization_id, user_id, ai_usage_action_id, request_id, agent_name, provider, model, input_tokens, output_tokens, "
            "cached_input_tokens, reasoning_output_tokens, total_tokens, request_count, "
            "latency_ms, estimated_cost_usd, pricing_source, pricing_version, routing_mode, fallback_triggered, "
            "billing_source, provider_credential_id, attempt_count, tool_call_count, status, error"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                organization_id or 1,
                user_id,
                ai_usage_action_id,
                request_id,
                agent_name,
                provider,
                model,
                usage.input_tokens,
                usage.output_tokens,
                usage.cached_input_tokens,
                usage.reasoning_output_tokens,
                usage.total_tokens,
                usage.request_count or 1,
                round(latency_ms, 2),
                estimated_cost_usd,
                pricing_source,
                pricing_version(),
                routing_mode,
                1 if fallback_triggered else 0,
                billing_source,
                provider_credential_id,
                attempt_count,
                tool_call_count,
                status,
                error,
            ),
        )
        usage_id = cur.lastrowid
    return {
        "usage_id": usage_id,
        "estimated_cost_usd": estimated_cost_usd,
        "pricing_source": pricing_source,
    }


def get_usage_summary(
    limit: int = 100,
    organization_id: int | None = None,
    routing_mode: str | None = None,
) -> dict[str, Any]:
    where_parts = []
    params_list: list[Any] = []
    if organization_id is not None:
        where_parts.append("organization_id = ?")
        params_list.append(organization_id)
    if routing_mode:
        where_parts.append("routing_mode = ?")
        params_list.append(routing_mode)
    where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    params: tuple[Any, ...] = tuple(params_list)
    with get_conn() as conn:
        total = dict_from_row(
            conn.execute(
                "SELECT "
                "COUNT(*) AS call_count, "
                "COALESCE(SUM(input_tokens), 0) AS input_tokens, "
                "COALESCE(SUM(output_tokens), 0) AS output_tokens, "
                "COALESCE(SUM(total_tokens), 0) AS total_tokens, "
                "COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd, "
                "COALESCE(SUM(CASE WHEN fallback_triggered = 1 THEN 1 ELSE 0 END), 0) AS fallback_count, "
                "COALESCE(SUM(CASE WHEN pricing_source = 'unpriced' THEN 1 ELSE 0 END), 0) AS unpriced_count, "
                "COALESCE(SUM(CASE WHEN estimated_cost_usd = 0 AND pricing_source != 'unpriced' THEN 1 ELSE 0 END), 0) AS zero_cost_priced_count, "
                "COALESCE(AVG(latency_ms), 0) AS avg_latency_ms "
                f"FROM llm_usage_events {where}",
                params,
            ).fetchone()
        ) or {}
        pricing_sources_sql = sql_group_concat_distinct("COALESCE(pricing_source, 'unknown')")
        by_model = [
            dict_from_row(row)
            for row in conn.execute(
                "SELECT provider, model, COUNT(*) AS call_count, "
                "COALESCE(SUM(input_tokens), 0) AS input_tokens, "
                "COALESCE(SUM(output_tokens), 0) AS output_tokens, "
                "COALESCE(SUM(total_tokens), 0) AS total_tokens, "
                "COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd, "
                "COALESCE(SUM(CASE WHEN pricing_source = 'unpriced' THEN 1 ELSE 0 END), 0) AS unpriced_count, "
                "COALESCE(SUM(CASE WHEN estimated_cost_usd = 0 AND pricing_source != 'unpriced' THEN 1 ELSE 0 END), 0) AS zero_cost_priced_count, "
                f"{pricing_sources_sql} AS pricing_sources, "
                "COALESCE(AVG(latency_ms), 0) AS avg_latency_ms "
                f"FROM llm_usage_events {where} GROUP BY provider, model "
                "ORDER BY estimated_cost_usd DESC, total_tokens DESC",
                params,
            ).fetchall()
        ]
        recent = [
            dict_from_row(row)
            for row in conn.execute(
                "SELECT id, request_id, agent_name, provider, model, routing_mode, input_tokens, output_tokens, "
                "total_tokens, latency_ms, estimated_cost_usd, fallback_triggered, "
                "pricing_source, billing_source, provider_credential_id, attempt_count, tool_call_count, status, created_at "
                f"FROM llm_usage_events {where} ORDER BY id DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
        ]
    return {"total": total, "by_model": by_model, "recent": recent}
