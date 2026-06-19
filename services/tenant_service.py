"""Organization, role, and mailbox-onboarding services."""

from __future__ import annotations

import base64
import datetime
import imaplib
import json
import logging
import re
import smtplib
import threading
import time
from copy import deepcopy
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cryptography.fernet import Fernet

from config.settings import settings
from utils.db_connection import dict_from_row, get_conn, using_postgres

logger = logging.getLogger(__name__)

ORG_ROLES = {"org_admin", "sales_manager", "sales_user", "viewer"}
ADMIN_ROLES = {"org_admin"}
MANAGER_ROLES = {"org_admin", "sales_manager"}
WORKFLOW_ROLES = {"org_admin", "sales_manager", "sales_user"}
READ_ROLES = {"org_admin", "sales_manager", "sales_user", "viewer"}
SUBSCRIPTION_ACTIVE_STATUSES = {"ACTIVE", "TRIALING"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SLUG_RE = re.compile(r"[^a-z0-9]+")
TIMEZONE_ALIASES = {
    "Africa/NIAROBI": "Africa/Nairobi",
    "Africa/Niarobi": "Africa/Nairobi",
    "africa/niarobi": "Africa/Nairobi",
    "africa/nairobi": "Africa/Nairobi",
}

_tenant_cache_lock = threading.Lock()
_app_user_cache: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}
_org_list_cache: dict[tuple[Any, ...], tuple[float, list[dict[str, Any]]]] = {}
_org_resolve_cache: dict[tuple[Any, ...], tuple[float, int]] = {}


def clear_tenant_caches() -> None:
    """Clear short-lived tenant caches after membership, organization, or plan writes."""
    with _tenant_cache_lock:
        _app_user_cache.clear()
        _org_list_cache.clear()
        _org_resolve_cache.clear()


def _cache_enabled() -> bool:
    return settings.tenant_cache_ttl_seconds > 0


def _cache_expiry() -> float:
    return time.time() + settings.tenant_cache_ttl_seconds


def _cache_namespace() -> int:
    return id(get_conn)


def _identity_cache_key(claims: dict[str, Any]) -> tuple[Any, ...]:
    identity = user_identity_from_claims(claims)
    return (
        _cache_namespace(),
        identity["clerk_user_id"],
        identity["email"],
        identity["name"],
    )


def _roles_cache_key(roles: set[str]) -> tuple[str, ...]:
    return tuple(sorted(roles))


def _get_cache(cache: dict[tuple[Any, ...], tuple[float, Any]], key: tuple[Any, ...]) -> Any | None:
    if not _cache_enabled():
        return None
    now = time.time()
    with _tenant_cache_lock:
        item = cache.get(key)
        if not item:
            return None
        expires_at, value = item
        if expires_at <= now:
            cache.pop(key, None)
            return None
        return deepcopy(value)


def _set_cache(cache: dict[tuple[Any, ...], tuple[float, Any]], key: tuple[Any, ...], value: Any) -> None:
    if not _cache_enabled():
        return
    with _tenant_cache_lock:
        cache[key] = (_cache_expiry(), deepcopy(value))


def now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


def future_iso(days: int) -> str:
    return (
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=days)
    ).isoformat().replace("+00:00", "Z")


def parse_iso(value: Any) -> datetime.datetime | None:
    if not value:
        return None
    if isinstance(value, datetime.datetime):
        return value if value.tzinfo else value.replace(tzinfo=datetime.UTC)
    try:
        parsed = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.UTC)


def _upsert_organization_user(conn, organization_id: int, user_id: int, role: str, status: str) -> None:
    if using_postgres():
        conn.execute(
            "INSERT INTO organization_users (organization_id, user_id, role, status) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT (organization_id, user_id) DO UPDATE SET "
            "role = excluded.role, status = excluded.status",
            (organization_id, user_id, role, status),
        )
        return
    conn.execute(
        "INSERT OR REPLACE INTO organization_users "
        "(organization_id, user_id, role, status) VALUES (?, ?, ?, ?)",
        (organization_id, user_id, role, status),
    )


def normalize_email(email: str | None) -> str:
    value = (email or "").strip().lower()
    if not EMAIL_RE.match(value):
        raise ValueError(f"invalid email: {email}")
    return value


def slugify(value: str) -> str:
    slug = SLUG_RE.sub("-", (value or "").strip().lower()).strip("-")
    if not slug:
        raise ValueError("organization slug cannot be empty")
    return slug[:80]


def normalize_timezone(timezone: str | None) -> str:
    raw = (timezone or "Africa/Nairobi").strip()
    value = TIMEZONE_ALIASES.get(raw, raw)
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"invalid timezone: {value}") from exc
    return value


