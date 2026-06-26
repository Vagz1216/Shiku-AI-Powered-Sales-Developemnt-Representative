"""Organization-scoped LLM provider credentials.

Tenant BYOK secrets are write-only at the API boundary. The service stores
encrypted values and returns only operational metadata plus a non-reversible
fingerprint so admins can recognize a credential without exposing it.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from langfuse.openai import AsyncAzureOpenAI, AsyncOpenAI

from config.settings import settings
from services import tenant_service
from utils.db_connection import dict_from_row, get_conn, using_postgres

logger = logging.getLogger(__name__)

SUPPORTED_PROVIDERS = {"openai", "azure_openai", "gemini", "groq", "cerebras", "openrouter"}
ACTIVE_STATUSES = {"ACTIVE", "DISABLED"}


def _normalize_provider(value: str) -> str:
    provider = (value or "").strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError("unsupported LLM provider")
    return provider


def _normalize_label(value: str | None, provider: str) -> str:
    label = (value or provider.replace("_", " ").title()).strip()
    if not label:
        raise ValueError("credential label cannot be empty")
    return label[:120]


def _plan_for_organization(organization_id: int) -> dict[str, Any] | None:
    subscription = tenant_service.get_organization_subscription(organization_id)
    return subscription.get("plan") if subscription.get("is_active") else None


def get_byok_policy(organization_id: int) -> dict[str, Any]:
    plan = _plan_for_organization(organization_id)
    plan_allows = bool(plan and plan.get("allow_byok"))
    enabled = bool(settings.organization_llm_keys_enabled and plan_allows)
    mode = str(
        (plan or {}).get("byok_provider_mode")
        or settings.organization_llm_provider_mode
        or "platform_first"
    )
    if mode not in tenant_service.LLM_PROVIDER_MODES:
        mode = "platform_first"
    return {
        "enabled": enabled,
        "global_enabled": bool(settings.organization_llm_keys_enabled),
        "plan_allows_byok": plan_allows,
        "provider_mode": mode,
        "max_credentials": (plan or {}).get("max_llm_credentials"),
        "plan": plan,
        "supported_providers": sorted(SUPPORTED_PROVIDERS),
        "security_note": (
            "Provider keys are encrypted before storage and are never shown again. "
            "Only provider metadata and a short fingerprint are visible to admins."
        ),
    }


def _credential_payload(row: dict[str, Any]) -> dict[str, Any]:
    clean = dict(row)
    secret = clean.pop("api_key_secret", None)
    clean["api_key_fingerprint"] = tenant_service._secret_fingerprint(secret)
    clean["has_api_key"] = bool(secret)
    return clean


def list_credentials(organization_id: int, actor_claims: dict[str, Any]) -> dict[str, Any]:
    tenant_service.require_org_role(actor_claims, organization_id, tenant_service.ADMIN_ROLES)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM organization_llm_credentials WHERE organization_id = ? ORDER BY provider ASC, id ASC",
            (organization_id,),
        ).fetchall()
    return {
        "policy": get_byok_policy(organization_id),
        "credentials": [_credential_payload(dict_from_row(row)) for row in rows],
    }


def _validate_create_limit(organization_id: int) -> None:
    policy = get_byok_policy(organization_id)
    if not policy["global_enabled"]:
        raise PermissionError("organization LLM keys are disabled for this deployment")
    if not policy["plan_allows_byok"]:
        raise PermissionError("the current plan does not include organization-managed LLM keys")
    max_credentials = policy.get("max_credentials")
    if max_credentials is None:
        return
    with get_conn() as conn:
        count_row = conn.execute(
            "SELECT COUNT(*) AS count FROM organization_llm_credentials WHERE organization_id = ?",
            (organization_id,),
        ).fetchone()
    if int(dict_from_row(count_row).get("count") or 0) >= int(max_credentials):
        raise ValueError("this plan has reached its LLM credential limit")


def _provider_defaults(provider: str, data: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "base_url": (data.get("base_url") or "").strip() or None,
        "azure_endpoint": (data.get("azure_endpoint") or "").strip() or None,
        "azure_deployment": (data.get("azure_deployment") or "").strip() or None,
        "azure_api_version": (data.get("azure_api_version") or "").strip() or None,
        "default_model": (data.get("default_model") or "").strip() or None,
    }
    if provider == "azure_openai":
        if not fields["azure_endpoint"] or not fields["azure_deployment"]:
            raise ValueError("Azure OpenAI credentials require endpoint and deployment")
        fields["azure_api_version"] = fields["azure_api_version"] or settings.azure_openai_api_version
        fields["default_model"] = fields["default_model"] or fields["azure_deployment"]
    elif provider == "openai":
        fields["default_model"] = fields["default_model"] or settings.outreach_model
    elif provider == "gemini":
        fields["default_model"] = fields["default_model"] or settings.gemini_model
        fields["base_url"] = fields["base_url"] or "https://generativelanguage.googleapis.com/v1beta/openai/"
    elif provider == "groq":
        fields["default_model"] = fields["default_model"] or settings.groq_model
        fields["base_url"] = fields["base_url"] or "https://api.groq.com/openai/v1"
    elif provider == "cerebras":
        fields["default_model"] = fields["default_model"] or settings.cerebras_model
        fields["base_url"] = fields["base_url"] or "https://api.cerebras.ai/v1"
    elif provider == "openrouter":
        fields["default_model"] = fields["default_model"] or settings.openrouter_auto_model
        fields["base_url"] = fields["base_url"] or "https://openrouter.ai/api/v1"
    return fields


def _test_client(provider: str, api_key: str, fields: dict[str, Any]):
    if provider == "azure_openai":
        endpoint = fields.get("azure_endpoint")
        deployment = fields.get("azure_deployment") or fields.get("default_model")
        api_version = fields.get("azure_api_version") or settings.azure_openai_api_version
        if not endpoint or not deployment:
            raise ValueError("Azure OpenAI credentials require endpoint and deployment")
        return AsyncAzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            azure_deployment=deployment,
            api_version=api_version,
            max_retries=0,
            timeout=20.0,
        )
    return AsyncOpenAI(
        api_key=api_key,
        base_url=fields.get("base_url"),
        max_retries=0,
        timeout=20.0,
    )


def _friendly_test_error(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    lowered = message.lower()
    if "insufficient_quota" in lowered or "quota" in lowered or "billing" in lowered:
        return f"Provider quota/billing issue: {message}"
    if "invalid_api_key" in lowered or "authentication" in lowered or "unauthorized" in lowered:
        return f"Authentication failed: {message}"
    if "rate_limit" in lowered or "too many requests" in lowered:
        return f"Provider rate limit reached: {message}"
    if "model" in lowered and ("not found" in lowered or "does not exist" in lowered or "unsupported" in lowered):
        return f"Model is not available for this credential: {message}"
    return message


async def _run_provider_test(provider: str, model: str, api_key: str, fields: dict[str, Any]) -> dict[str, Any]:
    client = _test_client(provider, api_key, fields)
    started = time.perf_counter()
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You are validating API connectivity for a tenant LLM credential.",
                },
                {
                    "role": "user",
                    "content": "Reply with exactly OK.",
                },
            ],
            temperature=0,
            max_tokens=64,
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        text = ((response.choices or [{}])[0].message.content or "").strip() if response.choices else ""
        if not text:
            raise ValueError("provider returned an empty response during the test")
        return {
            "message": f"Credential test succeeded via {provider} model {model}.",
            "latency_ms": latency_ms,
            "sample": text[:120],
        }
    finally:
        close = getattr(client, "close", None)
        aclose = getattr(client, "aclose", None)
        if callable(aclose):
            await aclose()
        elif callable(close):
            maybe_awaitable = close()
            if hasattr(maybe_awaitable, "__await__"):
                await maybe_awaitable


def create_credential(
    organization_id: int,
    data: dict[str, Any],
    actor_claims: dict[str, Any],
) -> dict[str, Any]:
    actor_ctx = tenant_service.require_org_role(actor_claims, organization_id, tenant_service.ADMIN_ROLES)
    _validate_create_limit(organization_id)
    provider = _normalize_provider(str(data.get("provider") or ""))
    label = _normalize_label(data.get("label"), provider)
    api_key = str(data.get("api_key") or "").strip()
    if not api_key:
        raise ValueError("api key is required")
    fields = _provider_defaults(provider, data)
    now = tenant_service.now_iso()
    with get_conn() as conn:
        with conn:
            cur = conn.execute(
                "INSERT INTO organization_llm_credentials "
                "(organization_id, provider, label, status, api_key_secret, base_url, azure_endpoint, "
                "azure_deployment, azure_api_version, default_model, created_by_user_id, updated_at) "
                "VALUES (?, ?, ?, 'ACTIVE', ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    organization_id,
                    provider,
                    label,
                    tenant_service.encrypt_secret(api_key),
                    fields["base_url"],
                    fields["azure_endpoint"],
                    fields["azure_deployment"],
                    fields["azure_api_version"],
                    fields["default_model"],
                    actor_ctx["user"]["id"],
                    now,
                ),
            )
            credential_id = int(cur.lastrowid)
            conn.execute(
                "INSERT INTO events (organization_id, type, payload, metadata) VALUES (?, ?, ?, ?)",
                (
                    organization_id,
                    "organization_llm_credential_created",
                    json.dumps({"credential_id": credential_id, "provider": provider}),
                    json.dumps({"actor_user_id": actor_ctx["user"]["id"]}),
                ),
            )
    return get_credential(organization_id, credential_id, actor_claims)


def get_credential(
    organization_id: int,
    credential_id: int,
    actor_claims: dict[str, Any],
) -> dict[str, Any]:
    tenant_service.require_org_role(actor_claims, organization_id, tenant_service.ADMIN_ROLES)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM organization_llm_credentials WHERE organization_id = ? AND id = ?",
            (organization_id, credential_id),
        ).fetchone()
    credential = _credential_payload(dict_from_row(row))
    if not credential:
        raise ValueError("LLM credential not found")
    return credential


def update_credential(
    organization_id: int,
    credential_id: int,
    data: dict[str, Any],
    actor_claims: dict[str, Any],
) -> dict[str, Any]:
    actor_ctx = tenant_service.require_org_role(actor_claims, organization_id, tenant_service.ADMIN_ROLES)
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT * FROM organization_llm_credentials WHERE organization_id = ? AND id = ?",
            (organization_id, credential_id),
        ).fetchone()
    existing_data = dict_from_row(existing)
    if not existing_data:
        raise ValueError("LLM credential not found")

    fields: dict[str, Any] = {}
    if "label" in data:
        fields["label"] = _normalize_label(data.get("label"), existing_data["provider"])
    if "status" in data:
        status = str(data.get("status") or "").upper()
        if status not in ACTIVE_STATUSES:
            raise ValueError("invalid LLM credential status")
        fields["status"] = status
    for key, value in _provider_defaults(existing_data["provider"], {**existing_data, **data}).items():
        if key in data:
            fields[key] = value
    if data.get("api_key"):
        fields["api_key_secret"] = tenant_service.encrypt_secret(str(data["api_key"]).strip())
    if not fields:
        return _credential_payload(existing_data)

    assignments = ", ".join(f"{field} = ?" for field in fields)
    params = [*fields.values(), tenant_service.now_iso(), organization_id, credential_id]
    with get_conn() as conn:
        with conn:
            conn.execute(
                f"UPDATE organization_llm_credentials SET {assignments}, updated_at = ? "
                "WHERE organization_id = ? AND id = ?",
                tuple(params),
            )
            conn.execute(
                "INSERT INTO events (organization_id, type, payload, metadata) VALUES (?, ?, ?, ?)",
                (
                    organization_id,
                    "organization_llm_credential_updated",
                    json.dumps({"credential_id": credential_id, "fields": sorted(fields)}),
                    json.dumps({"actor_user_id": actor_ctx["user"]["id"]}),
                ),
            )
    return get_credential(organization_id, credential_id, actor_claims)


def delete_credential(organization_id: int, credential_id: int, actor_claims: dict[str, Any]) -> None:
    actor_ctx = tenant_service.require_org_role(actor_claims, organization_id, tenant_service.ADMIN_ROLES)
    with get_conn() as conn:
        with conn:
            cur = conn.execute(
                "DELETE FROM organization_llm_credentials WHERE organization_id = ? AND id = ?",
                (organization_id, credential_id),
            )
            if cur.rowcount == 0:
                raise ValueError("LLM credential not found")
            conn.execute(
                "INSERT INTO events (organization_id, type, payload, metadata) VALUES (?, ?, ?, ?)",
                (
                    organization_id,
                    "organization_llm_credential_deleted",
                    json.dumps({"credential_id": credential_id}),
                    json.dumps({"actor_user_id": actor_ctx["user"]["id"]}),
                ),
            )


async def test_credential(organization_id: int, credential_id: int, actor_claims: dict[str, Any]) -> dict[str, Any]:
    actor_ctx = tenant_service.require_org_role(actor_claims, organization_id, tenant_service.ADMIN_ROLES)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM organization_llm_credentials WHERE organization_id = ? AND id = ?",
            (organization_id, credential_id),
        ).fetchone()
    credential = dict_from_row(row)
    if not credential:
        raise ValueError("LLM credential not found")

    provider = _normalize_provider(str(credential.get("provider") or ""))
    fields = _provider_defaults(provider, credential)
    api_key_secret = credential.get("api_key_secret")
    if not api_key_secret:
        raise ValueError("LLM credential is missing its encrypted API key")

    now = tenant_service.now_iso()
    try:
        api_key = tenant_service.decrypt_secret(api_key_secret)
        result = await _run_provider_test(provider, fields["default_model"], api_key, fields)
        last_error = None
        status = "passed"
        message = result["message"]
    except Exception as exc:
        logger.warning("LLM credential test failed for org %s credential %s: %s", organization_id, credential_id, exc)
        result = {"latency_ms": None, "sample": None}
        last_error = _friendly_test_error(exc)
        status = "failed"
        message = f"Credential test failed: {last_error}"

    with get_conn() as conn:
        with conn:
            conn.execute(
                "UPDATE organization_llm_credentials SET last_tested_at = ?, last_error = ?, updated_at = ? "
                "WHERE organization_id = ? AND id = ?",
                (now, last_error, now, organization_id, credential_id),
            )
            conn.execute(
                "INSERT INTO events (organization_id, type, payload, metadata) VALUES (?, ?, ?, ?)",
                (
                    organization_id,
                    "organization_llm_credential_tested",
                    json.dumps(
                        {
                            "credential_id": credential_id,
                            "provider": provider,
                            "status": status,
                            "message": message,
                            "latency_ms": result.get("latency_ms"),
                        }
                    ),
                    json.dumps({"actor_user_id": actor_ctx["user"]["id"]}),
                ),
            )

    return {
        "status": status,
        "message": message,
        "latency_ms": result.get("latency_ms"),
        "sample": result.get("sample"),
        "credential": get_credential(organization_id, credential_id, actor_claims),
    }


def list_active_provider_credentials(organization_id: int | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not organization_id:
        return [], {"enabled": False, "provider_mode": settings.organization_llm_provider_mode}
    policy = get_byok_policy(int(organization_id))
    if not policy["enabled"]:
        return [], policy
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM organization_llm_credentials "
            "WHERE organization_id = ? AND status = 'ACTIVE' ORDER BY provider ASC, id ASC",
            (organization_id,),
        ).fetchall()
    credentials = []
    for row in rows:
        data = dict_from_row(row)
        try:
            data["api_key"] = tenant_service.decrypt_secret(data.pop("api_key_secret"))
        except Exception as exc:
            logger.warning("Could not decrypt organization LLM credential %s: %s", data.get("id"), exc)
            continue
        credentials.append(data)
    return credentials, policy
