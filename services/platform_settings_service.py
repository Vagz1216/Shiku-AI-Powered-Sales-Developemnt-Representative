"""Platform-owner runtime settings."""

from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Literal

from config import settings
from utils.db_connection import dict_from_row, get_conn
from services import tenant_service

LLMRoutingMode = Literal["quality_first", "balanced", "cost_optimized"]

_LLM_ROUTING_KEY = "llm_routing_mode"
_CACHE_TTL_SECONDS = 30
_cache: dict[str, Any] = {"expires_at": 0.0, "settings": None}
_VALID_LLM_ROUTING_MODES = {"quality_first", "balanced", "cost_optimized"}
_routing_mode_override: ContextVar[str | None] = ContextVar("llm_routing_mode_override", default=None)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_platform_settings_table() -> None:
    with get_conn() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS platform_settings ("
            "key TEXT PRIMARY KEY, "
            "value TEXT NOT NULL, "
            "updated_by_user_id INTEGER, "
            "updated_at TEXT NOT NULL"
            ")"
        )


def clear_cache() -> None:
    _cache["expires_at"] = 0.0
    _cache["settings"] = None


def _load_settings() -> dict[str, str]:
    if _cache["settings"] is not None and time.time() < float(_cache["expires_at"]):
        return dict(_cache["settings"])

    _ensure_platform_settings_table()
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM platform_settings").fetchall()
    loaded = {str(row["key"]): str(row["value"]) for row in rows}
    _cache["settings"] = loaded
    _cache["expires_at"] = time.time() + _CACHE_TTL_SECONDS
    return dict(loaded)


def get_llm_routing_mode() -> LLMRoutingMode:
    """Return the active LLM routing mode.

    The database override lets a system owner switch routing without redeploying.
    If the DB is unavailable or the override is invalid, fall back to the
    validated environment setting so LLM calls do not fail just because the
    settings table is temporarily unreachable.
    """
    override = _routing_mode_override.get()
    if override in _VALID_LLM_ROUTING_MODES:
        return override  # type: ignore[return-value]
    try:
        value = _load_settings().get(_LLM_ROUTING_KEY)
    except Exception:
        value = None
    mode = value or settings.llm_routing_mode
    if mode not in _VALID_LLM_ROUTING_MODES:
        return settings.llm_routing_mode
    return mode  # type: ignore[return-value]


def get_effective_llm_routing_policy(organization_id: int | None = None) -> dict[str, Any]:
    requested = _routing_mode_override.get()
    global_mode = get_llm_routing_mode()
    if organization_id is None:
        requested = requested or global_mode
        return {
            "requested_mode": requested,
            "default_mode": requested,
            "resolved_mode": requested,
            "allowed_modes": sorted(_VALID_LLM_ROUTING_MODES),
            "plan_id": None,
            "plan_name": None,
            "plan_slug": None,
            "plan_currency_code": None,
            "plan_market_code": None,
            "plan_allow_byok": None,
            "plan_byok_provider_mode": None,
            "subscription_status": None,
            "downgraded": False,
        }
    try:
        return tenant_service.resolve_allowed_llm_routing_mode(
            organization_id,
            requested,
            fallback_mode=global_mode,
        )
    except Exception:
        requested = requested or global_mode
        return {
            "requested_mode": requested,
            "default_mode": requested,
            "resolved_mode": requested,
            "allowed_modes": sorted(_VALID_LLM_ROUTING_MODES),
            "plan_slug": None,
            "subscription_status": None,
            "downgraded": False,
        }


@contextmanager
def llm_routing_mode_context(mode: str | None):
    """Temporarily override routing mode for a campaign/workflow."""
    if mode not in _VALID_LLM_ROUTING_MODES:
        yield
        return
    token = _routing_mode_override.set(mode)
    try:
        yield
    finally:
        _routing_mode_override.reset(token)


def get_platform_runtime_settings(actor_claims: dict[str, Any]) -> dict[str, Any]:
    actor = tenant_service.require_system_owner(actor_claims)
    mode = get_llm_routing_mode()
    return {
        "llm_routing_mode": mode,
        "llm_routing_env_default": settings.llm_routing_mode,
        "allowed_llm_routing_modes": sorted(_VALID_LLM_ROUTING_MODES),
        "organization_llm_keys_enabled": settings.organization_llm_keys_enabled,
        "organization_llm_provider_mode": settings.organization_llm_provider_mode,
        "updated_by_user_id": actor.get("id"),
    }


def update_llm_routing_mode(mode: str, actor_claims: dict[str, Any]) -> dict[str, Any]:
    if mode not in _VALID_LLM_ROUTING_MODES:
        raise ValueError(f"invalid LLM routing mode: {mode}")
    actor = tenant_service.require_system_owner(actor_claims)
    _ensure_platform_settings_table()
    now = _now_iso()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO platform_settings (key, value, updated_by_user_id, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET "
            "value = excluded.value, "
            "updated_by_user_id = excluded.updated_by_user_id, "
            "updated_at = excluded.updated_at",
            (_LLM_ROUTING_KEY, mode, actor.get("id"), now),
        )
    clear_cache()
    return get_platform_runtime_settings(actor_claims)