def user_identity_from_claims(claims: dict[str, Any]) -> dict[str, str | None]:
    clerk_user_id = str(claims.get("sub") or claims.get("user_id") or "")
    if not clerk_user_id:
        raise ValueError("authenticated user is missing a Clerk subject")
    email = (
        claims.get("email")
        or claims.get("primary_email_address")
        or claims.get("email_address")
    )
    name = claims.get("name") or claims.get("full_name") or claims.get("username")
    return {
        "clerk_user_id": clerk_user_id,
        "email": str(email).lower() if email else None,
        "name": str(name) if name else None,
    }


def ensure_app_user(claims: dict[str, Any]) -> dict[str, Any]:
    """Upsert the authenticated platform user from Clerk claims."""
    identity = user_identity_from_claims(claims)
    cache_key = _identity_cache_key(claims)
    cached = _get_cache(_app_user_cache, cache_key)
    if cached:
        return cached
    owner_emails = settings.platform_owner_email_set
    platform_role = (
        "system_owner"
        if identity["email"] and identity["email"].lower() in owner_emails
        else "user"
    )
    with get_conn() as conn:
        with conn:
            row = conn.execute(
                "SELECT * FROM app_users WHERE clerk_user_id = ?",
                (identity["clerk_user_id"],),
            ).fetchone()
            if not row and identity["email"]:
                row = conn.execute(
                    "SELECT * FROM app_users WHERE lower(email) = lower(?)",
                    (identity["email"],),
                ).fetchone()
            if row:
                existing = dict_from_row(row)
                next_platform_role = (
                    "system_owner"
                    if existing.get("platform_role") == "system_owner" or platform_role == "system_owner"
                    else "user"
                )
                conn.execute(
                    "UPDATE app_users SET clerk_user_id = ?, email = COALESCE(?, email), name = COALESCE(?, name), "
                    "platform_role = ?, last_seen_at = ? WHERE id = ?",
                    (
                        identity["clerk_user_id"],
                        identity["email"],
                        identity["name"],
                        next_platform_role,
                        now_iso(),
                        existing["id"],
                    ),
                )
                user_id = existing["id"]
            else:
                cur = conn.execute(
                    "INSERT INTO app_users (clerk_user_id, email, name, platform_role, last_seen_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        identity["clerk_user_id"],
                        identity["email"],
                        identity["name"],
                        platform_role,
                        now_iso(),
                    ),
                )
                user_id = cur.lastrowid
        user = dict_from_row(conn.execute("SELECT * FROM app_users WHERE id = ?", (user_id,)).fetchone())
        _set_cache(_app_user_cache, cache_key, user)
        return user


def require_system_owner(claims: dict[str, Any]) -> dict[str, Any]:
    user = ensure_app_user(claims)
    if user.get("platform_role") != "system_owner":
        raise PermissionError("system owner access required")
    return user


def get_membership(user_id: int, organization_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT ou.*, o.name AS organization_name, o.slug AS organization_slug "
            "FROM organization_users ou "
            "JOIN organizations o ON o.id = ou.organization_id "
            "WHERE ou.user_id = ? AND ou.organization_id = ? AND ou.status = 'ACTIVE'",
            (user_id, organization_id),
        ).fetchone()
        return dict_from_row(row)


def require_org_role(claims: dict[str, Any], organization_id: int, allowed_roles: set[str]) -> dict[str, Any]:
    user = ensure_app_user(claims)
    if user.get("platform_role") == "system_owner":
        return {"user": user, "membership": None, "system_owner": True}
    membership = get_membership(int(user["id"]), organization_id)
    if not membership or membership.get("role") not in allowed_roles:
        raise PermissionError("organization access denied")
    return {"user": user, "membership": membership, "system_owner": False}


def resolve_organization_id(
    claims: dict[str, Any],
    requested_organization_id: int | None = None,
    allowed_roles: set[str] | None = None,
) -> int:
    """Resolve the active organization for a request and enforce membership."""
    allowed = allowed_roles or READ_ROLES
    cache_key = (
        *_identity_cache_key(claims),
        int(requested_organization_id) if requested_organization_id else None,
        _roles_cache_key(allowed),
    )
    cached = _get_cache(_org_resolve_cache, cache_key)
    if cached is not None:
        return int(cached)
    user = ensure_app_user(claims)
    if requested_organization_id:
        resolved = int(requested_organization_id)
        require_org_role(claims, resolved, allowed)
        _set_cache(_org_resolve_cache, cache_key, resolved)
        return resolved

    organizations = list_organizations(claims)
    if organizations:
        resolved = int(organizations[0]["id"])
        _set_cache(_org_resolve_cache, cache_key, resolved)
        return resolved

    if user.get("platform_role") == "system_owner":
        default_org = get_organization(1)
        resolved = int(default_org["id"])
        _set_cache(_org_resolve_cache, cache_key, resolved)
        return resolved
    raise PermissionError("organization access denied")


def role_capabilities(role: str) -> dict[str, bool]:
    """Return UI-friendly capability flags for an organization role."""
    normalized = role or "viewer"
    is_system_owner = normalized == "system_owner"
    is_admin = normalized == "org_admin" or is_system_owner
    is_manager = normalized in {"org_admin", "sales_manager"} or is_system_owner
    is_workflow = normalized in WORKFLOW_ROLES or is_system_owner
    return {
        "can_create_organizations": is_system_owner,
        "can_manage_subscription_plans": is_system_owner,
        "can_choose_subscription_plan": is_admin,
        "can_manage_organization": is_admin,
        "can_manage_users": is_admin,
        "can_manage_mailboxes": is_admin,
        "can_manage_staff": is_manager,
        "can_manage_campaigns": is_workflow,
        "can_manage_leads": is_workflow,
        "can_review_drafts": is_workflow,
        "can_run_outreach": is_workflow,
        "can_view_compliance": is_manager or is_system_owner,
    }


def _optional_positive_int(value: Any, field: str) -> int | None:
    if value in (None, ""):
        return None
    resolved = int(value)
    if resolved < 1:
        raise ValueError(f"{field} must be at least 1")
    return resolved


def _plan_input(data: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if "name" in data or not partial:
        name = str(data.get("name") or "").strip()
        if not name:
            raise ValueError("plan name cannot be empty")
        fields["name"] = name
    if "slug" in data or ("name" in fields and not partial):
        raw_slug = data.get("slug") or fields.get("name")
        if raw_slug is not None:
            fields["slug"] = slugify(str(raw_slug))
    if "description" in data:
        description = data.get("description")
        fields["description"] = str(description).strip() if description else None
    elif not partial:
        fields["description"] = None
    for key, default in (
        ("monthly_price_cents", 0),
        ("trial_days", 14),
    ):
        if key in data or not partial:
            value = default if data.get(key) is None else int(data.get(key))
            if value < 0:
                raise ValueError(f"{key} cannot be negative")
            fields[key] = value
    for key in (
        "max_users",
        "max_campaigns",
        "max_leads",
        "max_monthly_emails",
        "max_monthly_ai_tokens",
        "max_monthly_ai_credits",
    ):
        if key in data:
            fields[key] = _optional_positive_int(data.get(key), key)
        elif not partial:
            fields[key] = None
    if "overage_allowed" in data or not partial:
        fields["overage_allowed"] = 1 if data.get("overage_allowed", False) else 0
    if "overage_price_cents_per_ai_credit" in data:
        fields["overage_price_cents_per_ai_credit"] = _optional_positive_int(
            data.get("overage_price_cents_per_ai_credit"),
            "overage_price_cents_per_ai_credit",
        )
    elif not partial:
        fields["overage_price_cents_per_ai_credit"] = None
    if "active" in data or not partial:
        fields["active"] = 1 if data.get("active", True) else 0
    return fields


def sanitize_plan(plan: dict[str, Any] | None) -> dict[str, Any] | None:
    if not plan:
        return None
    clean = dict(plan)
    clean["active"] = bool(clean.get("active"))
    for key in (
        "monthly_price_cents",
        "trial_days",
        "max_users",
        "max_campaigns",
        "max_leads",
        "max_monthly_emails",
        "max_monthly_ai_tokens",
        "max_monthly_ai_credits",
        "overage_price_cents_per_ai_credit",
    ):
        clean[key] = int(clean[key]) if clean.get(key) is not None else None
    clean["overage_allowed"] = bool(clean.get("overage_allowed"))
    return clean


def create_subscription_plan(data: dict[str, Any], actor_claims: dict[str, Any]) -> dict[str, Any]:
    actor = require_system_owner(actor_claims)
    fields = _plan_input(data)
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM subscription_plans WHERE slug = ?",
            (fields["slug"],),
        ).fetchone()
        if existing:
            raise ValueError("a plan with that slug already exists")
        with conn:
            cur = conn.execute(
                "INSERT INTO subscription_plans "
                "(name, slug, description, monthly_price_cents, trial_days, max_users, max_campaigns, "
                "max_leads, max_monthly_emails, max_monthly_ai_tokens, max_monthly_ai_credits, "
                "overage_allowed, overage_price_cents_per_ai_credit, active, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    fields["name"],
                    fields["slug"],
                    fields["description"],
                    fields["monthly_price_cents"],
                    fields["trial_days"],
                    fields["max_users"],
                    fields["max_campaigns"],
                    fields["max_leads"],
                    fields["max_monthly_emails"],
                    fields["max_monthly_ai_tokens"],
                    fields["max_monthly_ai_credits"],
                    fields["overage_allowed"],
                    fields["overage_price_cents_per_ai_credit"],
                    fields["active"],
                    now_iso(),
                ),
            )
            plan_id = cur.lastrowid
            conn.execute(
                "INSERT INTO events (type, payload, metadata) VALUES (?, ?, ?)",
                (
                    "subscription_plan_created",
                    json.dumps({"plan_id": plan_id, "slug": fields["slug"]}),
                    json.dumps({"actor_user_id": actor["id"]}),
                ),
            )
    clear_tenant_caches()
    return get_subscription_plan(int(plan_id))


def update_subscription_plan(
    plan_id: int,
    data: dict[str, Any],
    actor_claims: dict[str, Any],
) -> dict[str, Any]:
    actor = require_system_owner(actor_claims)
    existing = get_subscription_plan(plan_id)
    fields = _plan_input(data, partial=True)
    if not fields:
        return existing
    if "slug" in fields and fields["slug"] != existing["slug"]:
        with get_conn() as conn:
            duplicate = conn.execute(
                "SELECT id FROM subscription_plans WHERE slug = ? AND id != ?",
                (fields["slug"], plan_id),
            ).fetchone()
            if duplicate:
                raise ValueError("a plan with that slug already exists")
    assignments = ", ".join(f"{field} = ?" for field in fields)
    params = [*fields.values(), now_iso(), plan_id]
    with get_conn() as conn:
        with conn:
            conn.execute(
                f"UPDATE subscription_plans SET {assignments}, updated_at = ? WHERE id = ?",
                tuple(params),
            )
            conn.execute(
                "INSERT INTO events (type, payload, metadata) VALUES (?, ?, ?)",
                (
                    "subscription_plan_updated",
                    json.dumps({"plan_id": plan_id, "fields": sorted(fields)}),
                    json.dumps({"actor_user_id": actor["id"]}),
                ),
            )
    clear_tenant_caches()
    return get_subscription_plan(plan_id)


def get_subscription_plan(plan_id: int) -> dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM subscription_plans WHERE id = ?", (plan_id,)).fetchone()
    plan = sanitize_plan(dict_from_row(row))
    if not plan:
        raise ValueError("subscription plan not found")
    return plan


def list_subscription_plans(actor_claims: dict[str, Any]) -> list[dict[str, Any]]:
    user = ensure_app_user(actor_claims)
    owner = user.get("platform_role") == "system_owner"
    with get_conn() as conn:
        if owner:
            rows = conn.execute("SELECT * FROM subscription_plans ORDER BY monthly_price_cents ASC, id ASC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM subscription_plans WHERE active = 1 ORDER BY monthly_price_cents ASC, id ASC"
            ).fetchall()
    return [sanitize_plan(dict_from_row(row)) for row in rows]


def _subscription_from_row(row: Any) -> dict[str, Any]:
    subscription = dict_from_row(row)
    if not subscription:
        return {
            "status": "NONE",
            "effective_status": "NONE",
            "is_active": False,
            "plan": None,
        }
    plan = sanitize_plan(
        {
            "id": subscription.pop("plan_id"),
            "name": subscription.pop("plan_name"),
            "slug": subscription.pop("plan_slug"),
            "description": subscription.pop("plan_description"),
            "monthly_price_cents": subscription.pop("plan_monthly_price_cents"),
            "trial_days": subscription.pop("plan_trial_days"),
            "max_users": subscription.pop("plan_max_users"),
            "max_campaigns": subscription.pop("plan_max_campaigns"),
            "max_leads": subscription.pop("plan_max_leads"),
            "max_monthly_emails": subscription.pop("plan_max_monthly_emails"),
            "max_monthly_ai_tokens": subscription.pop("plan_max_monthly_ai_tokens"),
            "max_monthly_ai_credits": subscription.pop("plan_max_monthly_ai_credits"),
            "overage_allowed": subscription.pop("plan_overage_allowed"),
            "overage_price_cents_per_ai_credit": subscription.pop("plan_overage_price_cents_per_ai_credit"),
            "active": subscription.pop("plan_active"),
            "created_at": subscription.pop("plan_created_at"),
            "updated_at": subscription.pop("plan_updated_at"),
        }
    )
    status = str(subscription.get("status") or "NONE").upper()
    effective_status = status
    if status == "TRIALING":
        trial_ends_at = parse_iso(subscription.get("trial_ends_at"))
        if trial_ends_at and trial_ends_at < datetime.datetime.now(datetime.UTC):
            effective_status = "EXPIRED"
    subscription["effective_status"] = effective_status
    subscription["is_active"] = effective_status in SUBSCRIPTION_ACTIVE_STATUSES
    subscription["plan"] = plan
    return subscription


def get_organization_subscription(organization_id: int) -> dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT s.*, "
            "p.name AS plan_name, p.slug AS plan_slug, p.description AS plan_description, "
            "p.monthly_price_cents AS plan_monthly_price_cents, p.trial_days AS plan_trial_days, "
            "p.max_users AS plan_max_users, p.max_campaigns AS plan_max_campaigns, p.max_leads AS plan_max_leads, "
            "p.max_monthly_emails AS plan_max_monthly_emails, p.max_monthly_ai_tokens AS plan_max_monthly_ai_tokens, "
            "p.max_monthly_ai_credits AS plan_max_monthly_ai_credits, p.overage_allowed AS plan_overage_allowed, "
            "p.overage_price_cents_per_ai_credit AS plan_overage_price_cents_per_ai_credit, "
            "p.active AS plan_active, p.created_at AS plan_created_at, p.updated_at AS plan_updated_at "
            "FROM organization_subscriptions s "
            "JOIN subscription_plans p ON p.id = s.plan_id "
            "WHERE s.organization_id = ?",
            (organization_id,),
        ).fetchone()
    return _subscription_from_row(row)


def organization_has_active_subscription(organization_id: int) -> bool:
    return bool(get_organization_subscription(organization_id).get("is_active"))


def require_active_subscription(organization_id: int) -> dict[str, Any]:
    subscription = get_organization_subscription(organization_id)
    if not subscription.get("is_active"):
        raise PermissionError("active subscription or trial required for this workflow")
    return subscription


def list_active_subscription_organization_ids() -> list[int]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT organization_id FROM organization_subscriptions "
            "WHERE status IN ('ACTIVE','TRIALING')"
        ).fetchall()
    active: list[int] = []
    for row in rows:
        org_id = int(dict_from_row(row)["organization_id"])
        if organization_has_active_subscription(org_id):
            active.append(org_id)
    return active


def select_organization_plan(
    organization_id: int,
    plan_id: int,
    actor_claims: dict[str, Any],
) -> dict[str, Any]:
    actor_ctx = require_org_role(actor_claims, organization_id, ADMIN_ROLES)
    plan = get_subscription_plan(plan_id)
    if not plan.get("active"):
        raise ValueError("inactive plans cannot be selected")

    trial_days = int(plan.get("trial_days") or 0)
    started_at = now_iso()
    trial_ends_at = future_iso(trial_days) if trial_days else None
    status = "TRIALING" if trial_days else "ACTIVE"
    current_period_ends_at = trial_ends_at or future_iso(30)

    with get_conn() as conn:
        with conn:
            existing = conn.execute(
                "SELECT id FROM organization_subscriptions WHERE organization_id = ?",
                (organization_id,),
            ).fetchone()
            if existing:
                subscription_id = int(dict_from_row(existing)["id"])
                conn.execute(
                    "UPDATE organization_subscriptions SET plan_id = ?, status = ?, trial_ends_at = ?, "
                    "current_period_started_at = ?, current_period_ends_at = ?, updated_at = ? WHERE id = ?",
                    (
                        plan_id,
                        status,
                        trial_ends_at,
                        started_at,
                        current_period_ends_at,
                        started_at,
                        subscription_id,
                    ),
                )
            else:
                cur = conn.execute(
                    "INSERT INTO organization_subscriptions "
                    "(organization_id, plan_id, status, trial_ends_at, current_period_started_at, current_period_ends_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        organization_id,
                        plan_id,
                        status,
                        trial_ends_at,
                        started_at,
                        current_period_ends_at,
                        started_at,
                    ),
                )
                subscription_id = int(cur.lastrowid)
            conn.execute(
                "INSERT INTO events (organization_id, type, payload, metadata) VALUES (?, ?, ?, ?)",
                (
                    organization_id,
                    "organization_plan_selected",
                    json.dumps({"subscription_id": subscription_id, "plan_id": plan_id, "status": status}),
                    json.dumps({"actor_user_id": actor_ctx["user"]["id"]}),
                ),
            )
    clear_tenant_caches()
    return get_organization_subscription(organization_id)


def create_organization(
    name: str,
    slug: str | None,
    owner_email: str | None,
    actor_claims: dict[str, Any],
    timezone: str = "Africa/Nairobi",
) -> dict[str, Any]:
    actor = require_system_owner(actor_claims)
    resolved_slug = slugify(slug or name)
    resolved_timezone = normalize_timezone(timezone)
    with get_conn() as conn:
        with conn:
            cur = conn.execute(
                "INSERT INTO organizations (name, slug, timezone, status) VALUES (?, ?, ?, 'ACTIVE')",
                (name.strip(), resolved_slug, resolved_timezone),
            )
            organization_id = cur.lastrowid
            if owner_email:
                owner_user_id = upsert_user_by_email(conn, owner_email, platform_role="user")
                _upsert_organization_user(conn, organization_id, owner_user_id, "org_admin", "ACTIVE")
            conn.execute(
                "INSERT INTO events (type, payload, metadata) VALUES (?, ?, ?)",
                (
                    "organization_created",
                    json.dumps({"organization_id": organization_id, "slug": resolved_slug}),
                    json.dumps({"actor_user_id": actor["id"]}),
                ),
            )
        clear_tenant_caches()
        return get_organization(organization_id)


def update_organization(
    organization_id: int,
    updates: dict[str, Any],
    actor_claims: dict[str, Any],
) -> dict[str, Any]:
    actor_ctx = require_org_role(actor_claims, organization_id, ADMIN_ROLES)
    allowed: dict[str, Any] = {}
    if "name" in updates and updates["name"] is not None:
        name = str(updates["name"]).strip()
        if not name:
            raise ValueError("organization name cannot be empty")
        allowed["name"] = name
    if "timezone" in updates and updates["timezone"] is not None:
        allowed["timezone"] = normalize_timezone(str(updates["timezone"]))
    if not allowed:
        return get_organization(organization_id)

    assignments = ", ".join(f"{field} = ?" for field in allowed)
    params = [*allowed.values(), organization_id]
    with get_conn() as conn:
        with conn:
            conn.execute(f"UPDATE organizations SET {assignments} WHERE id = ?", tuple(params))
            conn.execute(
                "INSERT INTO events (type, payload, metadata) VALUES (?, ?, ?)",
                (
                    "organization_updated",
                    json.dumps({"organization_id": organization_id, "fields": sorted(allowed)}),
                    json.dumps({"actor_user_id": actor_ctx["user"]["id"]}),
                ),
            )
    clear_tenant_caches()
    return get_organization(organization_id)


def get_organization(organization_id: int) -> dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM organizations WHERE id = ?", (organization_id,)).fetchone()
        data = dict_from_row(row)
        if not data:
            raise ValueError("organization not found")
        return data


def list_organizations(actor_claims: dict[str, Any]) -> list[dict[str, Any]]:
    cache_key = _identity_cache_key(actor_claims)
    cached = _get_cache(_org_list_cache, cache_key)
    if cached is not None:
        return cached
    user = ensure_app_user(actor_claims)
    with get_conn() as conn:
        if user.get("platform_role") == "system_owner":
            rows = conn.execute(
                "SELECT o.*, 'system_owner' AS current_user_role FROM organizations o ORDER BY o.id DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT o.*, ou.role AS current_user_role FROM organizations o "
                "JOIN organization_users ou ON ou.organization_id = o.id "
                "WHERE ou.user_id = ? AND ou.status = 'ACTIVE' ORDER BY o.id DESC",
                (user["id"],),
            ).fetchall()
        organizations = [dict_from_row(row) for row in rows]
        for organization in organizations:
            organization["capabilities"] = role_capabilities(organization.get("current_user_role", "viewer"))
            organization["subscription"] = get_organization_subscription(int(organization["id"]))
        _set_cache(_org_list_cache, cache_key, organizations)
        return organizations


def upsert_user_by_email(conn, email: str, *, platform_role: str = "user") -> int:
    normalized = normalize_email(email)
    row = conn.execute("SELECT id FROM app_users WHERE email = ?", (normalized,)).fetchone()
    if row:
        return int(dict_from_row(row)["id"])
    clerk_user_id = f"invited:{normalized}"
    cur = conn.execute(
        "INSERT INTO app_users (clerk_user_id, email, platform_role) VALUES (?, ?, ?)",
        (clerk_user_id, normalized, platform_role),
    )
    return int(cur.lastrowid)


def upsert_org_user(
    organization_id: int,
    email: str,
    role: str,
    status: str,
    actor_claims: dict[str, Any],
) -> dict[str, Any]:
    if role not in ORG_ROLES:
        raise ValueError(f"invalid organization role: {role}")
    if status not in {"ACTIVE", "INVITED", "DISABLED"}:
        raise ValueError(f"invalid organization user status: {status}")
    actor_ctx = require_org_role(actor_claims, organization_id, ADMIN_ROLES)
    with get_conn() as conn:
        with conn:
            user_id = upsert_user_by_email(conn, email)
            _upsert_organization_user(conn, organization_id, user_id, role, status)
            conn.execute(
                "INSERT INTO events (type, payload, metadata) VALUES (?, ?, ?)",
                (
                    "organization_user_upserted",
                    json.dumps({"organization_id": organization_id, "user_id": user_id, "role": role}),
                    json.dumps({"actor_user_id": actor_ctx["user"]["id"]}),
                ),
            )
        clear_tenant_caches()
        return get_organization_user(organization_id, user_id)


def get_organization_user(organization_id: int, user_id: int) -> dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT au.id, au.email, au.name, au.platform_role, ou.organization_id, ou.role, ou.status, ou.created_at "
            "FROM organization_users ou JOIN app_users au ON au.id = ou.user_id "
            "WHERE ou.organization_id = ? AND ou.user_id = ?",
            (organization_id, user_id),
        ).fetchone()
        data = dict_from_row(row)
        if not data:
            raise ValueError("organization user not found")
        return data


def list_organization_users(organization_id: int, actor_claims: dict[str, Any]) -> list[dict[str, Any]]:
    require_org_role(actor_claims, organization_id, MANAGER_ROLES)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT au.id, au.email, au.name, au.platform_role, ou.organization_id, ou.role, ou.status, ou.created_at "
            "FROM organization_users ou JOIN app_users au ON au.id = ou.user_id "
            "WHERE ou.organization_id = ? ORDER BY au.email",
            (organization_id,),
        ).fetchall()
        return [dict_from_row(row) for row in rows]


def create_mailbox(organization_id: int, data: dict[str, Any], actor_claims: dict[str, Any]) -> dict[str, Any]:
    actor_ctx = require_org_role(actor_claims, organization_id, ADMIN_ROLES)
    provider = data.get("provider") or "smtp_imap"
    if provider not in {"smtp_imap", "resend", "gmail", "microsoft"}:
        raise ValueError(f"invalid mailbox provider: {provider}")
    email_address = normalize_email(data.get("email_address"))
    with get_conn() as conn:
        with conn:
            cur = conn.execute(
                "INSERT INTO mailbox_connections "
                "(organization_id, provider, display_name, email_address, status, "
                "smtp_host, smtp_port, smtp_use_ssl, smtp_username, smtp_password_secret, "
                "imap_host, imap_port, imap_use_ssl, imap_username, imap_password_secret, "
                "resend_domain, resend_from_email, resend_reply_to, resend_api_key_secret, "
                "resend_webhook_secret_secret, daily_limit, updated_at) "
                "VALUES (?, ?, ?, ?, 'PENDING', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    organization_id,
                    provider,
                    data.get("display_name"),
                    email_address,
                    data.get("smtp_host"),
                    data.get("smtp_port"),
                    1 if data.get("smtp_use_ssl", True) else 0,
                    data.get("smtp_username"),
                    encrypt_secret(data.get("smtp_password")),
                    data.get("imap_host"),
                    data.get("imap_port"),
                    1 if data.get("imap_use_ssl", True) else 0,
                    data.get("imap_username"),
                    encrypt_secret(data.get("imap_password")),
                    data.get("resend_domain"),
                    data.get("resend_from_email"),
                    data.get("resend_reply_to"),
                    encrypt_secret(data.get("resend_api_key")),
                    encrypt_secret(data.get("resend_webhook_secret")),
                    int(data.get("daily_limit") or 100),
                    now_iso(),
                ),
            )
            mailbox_id = cur.lastrowid
            conn.execute(
                "INSERT INTO events (type, payload, metadata) VALUES (?, ?, ?)",
                (
                    "mailbox_created",
                    json.dumps({"organization_id": organization_id, "mailbox_id": mailbox_id}),
                    json.dumps({"actor_user_id": actor_ctx["user"]["id"]}),
                ),
            )
        return get_mailbox(organization_id, mailbox_id)


def list_mailboxes(organization_id: int, actor_claims: dict[str, Any]) -> list[dict[str, Any]]:
    require_org_role(actor_claims, organization_id, MANAGER_ROLES)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM mailbox_connections WHERE organization_id = ? ORDER BY id DESC",
            (organization_id,),
        ).fetchall()
        return [sanitize_mailbox(dict_from_row(row)) for row in rows]


def get_mailbox(organization_id: int, mailbox_id: int) -> dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM mailbox_connections WHERE organization_id = ? AND id = ?",
            (organization_id, mailbox_id),
        ).fetchone()
        data = dict_from_row(row)
        if not data:
            raise ValueError("mailbox not found")
    return sanitize_mailbox(data)


def get_resend_webhook_mailbox(mailbox_id: int) -> dict[str, Any]:
    """Return raw Resend mailbox config for webhook verification and fetch."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM mailbox_connections WHERE id = ? AND provider = 'resend' AND status = 'CONNECTED'",
            (mailbox_id,),
        ).fetchone()
        data = dict_from_row(row)
        if not data:
            raise ValueError("resend mailbox not found")
        return data


def test_mailbox(
    organization_id: int,
    mailbox_id: int,
    actor_claims: dict[str, Any],
    *,
    smtp_factory: Callable[..., Any] | None = None,
    imap_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    require_org_role(actor_claims, organization_id, ADMIN_ROLES)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM mailbox_connections WHERE organization_id = ? AND id = ?",
            (organization_id, mailbox_id),
        ).fetchone()
        mailbox = dict_from_row(row)
        if not mailbox:
            raise ValueError("mailbox not found")

    if mailbox["provider"] == "resend":
        missing = []
        if not decrypt_secret(mailbox.get("resend_api_key_secret")):
            missing.append("Resend API key")
        if not mailbox.get("resend_from_email"):
            missing.append("Resend from email")
        if missing:
            error = ", ".join(missing) + " required"
            _update_mailbox_test_state(mailbox_id, "FAILED", error)
            return {"success": False, "status": "FAILED", "error": error}
        result = {"success": True, "status": "CONNECTED", "message": "Resend configuration is present"}
        _update_mailbox_test_state(mailbox_id, "CONNECTED", None)
        return result
    if mailbox["provider"] != "smtp_imap":
        result = {"success": False, "status": "FAILED", "error": "provider does not support mailbox testing yet"}
        _update_mailbox_test_state(mailbox_id, "FAILED", result["error"])
        return result

    errors: list[str] = []
    try:
        _test_smtp(mailbox, smtp_factory=smtp_factory)
    except Exception as exc:
        errors.append(f"SMTP: {exc}")
    try:
        _test_imap(mailbox, imap_factory=imap_factory)
    except Exception as exc:
        errors.append(f"IMAP: {exc}")

    if errors:
        error = "; ".join(errors)
        _update_mailbox_test_state(mailbox_id, "FAILED", error)
        return {"success": False, "status": "FAILED", "error": error}
    _update_mailbox_test_state(mailbox_id, "CONNECTED", None)
    return {"success": True, "status": "CONNECTED"}


def _update_mailbox_test_state(mailbox_id: int, status: str, error: str | None) -> None:
    with get_conn() as conn:
        with conn:
            conn.execute(
                "UPDATE mailbox_connections SET status = ?, last_tested_at = ?, last_error = ?, updated_at = ? WHERE id = ?",
                (status, now_iso(), error, now_iso(), mailbox_id),
            )


def _test_smtp(mailbox: dict[str, Any], *, smtp_factory: Callable[..., Any] | None = None) -> None:
    host = mailbox.get("smtp_host")
    port = int(mailbox.get("smtp_port") or (465 if mailbox.get("smtp_use_ssl") else 587))
    username = mailbox.get("smtp_username")
    password = decrypt_secret(mailbox.get("smtp_password_secret"))
    if not (host and username and password):
        raise ValueError("SMTP host, username, and password are required")
    factory = smtp_factory or (smtplib.SMTP_SSL if mailbox.get("smtp_use_ssl") else smtplib.SMTP)
    client = factory(host, port, timeout=15)
    try:
        if not mailbox.get("smtp_use_ssl") and hasattr(client, "starttls"):
            client.starttls()
        client.login(username, password)
        if hasattr(client, "noop"):
            client.noop()
    finally:
        try:
            client.quit()
        except Exception:
            pass


def _test_imap(mailbox: dict[str, Any], *, imap_factory: Callable[..., Any] | None = None) -> None:
    host = mailbox.get("imap_host")
    port = int(mailbox.get("imap_port") or (993 if mailbox.get("imap_use_ssl") else 143))
    username = mailbox.get("imap_username")
    password = decrypt_secret(mailbox.get("imap_password_secret"))
    if not (host and username and password):
        raise ValueError("IMAP host, username, and password are required")
    factory = imap_factory or (imaplib.IMAP4_SSL if mailbox.get("imap_use_ssl") else imaplib.IMAP4)
    client = factory(host, port)
    try:
        client.login(username, password)
        client.select("INBOX", readonly=True)
    finally:
        try:
            client.logout()
        except Exception:
            pass


def encrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    if settings.mailbox_encryption_key:
        return "fernet:" + _fernet().encrypt(value.encode("utf-8")).decode("utf-8")
    logger.warning("MAILBOX_ENCRYPTION_KEY is not set; storing mailbox secret with reversible local encoding")
    return "local:" + base64.b64encode(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    if value.startswith("fernet:"):
        return _fernet().decrypt(value.removeprefix("fernet:").encode("utf-8")).decode("utf-8")
    if value.startswith("local:"):
        return base64.b64decode(value.removeprefix("local:")).decode("utf-8")
    return value


def _fernet() -> Fernet:
    if not settings.mailbox_encryption_key:
        raise RuntimeError("MAILBOX_ENCRYPTION_KEY is required to decrypt this mailbox secret")
    return Fernet(settings.mailbox_encryption_key.encode("utf-8"))


def sanitize_mailbox(mailbox: dict[str, Any]) -> dict[str, Any]:
    clean = dict(mailbox)
    clean.pop("smtp_password_secret", None)
    clean.pop("imap_password_secret", None)
    clean.pop("resend_api_key_secret", None)
    clean.pop("resend_webhook_secret_secret", None)
    clean["has_smtp_password"] = bool(mailbox.get("smtp_password_secret"))
    clean["has_imap_password"] = bool(mailbox.get("imap_password_secret"))
    clean["has_resend_api_key"] = bool(mailbox.get("resend_api_key_secret"))
    clean["has_resend_webhook_secret"] = bool(mailbox.get("resend_webhook_secret_secret"))
    return clean
