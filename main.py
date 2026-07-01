"""
Main FastAPI application with consolidated API endpoints.

Combines outreach and email monitoring functionality.
"""

import asyncio
import csv
import hashlib
import hmac
import io
import logging
from urllib.parse import urlparse
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
import time
import json
from uuid import uuid4

from config.logging import reset_request_id, set_request_id, setup_logging
from langfuse import observe
from config import settings
from schema import WebhookEvent
from schema.leads import ApiLeadImportRequest, BulkLeadImportRequest, LeadCreate, LeadUpdate
from schema.tenancy import (
    MailboxCreate,
    MailboxUpdate,
    OrganizationCreate,
    OrganizationLLMCredentialCreate,
    OrganizationLLMCredentialUpdate,
    OrganizationPlanSelect,
    OrganizationSubscriptionUpdate,
    OrganizationUpdate,
    OrganizationUserUpsert,
    SubscriptionPlanCreate,
    SubscriptionPlanUpdate,
)
from email_monitor.monitor import email_monitor
from email_monitor.webhook_utils import should_process_webhook, DEFAULT_LOOP_PREVENTION
from email_monitor.data_utils import extract_sender_email, extract_sender_name, extract_subject
from schema.outreach import CampaignCreate, CampaignUpdate
from tools.campaign_tools import get_active_campaigns, get_all_campaigns, create_campaign, update_campaign, delete_campaign
from outreach.marketing_agent import OutreachOrchestrator
from utils.auth import get_current_user, get_current_user_or_cron
from services import (
    analytics_service,
    audit_service,
    crm_service,
    draft_service,
    lead_service,
    llm_credential_service,
    metering_service,
    outbound_event_service,
    platform_settings_service,
    sequence_service,
    tenant_service,
    usage_service,
)
from services import mailbox_oauth_service
from services.mailbox_transport import (
    list_connected_imap_mailboxes,
    record_mailbox_sync_failure,
    sync_unread_mailbox,
)
from services.resend_email import normalize_resend_received_email, verify_resend_webhook_signature
from utils.request_timing import get_timings, timed_step

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# The OpenAI Agents SDK uses OPENAI_API_KEY for tracing by default.

# Initialize Orchestrator
outreach_orchestrator = OutreachOrchestrator()

# Webhook Log Broadcaster
class WebhookLogBroadcaster:
    def __init__(self):
        self.connections: list[dict[str, Any]] = []
    
    async def broadcast(
        self,
        status: str,
        message: str,
        event_id: str = "",
        organization_id: int | None = None,
    ):
        short_id = event_id[:8] if event_id else ""
        stale: list[dict[str, Any]] = []
        payload = {
            "status": status,
            "message": message,
            "event_id": short_id,
            "organization_id": organization_id,
        }
        for connection in self.connections:
            queue = connection["queue"]
            subscribed_org_id = connection.get("organization_id")
            if organization_id is not None and subscribed_org_id != organization_id:
                continue
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                stale.append(connection)
        for connection in stale:
            if connection in self.connections:
                self.connections.remove(connection)

    def scoped(self, event_id: str, organization_id: int | None = None):
        """Return a callback pre-bound to a specific event_id."""
        async def _cb(status: str, message: str):
            await self.broadcast(status, message, event_id, organization_id=organization_id)
        return _cb

webhook_broadcaster = WebhookLogBroadcaster()


class LLMRoutingModeUpdate(BaseModel):
    mode: str


class MailboxOAuthStartRequest(BaseModel):
    display_name: str | None = None
    daily_limit: int = 100
_scheduled_sender_task: asyncio.Task | None = None
_mailbox_sync_task: asyncio.Task | None = None


class PlatformCostAllocationCreate(BaseModel):
    period_start: str
    period_end: str
    category: str
    total_cost_usd: float
    provider: Optional[str] = None
    allocation_method: str = "manual"
    notes: Optional[str] = None

# HTTP Access Logging Middleware
_rate_limit_buckets: dict[tuple[str, str], list[float]] = {}


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_rate_limited(request: Request, now: float) -> bool:
    if request.url.path.startswith("/health"):
        return False
    key = (_client_ip(request), request.url.path)
    cutoff = now - 60
    bucket = [ts for ts in _rate_limit_buckets.get(key, []) if ts >= cutoff]
    if len(bucket) >= settings.rate_limit_requests_per_minute:
        _rate_limit_buckets[key] = bucket
        return True
    bucket.append(now)
    _rate_limit_buckets[key] = bucket
    return False


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        token = set_request_id(request_id)
        user_token = metering_service.set_current_user_id(None)
        org_token = metering_service.set_current_organization_id(None)
        
        # Add ngrok skip warning header for local development webhooks
        if request.headers.get("host", "").endswith("ngrok-free.dev") or request.headers.get("host", "").endswith("ngrok.io"):
            # We can't mutate request headers directly easily in starlette, 
            # but Ngrok intercepts it *before* it hits us anyway.
            # To fix the Ngrok warning for incoming webhooks, we need to tell the user to configure it in AgentMail,
            # OR we can try to send a custom response header, but ngrok blocks the *incoming* request.
            pass

        logger.info(
            f"Request: {request.method} {request.url.path}",
            extra={"kind": "request_start", "component": "api", "request_id": request_id},
        )

        try:
            if _is_rate_limited(request, start_time):
                logger.warning(
                    f"Rate limit exceeded: {request.method} {request.url.path}",
                    extra={
                        "kind": "rate_limit_blocked",
                        "component": "api",
                        "request_id": request_id,
                    },
                )
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded"},
                    headers={"X-Request-ID": request_id},
                )
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            process_time = time.time() - start_time
            logger.info(
                f"Response: {request.method} {request.url.path} - "
                f"{response.status_code} - {process_time:.3f}s",
                extra={
                    "kind": "request_complete",
                    "component": "api",
                    "request_id": request_id,
                    "duration_ms": round(process_time * 1000, 2),
                    "status_code": response.status_code,
                },
            )
            route_timings = get_timings(request)
            if route_timings:
                logger.info(
                    f"Route timing: {request.method} {request.url.path}",
                    extra={
                        "kind": "route_timing",
                        "component": "api",
                        "request_id": request_id,
                        "duration_ms": round(process_time * 1000, 2),
                        "status_code": response.status_code,
                        "method": request.method,
                        "path": request.url.path,
                        "steps": route_timings,
                    },
                )
            org_id = metering_service.get_current_organization_id()
            if org_id and not request.url.path.startswith("/api/usage"):
                try:
                    metering_service.record_platform_usage_event(
                        organization_id=org_id,
                        event_type="api_request",
                        quantity=1,
                        source_object_type="http",
                        source_object_id=f"{request.method} {request.url.path}",
                        metadata={
                            "method": request.method,
                            "path": request.url.path,
                            "status_code": response.status_code,
                            "duration_ms": round(process_time * 1000, 2),
                        },
                    )
                except Exception as usage_error:
                    logger.warning(f"Failed to record platform usage event: {usage_error}")
            return response
        except Exception:
            process_time = time.time() - start_time
            route_timings = get_timings(request)
            if route_timings:
                logger.error(
                    f"Route timing failed: {request.method} {request.url.path}",
                    extra={
                        "kind": "route_timing",
                        "component": "api",
                        "request_id": request_id,
                        "duration_ms": round(process_time * 1000, 2),
                        "status_code": 500,
                        "method": request.method,
                        "path": request.url.path,
                        "steps": route_timings,
                    },
                )
            raise
        finally:
            metering_service.reset_current_organization_id(org_token)
            metering_service.reset_current_user_id(user_token)
            reset_request_id(token)

app = FastAPI(
    title="Andela AI Bootcamp Euclid Squad 3 API", 
    description="Outreach and Email Monitoring System",
    version="1.0.0"
)

# Add access logging middleware
app.add_middleware(AccessLogMiddleware)

# Add CORS middleware for Next.js frontend (configurable via CORS_ORIGINS env)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _send_due_scheduled_for_active_organizations(limit: int, actor_id: str = "scheduler") -> dict[str, Any]:
    combined: dict[str, Any] = {"status": "success", "processed": 0, "sent": 0, "failed": 0, "results": []}
    remaining = max(1, min(limit, 200))
    try:
        organization_ids = tenant_service.list_active_subscription_organization_ids()
    except Exception as exc:
        logger.exception(
            "Scheduled email sender could not list active organizations",
            extra={
                "kind": "scheduled_sender_org_list_error",
                "component": "scheduler",
                "error": str(exc),
            },
        )
        combined["status"] = "error"
        combined["failed"] += 1
        combined["results"].append({"error": str(exc), "scope": "active_organizations"})
        return combined

    for org_id in organization_ids:
        if remaining <= 0:
            break
        try:
            result = await draft_service.send_due_scheduled_drafts(
                limit=remaining,
                actor_id=actor_id,
                organization_id=org_id,
            )
        except Exception as exc:
            logger.exception(
                "Scheduled email sender failed for organization",
                extra={
                    "kind": "scheduled_sender_org_error",
                    "component": "scheduler",
                    "organization_id": org_id,
                    "error": str(exc),
                },
            )
            combined["failed"] += 1
            combined["results"].append({"organization_id": org_id, "error": str(exc)})
            continue
        combined["processed"] += result.get("processed", 0)
        combined["sent"] += result.get("sent", 0)
        combined["failed"] += result.get("failed", 0)
        combined["results"].extend(result.get("results", []))
        remaining -= result.get("processed", 0)
    return combined


async def _scheduled_sender_loop() -> None:
    interval = settings.scheduled_sender_interval_seconds
    batch_size = settings.scheduled_sender_batch_size
    initial_delay = settings.scheduled_sender_initial_delay_seconds
    logger.info(
        "Scheduled email sender started",
        extra={
            "kind": "scheduled_sender_started",
            "component": "scheduler",
            "interval_seconds": interval,
            "batch_size": batch_size,
            "initial_delay_seconds": initial_delay,
        },
    )
    if initial_delay > 0:
        await asyncio.sleep(initial_delay)
    while True:
        try:
            result = await _send_due_scheduled_for_active_organizations(batch_size)
            if result.get("processed", 0) > 0:
                logger.info(
                    "Scheduled email sender processed due emails",
                    extra={
                        "kind": "scheduled_sender_tick",
                        "component": "scheduler",
                        "processed": result.get("processed", 0),
                        "sent": result.get("sent", 0),
                        "failed": result.get("failed", 0),
                    },
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "Scheduled email sender failed",
                extra={"kind": "scheduled_sender_error", "component": "scheduler", "error": str(exc)},
            )
        await asyncio.sleep(interval)


@app.on_event("startup")
async def start_scheduled_sender() -> None:
    global _scheduled_sender_task
    if not settings.scheduled_sender_enabled:
        logger.info(
            "Scheduled email sender disabled",
            extra={"kind": "scheduled_sender_disabled", "component": "scheduler"},
        )
        return
    if _scheduled_sender_task and not _scheduled_sender_task.done():
        return
    _scheduled_sender_task = asyncio.create_task(_scheduled_sender_loop())


@app.on_event("shutdown")
async def stop_scheduled_sender() -> None:
    global _scheduled_sender_task
    if not _scheduled_sender_task:
        return
    _scheduled_sender_task.cancel()
    try:
        await _scheduled_sender_task
    except asyncio.CancelledError:
        logger.info(
            "Scheduled email sender stopped",
            extra={"kind": "scheduled_sender_stopped", "component": "scheduler"},
        )
    finally:
        _scheduled_sender_task = None


# Health endpoints
@app.get("/health")
def health() -> Dict[str, str]:
    """Global health check."""
    return {"status": "ok", "service": "Andela AI Bootcamp Euclid Squad 3 API"}

@app.get("/health/db")
def health_db() -> Dict[str, str]:
    """Database health check."""
    try:
        from utils.db_connection import get_conn
        with get_conn() as conn:
            conn.execute("SELECT 1").fetchone()
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        raise HTTPException(status_code=503, detail="Database unavailable")

@app.get("/health/ai")
async def health_ai() -> Dict[str, Any]:
    """AI Provider health check."""
    try:
        from utils.model_fallback import get_available_providers
        providers = get_available_providers()
        if not providers:
            raise Exception("No AI providers configured")
        return {
            "status": "ok", 
            "providers_configured": len(providers),
            "primary_provider": providers[0].name
        }
    except Exception as e:
        logger.error(f"AI health check failed: {e}")
        raise HTTPException(status_code=503, detail="AI providers unavailable")


@app.get("/")
async def root() -> Dict[str, Any]:
    """Root endpoint with API overview."""
    return {
        "service": "Andela AI Bootcamp Euclid Squad 3 API",
        "version": "1.0.0",
        "endpoints": {
            "marketing_campaign": "/outreach/campaign",
            "outreach_ui": "/outreach (Gradio Interface)", 
            "webhook": "/webhook",
            "health": "/health"
        },
        "note": "Visit /outreach for the interactive campaign management UI"
    }


def _raise_service_error(exc: Exception):
    if isinstance(exc, PermissionError):
        raise HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc))
    raise HTTPException(status_code=500, detail=str(exc))


def _org_id(
    user: dict,
    requested_organization_id: int | None = None,
    roles: set[str] | None = None,
) -> int:
    organization_id = tenant_service.resolve_organization_id(user, requested_organization_id, roles)
    try:
        app_user = tenant_service.ensure_app_user(user)
        metering_service.set_current_user_id(int(app_user["id"]))
        metering_service.set_current_organization_id(organization_id)
    except Exception:
        pass
    return organization_id


def _workflow_org_id(
    user: dict,
    requested_organization_id: int | None = None,
    roles: set[str] | None = None,
) -> int:
    try:
        allowed_roles = roles or tenant_service.WORKFLOW_ROLES
        organization_id = _org_id(user, requested_organization_id, allowed_roles)
        tenant_service.require_org_member_role(user, organization_id, allowed_roles)
        tenant_service.require_active_subscription(organization_id)
        return organization_id
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/me")
async def get_me(request: Request, user: dict = Depends(get_current_user)):
    """Return the authenticated user's local platform profile and organizations."""
    try:
        with timed_step(request, "tenant.ensure_app_user"):
            app_user = tenant_service.ensure_app_user(user)
        with timed_step(request, "tenant.list_organizations"):
            organizations = tenant_service.list_organizations(user)
        return {"user": app_user, "organizations": organizations}
    except Exception as e:
        _raise_service_error(e)


@app.get("/api/organizations")
async def list_organizations(user: dict = Depends(get_current_user)):
    """List organizations visible to the current user."""
    try:
        return {"organizations": tenant_service.list_organizations(user)}
    except Exception as e:
        _raise_service_error(e)


@app.post("/api/organizations")
async def create_organization(request: OrganizationCreate, user: dict = Depends(get_current_user)):
    """Create a customer organization. Requires a platform system owner."""
    try:
        organization = tenant_service.create_organization(
            request.name,
            request.slug,
            request.owner_email,
            user,
            request.timezone,
        )
        return {"organization": organization}
    except Exception as e:
        _raise_service_error(e)


@app.get("/api/plans")
async def list_subscription_plans(user: dict = Depends(get_current_user)):
    """List selectable subscription plans. System owners also see inactive plans."""
    try:
        return {"plans": tenant_service.list_subscription_plans(user)}
    except Exception as e:
        _raise_service_error(e)


@app.post("/api/plans")
async def create_subscription_plan(
    request: SubscriptionPlanCreate,
    user: dict = Depends(get_current_user),
):
    """Create a subscription plan. Requires a platform system owner."""
    try:
        plan = tenant_service.create_subscription_plan(request.model_dump(), user)
        return {"plan": plan}
    except Exception as e:
        _raise_service_error(e)


@app.put("/api/plans/{plan_id}")
async def update_subscription_plan(
    plan_id: int,
    request: SubscriptionPlanUpdate,
    user: dict = Depends(get_current_user),
):
    """Update a subscription plan. Requires a platform system owner."""
    try:
        plan = tenant_service.update_subscription_plan(
            plan_id,
            request.model_dump(exclude_unset=True),
            user,
        )
        return {"plan": plan}
    except Exception as e:
        _raise_service_error(e)


@app.get("/api/organizations/{organization_id}/subscription")
async def get_organization_subscription(organization_id: int, user: dict = Depends(get_current_user)):
    """Return the organization's active plan/subscription state."""
    try:
        tenant_service.require_org_role(user, organization_id, tenant_service.READ_ROLES)
        return {"subscription": tenant_service.get_organization_subscription(organization_id)}
    except Exception as e:
        _raise_service_error(e)


@app.post("/api/organizations/{organization_id}/subscription")
async def select_organization_subscription_plan(
    organization_id: int,
    request: OrganizationPlanSelect,
    user: dict = Depends(get_current_user),
):
    """Select a plan for an organization. Requires org admin or system owner."""
    try:
        subscription = tenant_service.select_organization_plan(
            organization_id,
            request.plan_id,
            user,
        )
        return {"subscription": subscription}
    except Exception as e:
        _raise_service_error(e)


@app.put("/api/organizations/{organization_id}/subscription")
async def update_organization_subscription(
    organization_id: int,
    request: OrganizationSubscriptionUpdate,
    user: dict = Depends(get_current_user),
):
    """Manually update an organization's subscription. Requires system owner."""
    try:
        subscription = tenant_service.update_organization_subscription(
            organization_id,
            request.model_dump(exclude_unset=True),
            user,
        )
        return {"subscription": subscription}
    except Exception as e:
        _raise_service_error(e)


@app.get("/api/organizations/{organization_id}/llm-credentials")
async def list_organization_llm_credentials(
    organization_id: int,
    user: dict = Depends(get_current_user),
):
    """List write-only organization LLM provider credentials and BYOK policy."""
    try:
        return llm_credential_service.list_credentials(organization_id, user)
    except Exception as e:
        _raise_service_error(e)


@app.post("/api/organizations/{organization_id}/llm-credentials")
async def create_organization_llm_credential(
    organization_id: int,
    request: OrganizationLLMCredentialCreate,
    user: dict = Depends(get_current_user),
):
    """Create an encrypted organization LLM provider credential."""
    try:
        credential = llm_credential_service.create_credential(
            organization_id,
            request.model_dump(),
            user,
        )
        return {"credential": credential}
    except Exception as e:
        _raise_service_error(e)


@app.put("/api/organizations/{organization_id}/llm-credentials/{credential_id}")
async def update_organization_llm_credential(
    organization_id: int,
    credential_id: int,
    request: OrganizationLLMCredentialUpdate,
    user: dict = Depends(get_current_user),
):
    """Update organization LLM provider credential metadata or rotate its key."""
    try:
        credential = llm_credential_service.update_credential(
            organization_id,
            credential_id,
            request.model_dump(exclude_unset=True),
            user,
        )
        return {"credential": credential}
    except Exception as e:
        _raise_service_error(e)


@app.delete("/api/organizations/{organization_id}/llm-credentials/{credential_id}")
async def delete_organization_llm_credential(
    organization_id: int,
    credential_id: int,
    user: dict = Depends(get_current_user),
):
    """Delete an organization LLM provider credential."""
    try:
        llm_credential_service.delete_credential(organization_id, credential_id, user)
        return {"status": "deleted"}
    except Exception as e:
        _raise_service_error(e)


@app.post("/api/organizations/{organization_id}/llm-credentials/{credential_id}/test")
async def test_organization_llm_credential(
    organization_id: int,
    credential_id: int,
    user: dict = Depends(get_current_user),
):
    """Run a lightweight live credential test and persist the latest result."""
    try:
        return await llm_credential_service.test_credential(organization_id, credential_id, user)
    except Exception as e:
        _raise_service_error(e)


@app.put("/api/organizations/{organization_id}")
async def update_organization(
    organization_id: int,
    request: OrganizationUpdate,
    user: dict = Depends(get_current_user),
):
    """Update organization settings. Requires org admin or system owner."""
    try:
        organization = tenant_service.update_organization(
            organization_id,
            request.model_dump(exclude_unset=True),
            user,
        )
        return {"organization": organization}
    except Exception as e:
        _raise_service_error(e)


@app.get("/api/system/runtime-settings")
async def get_platform_runtime_settings(user: dict = Depends(get_current_user)):
    """Return system-owner runtime settings."""
    try:
        return platform_settings_service.get_platform_runtime_settings(user)
    except Exception as e:
        _raise_service_error(e)


@app.put("/api/system/llm-routing")
async def update_llm_routing_mode(
    request: LLMRoutingModeUpdate,
    user: dict = Depends(get_current_user),
):
    """Change the active LLM routing mode. Requires a platform system owner."""
    try:
        return platform_settings_service.update_llm_routing_mode(request.mode, user)
    except Exception as e:
        _raise_service_error(e)


@app.get("/api/organizations/{organization_id}/users")
async def list_organization_users(organization_id: int, user: dict = Depends(get_current_user)):
    """List users in an organization. Requires manager/admin membership."""
    try:
        return {"users": tenant_service.list_organization_users(organization_id, user)}
    except Exception as e:
        _raise_service_error(e)


@app.post("/api/organizations/{organization_id}/users")
async def upsert_organization_user(
    organization_id: int,
    request: OrganizationUserUpsert,
    user: dict = Depends(get_current_user),
):
    """Add or update a user's organization role. Requires org admin or system owner."""
    try:
        org_user = tenant_service.upsert_org_user(
            organization_id,
            request.email,
            request.role,
            request.status,
            user,
        )
        return {"user": org_user}
    except Exception as e:
        _raise_service_error(e)


@app.get("/api/organizations/{organization_id}/mailboxes")
async def list_mailboxes(organization_id: int, user: dict = Depends(get_current_user)):
    """List mailbox connections for an organization."""
    try:
        return {"mailboxes": tenant_service.list_mailboxes(organization_id, user)}
    except Exception as e:
        _raise_service_error(e)


@app.get("/api/mailbox-providers")
async def list_mailbox_providers(user: dict = Depends(get_current_user)):
    """List supported mailbox provider capabilities for the client UI."""
    return {"providers": tenant_service.list_mailbox_provider_definitions()}


@app.post("/api/organizations/{organization_id}/mailboxes/oauth/{provider}/start")
async def start_mailbox_oauth(
    organization_id: int,
    provider: str,
    request: MailboxOAuthStartRequest,
    http_request: Request,
    user: dict = Depends(get_current_user),
):
    """Create a provider authorization URL for a tenant mailbox OAuth connection."""
    try:
        redirect_uri = str(http_request.url_for("mailbox_oauth_callback", provider=provider))
        return mailbox_oauth_service.build_authorization_url(
            organization_id=organization_id,
            provider=provider,
            data=request.model_dump(),
            actor_claims=user,
            redirect_uri=redirect_uri,
        )
    except Exception as e:
        _raise_service_error(e)


@app.get("/api/mailboxes/oauth/{provider}/callback")
async def mailbox_oauth_callback(provider: str, request: Request):
    """Complete a mailbox OAuth connection and return the user to the frontend."""
    frontend_url = settings.mailbox_oauth_frontend_redirect_url
    error = request.query_params.get("error")
    if error:
        return RedirectResponse(f"{frontend_url}?mailbox_oauth=error&reason={error}")
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code or not state:
        return RedirectResponse(f"{frontend_url}?mailbox_oauth=error&reason=missing_code_or_state")
    try:
        redirect_uri = str(request.url_for("mailbox_oauth_callback", provider=provider))
        mailbox = mailbox_oauth_service.complete_authorization(
            provider=provider,
            code=code,
            state=state,
            redirect_uri=redirect_uri,
        )
        return RedirectResponse(
            f"{frontend_url}?mailbox_oauth=connected&provider={provider}&mailbox_id={mailbox['id']}"
        )
    except Exception as exc:
        logger.warning("Mailbox OAuth callback failed: %s", exc)
        return RedirectResponse(f"{frontend_url}?mailbox_oauth=error&reason=callback_failed")


@app.post("/api/organizations/{organization_id}/mailboxes")
async def create_mailbox(
    organization_id: int,
    request: MailboxCreate,
    user: dict = Depends(get_current_user),
):
    """Create a mailbox connection for SMTP/IMAP, Resend, Gmail, or Microsoft."""
    try:
        mailbox = tenant_service.create_mailbox(
            organization_id,
            request.model_dump(),
            user,
        )
        return {"mailbox": mailbox}
    except Exception as e:
        _raise_service_error(e)


@app.put("/api/organizations/{organization_id}/mailboxes/{mailbox_id}")
async def update_mailbox(
    organization_id: int,
    mailbox_id: int,
    request: MailboxUpdate,
    user: dict = Depends(get_current_user),
):
    """Update a mailbox connection without exposing stored secrets."""
    try:
        mailbox = tenant_service.update_mailbox(
            organization_id,
            mailbox_id,
            request.model_dump(),
            user,
        )
        return {"mailbox": mailbox}
    except Exception as e:
        _raise_service_error(e)


@app.post("/api/organizations/{organization_id}/mailboxes/{mailbox_id}/test")
async def test_mailbox(organization_id: int, mailbox_id: int, user: dict = Depends(get_current_user)):
    """Test SMTP/IMAP connectivity for a mailbox connection."""
    try:
        return tenant_service.test_mailbox(organization_id, mailbox_id, user)
    except Exception as e:
        _raise_service_error(e)


@app.post("/api/organizations/{organization_id}/mailboxes/{mailbox_id}/sync")
async def sync_mailbox(
    organization_id: int,
    mailbox_id: int,
    limit: int = 10,
    user: dict = Depends(get_current_user),
):
    """Fetch unread IMAP replies and process them through the email monitor."""
    try:
        tenant_service.require_org_role(user, organization_id, tenant_service.MANAGER_ROLES)
        tenant_service.require_active_subscription(organization_id)
        return await sync_unread_mailbox(
            organization_id,
            mailbox_id,
            limit=max(1, min(limit, 25)),
            callback=webhook_broadcaster.scoped(f"mailbox:{mailbox_id}", organization_id=organization_id),
        )
    except Exception as e:
        _raise_service_error(e)


# Outreach endpoints
@app.get("/api/campaigns")
async def list_campaigns(
    request: Request,
    user: dict = Depends(get_current_user),
    active_only: bool = True,
    organization_id: Optional[int] = None,
):
    """List campaigns. If active_only is true, returns only ACTIVE campaigns."""
    try:
        with timed_step(request, "tenant.resolve_org"):
            resolved_org_id = _org_id(user, organization_id, tenant_service.READ_ROLES)
        with timed_step(request, "campaigns.query", active_only=active_only):
            if active_only:
                campaigns = get_active_campaigns(resolved_org_id)
            else:
                campaigns = get_all_campaigns(resolved_org_id)
        with timed_step(request, "campaigns.serialize", count=len(campaigns)):
            serialized = [c.dict() for c in campaigns]
        if serialized:
            with timed_step(request, "campaigns.staff_summary", count=len(serialized)):
                from utils.db_connection import get_conn, sql_group_concat_distinct

                campaign_ids = [campaign["id"] for campaign in serialized]
                placeholders = ",".join("?" for _ in campaign_ids)
                staff_names_sql = sql_group_concat_distinct("s.name")
                with get_conn() as conn:
                    staff_rows = conn.execute(
                        "SELECT cs.campaign_id, "
                        f"{staff_names_sql} AS staff_names "
                        "FROM campaign_staff cs "
                        "JOIN staff s ON s.id = cs.staff_id "
                        f"WHERE cs.campaign_id IN ({placeholders}) AND s.organization_id = ? "
                        "GROUP BY cs.campaign_id",
                        (*campaign_ids, resolved_org_id),
                    ).fetchall()
                staff_by_campaign = {
                    int(row["campaign_id"]): [
                        name.strip()
                        for name in str(row["staff_names"] or "").split(",")
                        if name.strip()
                    ]
                    for row in staff_rows
                }
                for campaign in serialized:
                    campaign["staff_names"] = staff_by_campaign.get(int(campaign["id"]), [])
        return {"campaigns": serialized}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list campaigns: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/campaigns")
async def create_new_campaign(
    campaign: CampaignCreate,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Create a new campaign."""
    try:
        resolved_org_id = _workflow_org_id(user, organization_id, tenant_service.WORKFLOW_ROLES)
        new_campaign = create_campaign(campaign, resolved_org_id)
        if not new_campaign:
            raise HTTPException(status_code=500, detail="Failed to create campaign")
        return {"status": "success", "campaign": new_campaign.dict()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create campaign: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/campaigns/{campaign_id}")
async def update_existing_campaign(
    campaign_id: int,
    updates: CampaignUpdate,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Update an existing campaign."""
    try:
        resolved_org_id = _workflow_org_id(user, organization_id, tenant_service.WORKFLOW_ROLES)
        updated_campaign = update_campaign(campaign_id, updates, resolved_org_id)
        if not updated_campaign:
            raise HTTPException(status_code=404, detail="Campaign not found or update failed")
        return {"status": "success", "campaign": updated_campaign.dict()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update campaign {campaign_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/campaigns/{campaign_id}")
async def delete_existing_campaign(
    campaign_id: int,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Delete an existing campaign."""
    try:
        resolved_org_id = _workflow_org_id(user, organization_id, tenant_service.WORKFLOW_ROLES)
        success = delete_campaign(campaign_id, resolved_org_id)
        if not success:
            raise HTTPException(status_code=404, detail="Campaign not found or deletion failed")
        return {"status": "success", "message": f"Campaign {campaign_id} deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete campaign {campaign_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class StaffUpsertRequest(BaseModel):
    model_config = {"extra": "forbid"}

    name: str
    email: str
    timezone: Optional[str] = None
    availability: Optional[str] = None
    dummy_slots: Optional[str] = None


class CampaignStaffAssignmentRequest(BaseModel):
    model_config = {"extra": "forbid"}

    staff_ids: List[int]


@app.get("/api/staff")
async def list_staff(
    request: Request,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """List all staff available for campaign assignment and meeting notifications."""
    try:
        from utils.db_connection import get_conn
        with timed_step(request, "tenant.resolve_org"):
            resolved_org_id = _org_id(user, organization_id, tenant_service.READ_ROLES)
        with timed_step(request, "staff.query"):
            with get_conn() as conn:
                cur = conn.execute(
                    "SELECT id, name, email, timezone, availability, dummy_slots, created_at "
                    "FROM staff WHERE organization_id = ? ORDER BY id ASC",
                    (resolved_org_id,),
                )
                rows = cur.fetchall()
        with timed_step(request, "staff.serialize", count=len(rows)):
            staff = [dict(row) for row in rows]
        return {"staff": staff}
    except Exception as e:
        logger.error(f"Failed to list staff: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/staff")
async def create_staff_member(
    request: StaffUpsertRequest,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Create a staff member."""
    try:
        from utils.db_connection import get_conn
        resolved_org_id = _workflow_org_id(user, organization_id, tenant_service.MANAGER_ROLES)
        with get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO staff (organization_id, name, email, timezone, availability, dummy_slots) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    resolved_org_id,
                    request.name.strip(),
                    request.email.strip().lower(),
                    request.timezone,
                    request.availability,
                    request.dummy_slots,
                ),
            )
            staff_id = cur.lastrowid
        return {"status": "success", "staff_id": staff_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create staff member: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/staff/{staff_id}")
async def update_staff_member(
    staff_id: int,
    request: StaffUpsertRequest,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Update a staff member."""
    try:
        from utils.db_connection import get_conn
        resolved_org_id = _workflow_org_id(user, organization_id, tenant_service.MANAGER_ROLES)
        with get_conn() as conn:
            row = conn.execute(
                "SELECT id FROM staff WHERE id = ? AND organization_id = ?",
                (staff_id, resolved_org_id),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Staff member not found")
            conn.execute(
                "UPDATE staff SET name = ?, email = ?, timezone = ?, availability = ?, dummy_slots = ? WHERE id = ? AND organization_id = ?",
                (
                    request.name.strip(),
                    request.email.strip().lower(),
                    request.timezone,
                    request.availability,
                    request.dummy_slots,
                    staff_id,
                    resolved_org_id,
                ),
            )
        return {"status": "success", "staff_id": staff_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update staff member {staff_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/staff/{staff_id}")
async def delete_staff_member(
    staff_id: int,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Delete a staff member."""
    try:
        from utils.db_connection import get_conn
        resolved_org_id = _workflow_org_id(user, organization_id, tenant_service.MANAGER_ROLES)
        with get_conn() as conn:
            row = conn.execute(
                "SELECT id FROM staff WHERE id = ? AND organization_id = ?",
                (staff_id, resolved_org_id),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Staff member not found")
            conn.execute(
                "DELETE FROM staff WHERE id = ? AND organization_id = ?",
                (staff_id, resolved_org_id),
            )
        return {"status": "success", "staff_id": staff_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete staff member {staff_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/campaigns/{campaign_id}/staff")
async def get_campaign_staff(
    campaign_id: int,
    request: Request,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Get all staff with assignment state for a campaign."""
    try:
        from utils.db_connection import get_conn
        with timed_step(request, "tenant.resolve_org"):
            resolved_org_id = _org_id(user, organization_id, tenant_service.READ_ROLES)
        with timed_step(request, "campaign_staff.query"):
            with get_conn() as conn:
                c = conn.execute(
                    "SELECT id, name FROM campaigns WHERE id = ? AND organization_id = ?",
                    (campaign_id, resolved_org_id),
                ).fetchone()
                if not c:
                    raise HTTPException(status_code=404, detail="Campaign not found")

                cur = conn.execute(
                    "SELECT s.id, s.name, s.email, s.timezone, "
                    "CASE WHEN cs.campaign_id IS NULL THEN 0 ELSE 1 END AS assigned "
                    "FROM staff s "
                    "LEFT JOIN campaign_staff cs ON cs.staff_id = s.id AND cs.campaign_id = ? "
                    "WHERE s.organization_id = ? ORDER BY s.id ASC",
                    (campaign_id, resolved_org_id),
                )
                rows = cur.fetchall()
        with timed_step(request, "campaign_staff.serialize", count=len(rows)):
            staff = [dict(row) for row in rows]
        return {"campaign_id": campaign_id, "staff": staff}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch campaign staff for {campaign_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/campaigns/{campaign_id}/staff")
async def replace_campaign_staff(
    campaign_id: int,
    request: CampaignStaffAssignmentRequest,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Replace campaign staff assignments with the provided staff IDs."""
    try:
        from utils.db_connection import get_conn
        resolved_org_id = _workflow_org_id(user, organization_id, tenant_service.MANAGER_ROLES)
        staff_ids = sorted(set(request.staff_ids))
        with get_conn() as conn:
            c = conn.execute(
                "SELECT id FROM campaigns WHERE id = ? AND organization_id = ?",
                (campaign_id, resolved_org_id),
            ).fetchone()
            if not c:
                raise HTTPException(status_code=404, detail="Campaign not found")

            if staff_ids:
                placeholders = ",".join("?" for _ in staff_ids)
                rows = conn.execute(
                    f"SELECT id FROM staff WHERE organization_id = ? AND id IN ({placeholders})",
                    (resolved_org_id, *staff_ids),
                ).fetchall()
                found = {r["id"] for r in rows}
                missing = [sid for sid in staff_ids if sid not in found]
                if missing:
                    raise HTTPException(status_code=400, detail=f"Invalid staff IDs: {missing}")

            with conn:
                conn.execute("DELETE FROM campaign_staff WHERE campaign_id = ?", (campaign_id,))
                for staff_id in staff_ids:
                    conn.execute(
                        "INSERT INTO campaign_staff (campaign_id, staff_id) VALUES (?, ?)",
                        (campaign_id, staff_id),
                    )
        return {"status": "success", "campaign_id": campaign_id, "assigned_count": len(staff_ids)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update campaign staff for {campaign_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/leads")
async def list_leads(
    request: Request,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """List leads with outreach status, campaign context, and last outbound activity."""
    try:
        from utils.db_connection import get_conn, sql_group_concat_distinct, sql_order_by_datetime

        with timed_step(request, "tenant.resolve_org"):
            resolved_org_id = _org_id(user, organization_id, tenant_service.READ_ROLES)
        odt = sql_order_by_datetime("em.created_at")
        gcat = sql_group_concat_distinct("c.name")
        with timed_step(request, "leads.query"):
            with get_conn() as conn:
                cur = conn.execute(
                    "SELECT "
                    "l.id, l.name, l.email, l.phone_number, l.linkedin_url, l.company, l.industry, l.pain_points, "
                    "l.status, l.touch_count, l.email_opt_out, "
                    "l.last_contacted_at, l.last_inbound_at, l.created_at, "
                    "COALESCE(SUM(cl.emails_sent), 0) AS emails_sent, "
                    "COALESCE(MAX(CAST(cl.responded AS INTEGER)), 0) AS responded, "
                    "COALESCE(MAX(CAST(cl.meeting_booked AS INTEGER)), 0) AS meeting_booked, "
                    f"{gcat} AS campaigns, "
                    f"{sql_group_concat_distinct('c.id')} AS campaign_ids, "
                    "(SELECT em.status FROM email_messages em "
                    " WHERE em.lead_id = l.id AND em.direction = 'outbound' "
                    f" ORDER BY {odt} DESC LIMIT 1) AS last_outbound_status, "
                    "(SELECT em.subject FROM email_messages em "
                    " WHERE em.lead_id = l.id AND em.direction = 'outbound' "
                    f" ORDER BY {odt} DESC LIMIT 1) AS last_outbound_subject, "
                    "(SELECT em.created_at FROM email_messages em "
                    " WHERE em.lead_id = l.id AND em.direction = 'outbound' "
                    f" ORDER BY {odt} DESC LIMIT 1) AS last_outbound_at "
                    "FROM leads l "
                    "LEFT JOIN campaign_leads cl ON cl.lead_id = l.id "
                    "LEFT JOIN campaigns c ON c.id = cl.campaign_id AND c.organization_id = l.organization_id "
                    "WHERE l.organization_id = ? "
                    "GROUP BY l.id "
                    "ORDER BY l.id ASC",
                    (resolved_org_id,),
                )
                rows = cur.fetchall()
        with timed_step(request, "leads.serialize", count=len(rows)):
            leads = [dict(row) for row in rows]
        return {"leads": leads}
    except Exception as e:
        logger.error(f"Failed to list leads: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/leads")
async def create_lead(
    request: LeadCreate,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Create a single lead and optionally assign it to campaigns."""
    resolved_org_id = _workflow_org_id(user, organization_id, tenant_service.WORKFLOW_ROLES)
    result = lead_service.create_lead(request.model_dump(), resolved_org_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return {"lead": result["data"]}


@app.put("/api/leads/{lead_id}")
async def update_lead(
    lead_id: int,
    request: LeadUpdate,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Update a lead. Include campaign_ids to replace campaign assignment."""
    payload = request.model_dump(exclude_unset=True)
    resolved_org_id = _workflow_org_id(user, organization_id, tenant_service.WORKFLOW_ROLES)
    result = lead_service.update_lead(lead_id, payload, resolved_org_id)
    if not result["success"]:
        status_code = 404 if result["error"] == "lead not found" else 400
        raise HTTPException(status_code=status_code, detail=result["error"])
    return {"lead": result["data"]}


@app.delete("/api/leads/{lead_id}")
async def delete_lead(
    lead_id: int,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Delete a lead and related campaign/message rows through FK cascade."""
    resolved_org_id = _workflow_org_id(user, organization_id, tenant_service.WORKFLOW_ROLES)
    result = lead_service.delete_lead(lead_id, resolved_org_id)
    if not result["success"]:
        status_code = 404 if result["error"] == "lead not found" else 400
        raise HTTPException(status_code=status_code, detail=result["error"])
    return result["data"]


class BulkDeleteLeadsRequest(BaseModel):
    lead_ids: list[int]

@app.post("/api/leads/bulk-delete")
async def bulk_delete_leads(
    request: BulkDeleteLeadsRequest,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Bulk delete leads and related rows through FK cascade."""
    resolved_org_id = _workflow_org_id(user, organization_id, tenant_service.WORKFLOW_ROLES)
    result = lead_service.bulk_delete_leads(request.lead_ids, resolved_org_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result["data"]


@app.post("/api/leads/import")
async def bulk_import_leads(
    request: BulkLeadImportRequest,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Bulk import leads from UI-parsed CSV/JSON or another trusted client."""
    resolved_org_id = _workflow_org_id(user, organization_id, tenant_service.WORKFLOW_ROLES)
    result = lead_service.bulk_import_leads(
        request.leads,
        campaign_ids=request.campaign_ids,
        upsert=request.upsert,
        source=request.source,
        organization_id=resolved_org_id,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    await outbound_event_service.emit_event("leads_imported", result["data"])
    return result["data"]


def _dig_json_path(payload: Any, json_path: str | None) -> Any:
    if not json_path:
        return payload
    current = payload
    for part in [p for p in json_path.split(".") if p]:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            current = current[int(part)]
        else:
            return None
    return current


def _normalize_external_lead(raw: dict[str, Any]) -> dict[str, Any]:
    lowered = {str(k).strip().lower(): v for k, v in raw.items()}

    def pick(*names: str):
        for name in names:
            if name in lowered and lowered[name] not in (None, ""):
                return lowered[name]
        return None

    return {
        "email": pick("email", "email_address", "work_email"),
        "name": pick("name", "full_name", "contact_name"),
        "phone_number": pick("phone_number", "phone", "mobile"),
        "linkedin_url": pick("linkedin_url", "linkedin", "linkedin_profile"),
        "company": pick("company", "company_name", "account"),
        "industry": pick("industry", "sector"),
        "pain_points": pick("pain_points", "pain point", "notes", "description"),
        "status": pick("status") or "NEW",
        "email_opt_out": str(pick("email_opt_out", "opt_out", "unsubscribed") or "").lower()
        in {"1", "true", "yes", "y"},
    }


def _extract_leads_from_payload(payload: Any, json_path: str | None = None) -> list[dict[str, Any]]:
    data = _dig_json_path(payload, json_path)
    if isinstance(data, dict):
        for key in ("leads", "data", "records", "results", "items"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        raise ValueError("API response must be a JSON array or contain leads/data/records/results/items")
    return [_normalize_external_lead(item) for item in data if isinstance(item, dict)]


def _is_allowed_import_url(source_url: str) -> bool:
    parsed = urlparse(source_url)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    blocked_hosts = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
    return bool(host) and host not in blocked_hosts and not host.endswith(".local")


@app.post("/api/leads/import/url")
async def import_leads_from_url(
    request: ApiLeadImportRequest,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Fetch leads from an external JSON or CSV API and import them."""
    if not _is_allowed_import_url(request.source_url):
        raise HTTPException(status_code=400, detail="source_url must be an external http(s) URL")

    try:
        import httpx

        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() in {"authorization", "x-api-key", "accept"}
        }
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            response = await client.get(request.source_url, headers=headers)
            response.raise_for_status()
            body = response.text
            if len(body) > 2_000_000:
                raise ValueError("response too large; max 2MB")
            content_type = response.headers.get("content-type", "")
            if "csv" in content_type or request.source_url.lower().endswith(".csv"):
                rows = list(csv.DictReader(io.StringIO(body)))
                leads = [_normalize_external_lead(row) for row in rows]
            else:
                leads = _extract_leads_from_payload(response.json(), request.json_path)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to import leads from URL: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    resolved_org_id = _workflow_org_id(user, organization_id, tenant_service.WORKFLOW_ROLES)
    result = lead_service.bulk_import_leads(
        leads,
        campaign_ids=request.campaign_ids,
        upsert=request.upsert,
        source=request.source_url,
        organization_id=resolved_org_id,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    await outbound_event_service.emit_event("leads_imported", result["data"])
    return result["data"]


@app.get("/api/usage/llm")
async def get_llm_usage(
    request: Request,
    user: dict = Depends(get_current_user),
    limit: int = 100,
    organization_id: Optional[int] = None,
    routing_mode: Optional[str] = None,
):
    """Return aggregate LLM token and estimated cost usage."""
    if routing_mode and routing_mode not in {"quality_first", "balanced", "cost_optimized"}:
        raise HTTPException(status_code=400, detail="Invalid routing_mode")
    with timed_step(request, "tenant.resolve_org"):
        resolved_org_id = _org_id(user, organization_id, tenant_service.READ_ROLES)
    bounded_limit = max(1, min(limit, 500))
    with timed_step(request, "usage.summary", limit=bounded_limit):
        return usage_service.get_usage_summary(
            limit=bounded_limit,
            organization_id=resolved_org_id,
            routing_mode=routing_mode,
        )


@app.get("/api/usage/customer")
async def get_customer_usage(
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Return customer-facing plan usage for the selected organization."""
    resolved_org_id = _org_id(user, organization_id, tenant_service.READ_ROLES)
    return metering_service.get_customer_usage_summary(resolved_org_id)


@app.get("/api/usage/margins")
async def get_usage_margin_summary(
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Return owner-facing usage and estimated vendor-cost summary."""
    tenant_service.require_system_owner(user)
    return metering_service.get_owner_margin_summary(organization_id=organization_id)


@app.get("/api/usage/unit-economics")
async def get_usage_unit_economics(
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Return action-level cost averages for pricing and margin modeling."""
    tenant_service.require_system_owner(user)
    return metering_service.get_action_unit_economics(organization_id=organization_id)


@app.post("/api/usage/platform-costs")
async def create_platform_cost_allocation(
    request: PlatformCostAllocationCreate,
    user: dict = Depends(get_current_user),
):
    """Record a manual platform cost allocation for future margin analysis."""
    tenant_service.require_system_owner(user)
    return {
        "allocation": metering_service.add_platform_cost_allocation(
            period_start=request.period_start,
            period_end=request.period_end,
            category=request.category,
            provider=request.provider,
            total_cost_usd=request.total_cost_usd,
            allocation_method=request.allocation_method,
            notes=request.notes,
        )
    }


@app.get("/api/campaigns/{campaign_id}/leads")
async def get_campaign_leads(
    campaign_id: int,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Get all leads with assignment info for a campaign."""
    try:
        from utils.db_connection import get_conn
        resolved_org_id = _org_id(user, organization_id, tenant_service.READ_ROLES)
        with get_conn() as conn:
            # Ensure campaign exists
            c = conn.execute(
                "SELECT id, name FROM campaigns WHERE id = ? AND organization_id = ?",
                (campaign_id, resolved_org_id),
            ).fetchone()
            if not c:
                raise HTTPException(status_code=404, detail="Campaign not found")

            cur = conn.execute(
                "SELECT l.id, l.name, l.email, l.company, l.status, l.touch_count, "
                "CASE WHEN cl.campaign_id IS NULL THEN 0 ELSE 1 END AS assigned, "
                "COALESCE(cl.emails_sent, 0) AS emails_sent, "
                "COALESCE(CAST(cl.responded AS INTEGER), 0) AS responded, "
                "COALESCE(CAST(cl.meeting_booked AS INTEGER), 0) AS meeting_booked "
                "FROM leads l "
                "LEFT JOIN campaign_leads cl ON cl.lead_id = l.id AND cl.campaign_id = ? "
                "WHERE l.organization_id = ? ORDER BY l.id ASC",
                (campaign_id, resolved_org_id),
            )
            leads = [dict(row) for row in cur.fetchall()]
        return {"campaign_id": campaign_id, "leads": leads}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch campaign leads for {campaign_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class CampaignLeadAssignmentRequest(BaseModel):
    model_config = {"extra": "forbid"}

    lead_ids: List[int]


@app.put("/api/campaigns/{campaign_id}/leads")
async def replace_campaign_leads(
    campaign_id: int,
    request: CampaignLeadAssignmentRequest,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Replace campaign lead assignments with the provided lead IDs."""
    try:
        from utils.db_connection import get_conn
        resolved_org_id = _workflow_org_id(user, organization_id, tenant_service.WORKFLOW_ROLES)
        lead_ids = sorted(set(request.lead_ids))
        with get_conn() as conn:
            c = conn.execute(
                "SELECT id FROM campaigns WHERE id = ? AND organization_id = ?",
                (campaign_id, resolved_org_id),
            ).fetchone()
            if not c:
                raise HTTPException(status_code=404, detail="Campaign not found")

            # Validate provided lead IDs exist
            if lead_ids:
                placeholders = ",".join("?" for _ in lead_ids)
                rows = conn.execute(
                    f"SELECT id FROM leads WHERE organization_id = ? AND id IN ({placeholders})",
                    (resolved_org_id, *lead_ids),
                ).fetchall()
                found = {r["id"] for r in rows}
                missing = [lid for lid in lead_ids if lid not in found]
                if missing:
                    raise HTTPException(status_code=400, detail=f"Invalid lead IDs: {missing}")

            with conn:
                conn.execute("DELETE FROM campaign_leads WHERE campaign_id = ?", (campaign_id,))
                for lead_id in lead_ids:
                    conn.execute(
                        "INSERT INTO campaign_leads (campaign_id, lead_id, emails_sent, responded, meeting_booked) "
                        "VALUES (?, ?, 0, 0, 0)",
                        (campaign_id, lead_id),
                    )
        return {"status": "success", "campaign_id": campaign_id, "assigned_count": len(lead_ids)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update campaign leads for {campaign_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class ScoutLeadsRequest(BaseModel):
    limit: int = 50  # clamped in the handler (1–100)
    approve_credit_spend: bool = False

@app.post("/api/campaigns/{campaign_id}/scout-leads")
async def scout_campaign_leads(
    campaign_id: int,
    request: ScoutLeadsRequest,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Trigger the Lead Scout Agent to find and import leads for a campaign."""
    try:
        from utils.db_connection import get_conn, dict_from_row
        from outreach.lead_scout.agent import LeadScoutAgent
        
        resolved_org_id = _workflow_org_id(user, organization_id, tenant_service.WORKFLOW_ROLES)
        scout_limit = max(1, min(request.limit, 100))
        
        with get_conn() as conn:
            c = conn.execute(
                "SELECT * FROM campaigns WHERE id = ? AND organization_id = ?",
                (campaign_id, resolved_org_id),
            ).fetchone()
            if not c:
                raise HTTPException(status_code=404, detail="Campaign not found")
            campaign_context = dict_from_row(c)

        agent = LeadScoutAgent(organization_id=resolved_org_id)
        credit_estimate = agent.estimate_credit_exposure(limit=scout_limit)
        if credit_estimate.get("requires_approval") and not request.approve_credit_spend:
            raise HTTPException(
                status_code=428,
                detail={
                    "code": "credit_approval_required",
                    "message": "This lead scout run may consume paid provider credits and requires approval.",
                    "estimated_max_credits": credit_estimate.get("estimated_max_credits", 0),
                    "provider_statuses": credit_estimate.get("provider_statuses", []),
                },
            )

        with get_conn() as conn:
            # Record the job
            cur = conn.execute(
                "INSERT INTO lead_discovery_jobs (organization_id, campaign_id, status) VALUES (?, ?, 'RUNNING')",
                (resolved_org_id, campaign_id)
            )
            job_id = cur.lastrowid
            
        result = await agent.run_discovery_job(campaign_id, campaign_context, limit=scout_limit)
        
        with get_conn() as conn:
            with conn:
                conn.execute(
                    "UPDATE lead_discovery_jobs SET status = ?, candidates_found = ?, leads_imported = ?, error = ?, completed_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (result.get("status"), result.get("candidates_found", 0), result.get("leads_imported", 0), result.get("error"), job_id)
                )
                
        return {"job_id": job_id, "result": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to scout leads for campaign {campaign_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/campaigns/{campaign_id}/discovery-jobs")
async def get_discovery_jobs(
    campaign_id: int,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Get history of lead discovery jobs for a campaign."""
    try:
        from utils.db_connection import get_conn, dict_from_row
        resolved_org_id = _org_id(user, organization_id, tenant_service.READ_ROLES)
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM lead_discovery_jobs WHERE campaign_id = ? AND organization_id = ? ORDER BY created_at DESC LIMIT 20",
                (campaign_id, resolved_org_id),
            ).fetchall()
        return {"jobs": [dict_from_row(r) for r in rows]}
    except Exception as e:
        logger.error(f"Failed to fetch discovery jobs for campaign {campaign_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/drafts")
async def list_drafts(
    request: Request,
    user: dict = Depends(get_current_user),
    q: Optional[str] = None,
    campaign_name: Optional[str] = None,
    lead_email: Optional[str] = None,
    organization_id: Optional[int] = None,
):
    """List all pending email drafts awaiting approval."""
    try:
        from services.campaign_context_service import build_draft_generation_summary, summarize_text
        from utils.db_connection import get_conn, sql_order_by_datetime

        with timed_step(request, "tenant.resolve_org"):
            resolved_org_id = _org_id(user, organization_id, tenant_service.READ_ROLES)
        order_created = sql_order_by_datetime("e.created_at")
        with timed_step(
            request,
            "drafts.build_filters",
            has_query=bool(q),
            has_campaign=bool(campaign_name),
            has_lead_email=bool(lead_email),
        ):
            where_clauses = [
                "e.organization_id = ?",
                "UPPER(e.status) = 'DRAFT'",
                "e.approved = 0",
                "e.direction = 'outbound'",
            ]
            params: list[Any] = [resolved_org_id]

            if q:
                where_clauses.append(
                    "(e.subject LIKE ? OR e.body LIKE ? OR l.name LIKE ? OR l.email LIKE ? OR c.name LIKE ?)"
                )
                q_like = f"%{q}%"
                params.extend([q_like, q_like, q_like, q_like, q_like])
            if campaign_name:
                where_clauses.append("c.name = ?")
                params.append(campaign_name)
            if lead_email:
                where_clauses.append("l.email = ?")
                params.append(lead_email)

            where_sql = " AND ".join(where_clauses)
        with get_conn() as conn:
            with timed_step(request, "drafts.query"):
                cur = conn.execute(
                    "SELECT "
                    "e.id, e.subject, e.body, e.created_at, e.lead_id, e.campaign_id, "
                    "e.sequence_step_id, e.external_message_id, e.external_thread_id, "
                    "e.selected_draft_type, e.review_rationale, "
                    "e.channel, e.deep_link_url, "
                    "l.touch_count, cl.emails_sent, "
                    "l.name as lead_name, l.email as lead_email, "
                    "COALESCE(c.name, 'No campaign') as campaign_name, "
                    "src.subject as source_subject, src.body as source_body, "
                    "src.intent as source_intent, src.created_at as source_received_at, "
                    "(SELECT prev.subject FROM email_messages prev "
                    "WHERE prev.organization_id = e.organization_id "
                    "AND prev.campaign_id = e.campaign_id "
                    "AND prev.lead_id = e.lead_id "
                    "AND prev.direction = 'outbound' "
                    "AND prev.id <> e.id "
                    "AND UPPER(prev.status) <> 'DRAFT' "
                    "ORDER BY prev.created_at DESC LIMIT 1) as previous_outbound_subject, "
                    "(SELECT prev.body FROM email_messages prev "
                    "WHERE prev.organization_id = e.organization_id "
                    "AND prev.campaign_id = e.campaign_id "
                    "AND prev.lead_id = e.lead_id "
                    "AND prev.direction = 'outbound' "
                    "AND prev.id <> e.id "
                    "AND UPPER(prev.status) <> 'DRAFT' "
                    "ORDER BY prev.created_at DESC LIMIT 1) as previous_outbound_body, "
                    "ctx.last_outbound_subject as context_last_outbound_subject, "
                    "ctx.last_outbound_summary as context_last_outbound_summary, "
                    "ctx.last_inbound_subject as context_last_inbound_subject, "
                    "ctx.last_inbound_summary as context_last_inbound_summary, "
                    "ctx.latest_intent as context_latest_intent, "
                    "ctx.updated_at as context_updated_at "
                    "FROM email_messages e "
                    "JOIN leads l ON e.lead_id = l.id "
                    "LEFT JOIN campaigns c ON e.campaign_id = c.id "
                    "LEFT JOIN campaign_leads cl ON cl.campaign_id = e.campaign_id "
                    "AND cl.lead_id = e.lead_id "
                    "LEFT JOIN email_messages src ON src.organization_id = e.organization_id "
                    "AND src.direction = 'inbound' "
                    "AND src.external_message_id IS NOT NULL "
                    "AND src.external_message_id = e.external_message_id "
                    "LEFT JOIN campaign_lead_contexts ctx ON ctx.campaign_id = e.campaign_id "
                    "AND ctx.lead_id = e.lead_id "
                    f"WHERE {where_sql} "
                    f"ORDER BY {order_created} DESC",
                    tuple(params),
                )
                drafts = [dict(row) for row in cur.fetchall()]
            with timed_step(request, "drafts.attachments", count=len(drafts)):
                attachment_map = draft_service.list_attachments_for_messages(
                    conn,
                    [draft["id"] for draft in drafts],
                )
            with timed_step(request, "drafts.serialize", count=len(drafts)):
                for draft in drafts:
                    subject_text = str(draft.get("subject") or "").strip().lower()
                    has_reply_source_metadata = bool(
                        draft.get("external_message_id")
                        or draft.get("external_thread_id")
                    )
                    has_inbound_context = bool(
                        draft.get("source_body")
                        or draft.get("context_last_inbound_summary")
                        or draft.get("context_latest_intent")
                    )
                    is_inbound_response = has_reply_source_metadata or (
                        subject_text.startswith("re:") and has_inbound_context
                    )
                    inbound_summary = summarize_text(draft.get("source_body")) or draft.get("context_last_inbound_summary")
                    previous_outbound_summary = (
                        summarize_text(draft.pop("previous_outbound_body", None))
                        or draft.get("context_last_outbound_summary")
                    )
                    previous_outbound_subject = (
                        draft.pop("previous_outbound_subject", None)
                        or draft.get("context_last_outbound_subject")
                    )
                    generation_summary = build_draft_generation_summary(
                        source="inbound_response" if is_inbound_response else "outreach",
                        lead_name=draft.get("lead_name"),
                        campaign_name=draft.get("campaign_name"),
                        emails_sent=draft.pop("emails_sent", None),
                        touch_count=draft.pop("touch_count", None),
                        inbound_summary=inbound_summary,
                        last_outbound_summary=previous_outbound_summary,
                        last_inbound_summary=draft.get("context_last_inbound_summary"),
                        intent=draft.get("source_intent", None) or draft.get("context_latest_intent"),
                    )
                    review_context = {
                        "source": "inbound_response" if is_inbound_response else "outreach",
                        "source_label": "Reply draft" if is_inbound_response else "Cold outreach",
                        "generation_summary": generation_summary,
                        "review_rationale": draft.pop("review_rationale", None),
                        "selected_draft_type": draft.pop("selected_draft_type", None),
                        "inbound_subject": draft.pop("source_subject", None),
                        "inbound_summary": inbound_summary,
                        "inbound_received_at": draft.pop("source_received_at", None),
                        "intent": draft.pop("source_intent", None) or draft.get("context_latest_intent"),
                        "last_outbound_subject": previous_outbound_subject,
                        "last_outbound_summary": previous_outbound_summary,
                        "last_inbound_subject": draft.pop("context_last_inbound_subject", None),
                        "last_inbound_summary": draft.pop("context_last_inbound_summary", None),
                        "context_updated_at": draft.pop("context_updated_at", None),
                    }
                    draft.pop("context_last_outbound_subject", None)
                    draft.pop("context_last_outbound_summary", None)
                    draft.pop("source_body", None)
                    draft.pop("context_latest_intent", None)
                    draft["draft_source"] = review_context["source"]
                    draft["review_context"] = review_context
                    draft["body"] = draft_service.clean_quick_reply_text(draft["body"])
                    draft["attachments"] = attachment_map.get(draft["id"], [])
        return {"drafts": drafts}
    except Exception as e:
        logger.error(f"Failed to list drafts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/drafts/count")
async def count_drafts(
    request: Request,
    user: dict = Depends(get_current_user),
    q: Optional[str] = None,
    campaign_name: Optional[str] = None,
    lead_email: Optional[str] = None,
    organization_id: Optional[int] = None,
):
    """Count pending email drafts awaiting approval without fetching full draft bodies."""
    try:
        from utils.db_connection import get_conn

        with timed_step(request, "tenant.resolve_org"):
            resolved_org_id = _org_id(user, organization_id, tenant_service.READ_ROLES)
        with timed_step(
            request,
            "drafts.count_build_filters",
            has_query=bool(q),
            has_campaign=bool(campaign_name),
            has_lead_email=bool(lead_email),
        ):
            where_clauses = [
                "e.organization_id = ?",
                "e.status IN ('DRAFT', 'draft')",
                "e.approved = 0",
                "e.direction = 'outbound'",
            ]
            params: list[Any] = [resolved_org_id]
            joins: list[str] = []

            if q:
                joins.extend([
                    "JOIN leads l ON e.lead_id = l.id",
                    "LEFT JOIN campaigns c ON e.campaign_id = c.id",
                ])
                where_clauses.append(
                    "(e.subject LIKE ? OR e.body LIKE ? OR l.name LIKE ? OR l.email LIKE ? OR c.name LIKE ?)"
                )
                q_like = f"%{q}%"
                params.extend([q_like, q_like, q_like, q_like, q_like])
            if campaign_name:
                if not any("campaigns c" in join for join in joins):
                    joins.append("LEFT JOIN campaigns c ON e.campaign_id = c.id")
                where_clauses.append("c.name = ?")
                params.append(campaign_name)
            if lead_email:
                if not any("leads l" in join for join in joins):
                    joins.append("JOIN leads l ON e.lead_id = l.id")
                where_clauses.append("l.email = ?")
                params.append(lead_email)
            where_sql = " AND ".join(where_clauses)

        with timed_step(request, "drafts.count_query"):
            with get_conn() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) AS count "
                    "FROM email_messages e "
                    f"{' '.join(joins)} "
                    f"WHERE {where_sql}",
                    tuple(params),
                ).fetchone()
        return {"count": int(row["count"] if row else 0)}
    except Exception as e:
        logger.error(f"Failed to count drafts: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class DraftApprovalRequest(BaseModel):
    model_config = {"extra": "forbid"}

    approved: bool
    approval_id: Optional[str] = None
    scheduled_send_at: Optional[str] = None


class DraftUpdateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    subject: str
    body: str


class DraftAttachmentCreate(BaseModel):
    model_config = {"extra": "forbid"}

    filename: str
    content_type: Optional[str] = None
    content_base64: str


class DraftAttachmentRequest(BaseModel):
    model_config = {"extra": "forbid"}

    attachments: List[DraftAttachmentCreate]


@app.put("/api/drafts/{draft_id}")
async def update_draft(
    draft_id: int,
    request: DraftUpdateRequest,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Update a pending draft before human approval."""
    try:
        actor_id = str(user.get("sub") or user.get("id") or "")
        resolved_org_id = _workflow_org_id(user, organization_id, tenant_service.WORKFLOW_ROLES)
        result = draft_service.update_draft_content(
            draft_id,
            request.subject,
            request.body,
            actor_id,
            resolved_org_id,
        )
        if result["status"] == "permission_denied":
            raise HTTPException(status_code=403, detail=result.get("error"))
        if result["status"] == "validation_error":
            raise HTTPException(status_code=400, detail=result.get("error"))
        if result["status"] == "not_found":
            raise HTTPException(status_code=404, detail="Draft not found or already processed")
        return {"status": "success", "draft": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update draft {draft_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/drafts/{draft_id}/attachments")
async def add_draft_attachments(
    draft_id: int,
    request: DraftAttachmentRequest,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Attach one or more files to a pending draft before approval."""
    try:
        actor_id = str(user.get("sub") or user.get("id") or "")
        resolved_org_id = _workflow_org_id(user, organization_id, tenant_service.WORKFLOW_ROLES)
        result = draft_service.add_draft_attachments(
            draft_id,
            [attachment.model_dump() for attachment in request.attachments],
            actor_id,
            resolved_org_id,
        )
        if result["status"] == "permission_denied":
            raise HTTPException(status_code=403, detail=result.get("error"))
        if result["status"] == "validation_error":
            raise HTTPException(status_code=400, detail=result.get("error"))
        if result["status"] == "not_found":
            raise HTTPException(status_code=404, detail="Draft not found or already processed")
        return {"status": "success", "result": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to add attachments for draft {draft_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/drafts/{draft_id}/attachments/{attachment_id}")
async def delete_draft_attachment(
    draft_id: int,
    attachment_id: int,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Remove an attachment from a pending draft."""
    try:
        actor_id = str(user.get("sub") or user.get("id") or "")
        resolved_org_id = _workflow_org_id(user, organization_id, tenant_service.WORKFLOW_ROLES)
        result = draft_service.delete_draft_attachment(draft_id, attachment_id, actor_id, resolved_org_id)
        if result["status"] == "permission_denied":
            raise HTTPException(status_code=403, detail=result.get("error"))
        if result["status"] == "not_found":
            raise HTTPException(status_code=404, detail="Draft not found or already processed")
        if result["status"] == "attachment_not_found":
            raise HTTPException(status_code=404, detail="Attachment not found")
        return {"status": "success", "result": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete attachment {attachment_id} for draft {draft_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/drafts/{draft_id}/approve")
async def approve_draft(
    draft_id: int,
    request: Request,
    approval_request: DraftApprovalRequest,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Approve or reject a pending email draft. For WhatsApp/LinkedIn drafts use /mark-sent instead."""
    try:
        actor_id = str(user.get("sub") or user.get("id") or "")
        with timed_step(request, "tenant.resolve_org"):
            resolved_org_id = _workflow_org_id(user, organization_id, tenant_service.WORKFLOW_ROLES)
        # Guard: non-email channels must use /mark-sent, not /approve
        from utils.db_connection import get_conn
        with get_conn() as conn:
            draft_row = conn.execute(
                "SELECT channel FROM email_messages WHERE id = ? AND organization_id = ? AND UPPER(status) = 'DRAFT'",
                (draft_id, resolved_org_id),
            ).fetchone()
        if draft_row and draft_row["channel"] in ("whatsapp", "linkedin"):
            raise HTTPException(
                status_code=400,
                detail=f"This is a {draft_row['channel']} draft. Use POST /api/drafts/{draft_id}/mark-sent after sending manually.",
            )
        with timed_step(
            request,
            "drafts.approve",
            approved=approval_request.approved,
            schedule_requested=bool((approval_request.scheduled_send_at or "").strip()),
        ):
            result = await draft_service.approve_draft(
                draft_id,
                approval_request.approved,
                actor_id,
                scheduled_send_at=approval_request.scheduled_send_at,
                organization_id=resolved_org_id,
            )
        if result["status"] == "permission_denied":
            raise HTTPException(status_code=403, detail=result.get("error"))
        if result["status"] == "validation_error":
            raise HTTPException(status_code=400, detail=result.get("error"))
        if result["status"] == "not_found":
            raise HTTPException(status_code=404, detail="Draft not found or already processed")
        if result["status"] == "send_failed":
            logger.warning(
                "Draft approval send failed",
                extra={
                    "kind": "draft_approval_send_failed",
                    "component": "drafts",
                    "data": {
                        "draft_id": draft_id,
                        "organization_id": resolved_org_id,
                        "error": result.get("error"),
                    },
                },
            )
            raise HTTPException(status_code=500, detail=f"Failed to send email: {result.get('error')}")
        return {
            "status": "success",
            "message": (
                "Draft approved and scheduled"
                if result.get("status") == "approved_scheduled"
                else "Draft approved and sent"
                if approval_request.approved
                else "Draft rejected"
            ),
            "approval_id": result.get("approval_id"),
            "scheduled_send_at": result.get("scheduled_send_at"),
        }
                
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to process draft approval: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class MarkSentRequest(BaseModel):
    model_config = {"extra": "forbid"}


@app.post("/api/drafts/{draft_id}/mark-sent")
async def mark_draft_sent(
    draft_id: int,
    request: Request,
    _body: MarkSentRequest = MarkSentRequest(),
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Mark a WhatsApp or LinkedIn draft as manually sent by the SDR.

    Updates the draft status to SENT, records the touch, and updates the lead
    status. Does NOT send any email — the SDR has already sent the message
    natively via the deep link.
    """
    try:
        import datetime as _datetime
        from utils.db_connection import get_conn
        actor_id = str(user.get("sub") or user.get("id") or "unknown")
        resolved_org_id = _workflow_org_id(user, organization_id, tenant_service.WORKFLOW_ROLES)
        now = _datetime.datetime.now(_datetime.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        with get_conn() as conn:
            row = conn.execute(
                "SELECT id, lead_id, campaign_id, channel, status "
                "FROM email_messages "
                "WHERE id = ? AND organization_id = ? AND UPPER(status) = 'DRAFT' AND approved = 0",
                (draft_id, resolved_org_id),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Draft not found or already processed")
            if row["channel"] not in ("whatsapp", "linkedin"):
                raise HTTPException(
                    status_code=400,
                    detail="/mark-sent is only for WhatsApp and LinkedIn drafts. Use /approve for email drafts.",
                )
            with conn:
                conn.execute(
                    "UPDATE email_messages "
                    "SET status = 'SENT', approved = 1, approved_by = ?, approved_at = ?, sent_at = ? "
                    "WHERE id = ?",
                    (actor_id, now, now, draft_id),
                )
            lead_id = row["lead_id"]
            campaign_id = row["campaign_id"]
        # Update touch count and lead status outside the db context manager
        try:
            lead_service.update_lead_touch(lead_id, campaign_id)
            lead_data = lead_service.get_lead(lead_id)
            if lead_data and (lead_data.get("status") or "").upper() in {"NEW", "COLD", ""}:
                lead_service.update_lead_status(lead_id, "CONTACTED")
        except Exception as exc:
            logger.warning("mark-sent: failed to update lead touch/status: %s", exc)
        logger.info(
            "Draft marked as manually sent",
            extra={
                "kind": "draft_mark_sent",
                "component": "drafts",
                "data": {"draft_id": draft_id, "lead_id": lead_id, "channel": row["channel"], "actor_id": actor_id},
            },
        )
        return {"status": "success", "message": f"Draft #{draft_id} marked as sent.", "channel": row["channel"]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to mark draft as sent: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class BatchDraftApprovalRequest(BaseModel):
    model_config = {"extra": "forbid"}

    draft_ids: List[int]
    approved: bool
    scheduled_send_at: Optional[str] = None


@app.post("/api/drafts/batch-approve")
async def batch_approve_drafts(
    request: BatchDraftApprovalRequest,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Approve or reject many drafts in one call."""
    try:
        actor_id = str(user.get("sub") or user.get("id") or "")
        resolved_org_id = _workflow_org_id(user, organization_id, tenant_service.WORKFLOW_ROLES)
        result = await draft_service.batch_approve_drafts(
            request.draft_ids,
            request.approved,
            actor_id,
            scheduled_send_at=request.scheduled_send_at,
            organization_id=resolved_org_id,
        )
        if result["status"] == "permission_denied":
            raise HTTPException(status_code=403, detail=result.get("error"))
        if result["status"] == "validation_error":
            raise HTTPException(status_code=400, detail=result.get("error"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed batch draft approval: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/drafts/{draft_id}")
async def delete_draft(
    draft_id: int,
    stop_future_attempts: bool = True,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Delete one pending draft and optionally stop future attempts for that lead in the campaign."""
    try:
        actor_id = str(user.get("sub") or user.get("id") or "")
        resolved_org_id = _workflow_org_id(user, organization_id, tenant_service.WORKFLOW_ROLES)
        result = draft_service.delete_draft(draft_id, stop_future_attempts, actor_id, resolved_org_id)
        if result["status"] == "permission_denied":
            raise HTTPException(status_code=403, detail=result.get("error"))
        if result["status"] == "not_found":
            raise HTTPException(status_code=404, detail="Draft not found or already processed")
        return {"status": "success", "result": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete draft {draft_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class BatchDraftDeleteRequest(BaseModel):
    model_config = {"extra": "forbid"}

    draft_ids: List[int]
    stop_future_attempts: bool = True


@app.post("/api/drafts/batch-delete")
async def batch_delete_drafts(
    request: BatchDraftDeleteRequest,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Delete many pending drafts and optionally stop future attempts."""
    try:
        actor_id = str(user.get("sub") or user.get("id") or "")
        resolved_org_id = _workflow_org_id(user, organization_id, tenant_service.WORKFLOW_ROLES)
        result = draft_service.batch_delete_drafts(
            request.draft_ids,
            request.stop_future_attempts,
            actor_id,
            resolved_org_id,
        )
        if result["status"] == "permission_denied":
            raise HTTPException(status_code=403, detail=result.get("error"))
        if result["status"] == "validation_error":
            raise HTTPException(status_code=400, detail=result.get("error"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed batch draft delete: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class SendDueRequest(BaseModel):
    model_config = {"extra": "forbid"}

    limit: int = 50


class MailboxSyncDueRequest(BaseModel):
    model_config = {"extra": "forbid"}

    limit: Optional[int] = None
    mailbox_id: Optional[int] = None
    mark_seen: Optional[bool] = None
    wait: Optional[bool] = None


class ScheduledEmailUpdateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    subject: str
    body: str
    scheduled_send_at: str


@app.get("/api/scheduled-emails")
async def list_scheduled_emails(
    user: dict = Depends(get_current_user),
    limit: int = 100,
    organization_id: Optional[int] = None,
):
    """List approved scheduled emails waiting to be sent."""
    try:
        from utils.db_connection import get_conn, sql_order_by_datetime

        resolved_org_id = _org_id(user, organization_id, tenant_service.READ_ROLES)
        order_scheduled = sql_order_by_datetime("e.scheduled_send_at")
        with get_conn() as conn:
            rows = [
                dict(row)
                for row in conn.execute(
                    "SELECT e.id, e.subject, e.body, e.scheduled_send_at, e.created_at, "
                    "e.send_attempts, e.last_error, e.approved_by, e.approved_at, "
                    "l.name AS lead_name, l.email AS lead_email, COALESCE(c.name, 'No campaign') AS campaign_name "
                    "FROM email_messages e "
                    "JOIN leads l ON e.lead_id = l.id "
                    "LEFT JOIN campaigns c ON e.campaign_id = c.id "
                    "WHERE e.organization_id = ? AND e.direction = 'outbound' AND UPPER(e.status) = 'SCHEDULED' AND e.approved = 1 "
                    f"ORDER BY {order_scheduled} ASC LIMIT ?",
                    (resolved_org_id, max(1, min(limit, 500))),
                ).fetchall()
            ]
        return {"scheduled": rows}
    except Exception as e:
        logger.error(f"Failed to list scheduled emails: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/scheduled-emails/{draft_id}")
async def update_scheduled_email(
    draft_id: int,
    request: ScheduledEmailUpdateRequest,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Edit subject/body/time for an approved scheduled email before it sends."""
    actor_id = str(user.get("sub") or user.get("id") or "")
    resolved_org_id = _workflow_org_id(user, organization_id, tenant_service.WORKFLOW_ROLES)
    result = draft_service.update_scheduled_draft(
        draft_id,
        request.subject,
        request.body,
        request.scheduled_send_at,
        actor_id,
        resolved_org_id,
    )
    if result["status"] == "permission_denied":
        raise HTTPException(status_code=403, detail=result.get("error"))
    if result["status"] == "validation_error":
        raise HTTPException(status_code=400, detail=result.get("error"))
    if result["status"] == "not_found":
        raise HTTPException(status_code=404, detail="Scheduled email not found or already processed")
    return {"status": "success", "scheduled": result}


@app.post("/api/scheduled-emails/{draft_id}/return-to-review")
async def return_scheduled_email_to_review(
    draft_id: int,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Move a scheduled email back to Draft Approvals."""
    actor_id = str(user.get("sub") or user.get("id") or "")
    resolved_org_id = _workflow_org_id(user, organization_id, tenant_service.WORKFLOW_ROLES)
    result = draft_service.return_scheduled_draft_to_review(draft_id, actor_id, resolved_org_id)
    if result["status"] == "permission_denied":
        raise HTTPException(status_code=403, detail=result.get("error"))
    if result["status"] == "not_found":
        raise HTTPException(status_code=404, detail="Scheduled email not found or already processed")
    return {"status": "success", "result": result}


@app.post("/api/scheduled-emails/send-due")
async def send_due_scheduled_emails(
    request: SendDueRequest,
    user: dict = Depends(get_current_user_or_cron),
    organization_id: Optional[int] = None,
):
    """Send approved scheduled emails whose scheduled time has arrived."""
    actor_id = str(user.get("sub") or user.get("id") or "scheduler")
    resolved_org_id = None
    if not user.get("cron") or organization_id is not None:
        resolved_org_id = _workflow_org_id(user, organization_id, tenant_service.WORKFLOW_ROLES)
    if user.get("cron") and resolved_org_id is None:
        return await _send_due_scheduled_for_active_organizations(request.limit, actor_id=actor_id)
    return await draft_service.send_due_scheduled_drafts(
        limit=request.limit,
        actor_id=actor_id,
        organization_id=resolved_org_id,
    )


async def _run_due_mailbox_sync(
    request: MailboxSyncDueRequest,
    user: dict,
    organization_id: Optional[int],
) -> dict[str, Any]:
    if not user.get("cron") or organization_id is not None:
        resolved_org_id = _workflow_org_id(user, organization_id, tenant_service.WORKFLOW_ROLES)
        tenant_service.require_active_subscription(resolved_org_id)
        mailboxes = list_connected_imap_mailboxes(
            organization_id=resolved_org_id,
            mailbox_id=request.mailbox_id,
        )
    else:
        active_org_ids = set(tenant_service.list_active_subscription_organization_ids())
        mailboxes = [
            mailbox
            for mailbox in list_connected_imap_mailboxes(mailbox_id=request.mailbox_id)
            if int(mailbox["organization_id"]) in active_org_ids
        ]

    combined = {
        "status": "success",
        "mailboxes_checked": 0,
        "messages_checked": 0,
        "processed": 0,
        "skipped": 0,
        "errors": 0,
        "results": [],
    }
    requested_limit = request.limit if request.limit is not None else settings.mailbox_sync_default_limit
    mark_seen = request.mark_seen if request.mark_seen is not None else settings.mailbox_sync_mark_seen
    limit = max(1, min(requested_limit, 25))
    for mailbox in mailboxes:
        mailbox_id = int(mailbox["id"])
        org_id = int(mailbox["organization_id"])
        try:
            result = await sync_unread_mailbox(
                org_id,
                mailbox_id,
                limit=limit,
                mark_seen=mark_seen,
                callback=webhook_broadcaster.scoped(f"mailbox:{mailbox_id}", organization_id=org_id),
            )
        except Exception as exc:
            error = str(exc)
            auth_failed = "AUTHENTICATIONFAILED" in error.upper() or "AUTHENTICATION FAILED" in error.upper()
            record_mailbox_sync_failure(mailbox_id, error, disable=auth_failed)
            logger.exception(
                "Mailbox sync failed for mailbox",
                extra={
                    "kind": "mailbox_sync_mailbox_error",
                    "component": "mailbox",
                    "data": {
                        "organization_id": org_id,
                        "mailbox_id": mailbox_id,
                        "email_address": mailbox.get("email_address"),
                        "auth_failed": auth_failed,
                        "error": error,
                    },
                },
            )
            combined["mailboxes_checked"] += 1
            combined["errors"] += 1
            combined["results"].append(
                {
                    "mailbox_id": mailbox_id,
                    "checked": 0,
                    "processed": [],
                    "skipped": [],
                    "errors": [{"reason": error, "auth_failed": auth_failed}],
                }
            )
            continue
        combined["mailboxes_checked"] += 1
        combined["messages_checked"] += result.get("checked", 0)
        combined["processed"] += len(result.get("processed", []))
        combined["skipped"] += len(result.get("skipped", []))
        combined["errors"] += len(result.get("errors", []))
        combined["results"].append(result)
    return combined


async def _run_due_mailbox_sync_background(
    request: MailboxSyncDueRequest,
    user: dict,
    organization_id: Optional[int],
) -> None:
    try:
        result = await _run_due_mailbox_sync(request, user, organization_id)
        logger.info(
            "Background mailbox sync completed",
            extra={
                "kind": "mailbox_sync_background_complete",
                "component": "mailbox",
                "data": {
                    "mailboxes_checked": result.get("mailboxes_checked"),
                    "messages_checked": result.get("messages_checked"),
                    "processed": result.get("processed"),
                    "skipped": result.get("skipped"),
                    "errors": result.get("errors"),
                },
            },
        )
    except Exception as exc:
        logger.exception(
            "Background mailbox sync failed",
            extra={
                "kind": "mailbox_sync_background_error",
                "component": "mailbox",
                "data": {"error": str(exc)},
            },
        )


async def _mailbox_sync_loop() -> None:
    interval = settings.mailbox_sync_interval_seconds
    initial_delay = settings.mailbox_sync_initial_delay_seconds
    request = MailboxSyncDueRequest(
        limit=settings.mailbox_sync_default_limit,
        mark_seen=settings.mailbox_sync_mark_seen,
        wait=True,
    )
    cron_user = {"cron": True, "sub": "mailbox-sync"}
    logger.info(
        "Mailbox sync poller started",
        extra={
            "kind": "mailbox_sync_poller_started",
            "component": "mailbox",
            "data": {
                "interval_seconds": interval,
                "limit": request.limit,
                "mark_seen": request.mark_seen,
                "initial_delay_seconds": initial_delay,
            },
        },
    )
    if initial_delay > 0:
        await asyncio.sleep(initial_delay)
    while True:
        try:
            result = await _run_due_mailbox_sync(request, cron_user, organization_id=None)
            if result.get("processed", 0) > 0 or result.get("errors", 0) > 0:
                logger.info(
                    "Mailbox sync poller processed due replies",
                    extra={
                        "kind": "mailbox_sync_poller_tick",
                        "component": "mailbox",
                        "data": {
                            "mailboxes_checked": result.get("mailboxes_checked"),
                            "messages_checked": result.get("messages_checked"),
                            "processed": result.get("processed"),
                            "skipped": result.get("skipped"),
                            "errors": result.get("errors"),
                        },
                    },
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "Mailbox sync poller failed",
                extra={
                    "kind": "mailbox_sync_poller_error",
                    "component": "mailbox",
                    "data": {"error": str(exc)},
                },
            )
        await asyncio.sleep(interval)


@app.on_event("startup")
async def start_mailbox_sync_poller() -> None:
    global _mailbox_sync_task
    if not settings.mailbox_sync_enabled:
        logger.info(
            "Mailbox sync poller disabled",
            extra={"kind": "mailbox_sync_poller_disabled", "component": "mailbox"},
        )
        return
    if _mailbox_sync_task and not _mailbox_sync_task.done():
        return
    _mailbox_sync_task = asyncio.create_task(_mailbox_sync_loop())


@app.on_event("shutdown")
async def stop_mailbox_sync_poller() -> None:
    global _mailbox_sync_task
    if not _mailbox_sync_task:
        return
    _mailbox_sync_task.cancel()
    try:
        await _mailbox_sync_task
    except asyncio.CancelledError:
        logger.info(
            "Mailbox sync poller stopped",
            extra={"kind": "mailbox_sync_poller_stopped", "component": "mailbox"},
        )
    finally:
        _mailbox_sync_task = None


@app.post("/api/mailboxes/sync-due")
async def sync_due_mailboxes(
    request: MailboxSyncDueRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user_or_cron),
    organization_id: Optional[int] = None,
):
    """Poll connected SMTP/IMAP mailboxes for unread replies.

    This gives production schedulers a cron-secret protected equivalent of the
    UI-triggered mailbox sync endpoint. Use wait=false for manual/cron triggers
    that should enqueue the sync and return before LLM processing completes.
    """
    wait = request.wait if request.wait is not None else settings.mailbox_sync_wait
    if not wait:
        background_tasks.add_task(_run_due_mailbox_sync_background, request, user, organization_id)
        return {
            "status": "accepted",
            "message": "Mailbox sync started in background",
            "mailbox_id": request.mailbox_id,
            "limit": max(1, min(request.limit or settings.mailbox_sync_default_limit, 25)),
        }
    return await _run_due_mailbox_sync(request, user, organization_id)


class SequenceStepRequest(BaseModel):
    model_config = {"extra": "forbid"}

    step_number: int
    delay_days: int
    subject_template: str = ""
    body_template: str = ""
    active: bool = True
    channel: str = "email"   # email | linkedin | whatsapp
    prompt_context: Optional[str] = None


class SequenceReplaceRequest(BaseModel):
    model_config = {"extra": "forbid"}

    steps: List[SequenceStepRequest]


@app.get("/api/campaigns/{campaign_id}/sequence")
async def get_campaign_sequence(
    campaign_id: int,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Return follow-up sequence steps for a campaign, merging omnichannel metadata."""
    try:
        resolved_org_id = _org_id(user, organization_id, tenant_service.READ_ROLES)
        with __import__("utils.db_connection", fromlist=["get_conn"]).get_conn() as conn:
            row = conn.execute(
                "SELECT id FROM campaigns WHERE id = ? AND organization_id = ?",
                (campaign_id, resolved_org_id),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="campaign not found")
        base_steps = sequence_service.ensure_default_steps(campaign_id)
        # Merge channel + prompt_context from campaign_sequences
        with __import__("utils.db_connection", fromlist=["get_conn"]).get_conn() as conn:
            seq_rows = conn.execute(
                "SELECT step_number, channel, delay_days, prompt_context FROM campaign_sequences WHERE campaign_id = ?",
                (campaign_id,)
            ).fetchall()
        seq_map = {r["step_number"]: dict(r) for r in seq_rows} if seq_rows else {}
        merged = []
        for step in base_steps:
            sn = step.get("step_number")
            extra = seq_map.get(sn, {})
            merged.append({
                **step,
                "channel": extra.get("channel", "email"),
                "prompt_context": extra.get("prompt_context", ""),
            })
        return {"campaign_id": campaign_id, "steps": merged}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to load campaign sequence: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/campaigns/{campaign_id}/sequence")
async def replace_campaign_sequence(
    campaign_id: int,
    request: SequenceReplaceRequest,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Replace follow-up sequence steps for a campaign, including omnichannel metadata."""
    try:
        resolved_org_id = _workflow_org_id(user, organization_id, tenant_service.WORKFLOW_ROLES)
        VALID_CHANNELS = {"email", "linkedin", "whatsapp"}
        for step in request.steps:
            if step.channel not in VALID_CHANNELS:
                raise ValueError(f"Invalid channel '{step.channel}'. Must be one of: {', '.join(VALID_CHANNELS)}")
        steps = sequence_service.replace_sequence_steps(
            campaign_id,
            [step.model_dump() for step in request.steps],
            resolved_org_id,
        )
        # Also sync to campaign_sequences table for orchestrator
        with __import__("utils.db_connection", fromlist=["get_conn"]).get_conn() as conn:
            with conn:
                conn.execute("DELETE FROM campaign_sequences WHERE campaign_id = ?", (campaign_id,))
                for step in request.steps:
                    conn.execute(
                        "INSERT INTO campaign_sequences (campaign_id, step_number, channel, delay_days, prompt_context) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (campaign_id, step.step_number, step.channel, step.delay_days, step.prompt_context or None)
                    )
        # Return steps enriched with channel/prompt_context
        enriched = [
            {
                **s,
                "channel": req.channel,
                "prompt_context": req.prompt_context or "",
            }
            for s, req in zip(steps, sorted(request.steps, key=lambda x: x.step_number))
        ]
        return {"status": "success", "campaign_id": campaign_id, "steps": enriched}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to update campaign sequence: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class FollowupGenerateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    campaign_id: Optional[int] = None
    limit: int = 50


@app.get("/api/followups/upcoming")
async def list_upcoming_followups(
    campaign_id: Optional[int] = None,
    limit: int = 100,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """List upcoming and due follow-up sequence candidates without creating drafts."""
    try:
        resolved_org_id = _org_id(user, organization_id, tenant_service.READ_ROLES)
        return sequence_service.list_upcoming_followups(campaign_id=campaign_id, limit=limit, organization_id=resolved_org_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to list upcoming follow-ups: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/followups/generate-due")
async def generate_due_followups(
    request: FollowupGenerateRequest,
    user: dict = Depends(get_current_user_or_cron),
    organization_id: Optional[int] = None,
):
    """Create reviewable follow-up drafts for leads whose next sequence step is due."""
    try:
        resolved_org_id = None
        if not user.get("cron") or organization_id is not None:
            resolved_org_id = _workflow_org_id(user, organization_id, tenant_service.WORKFLOW_ROLES)
        if user.get("cron") and resolved_org_id is None:
            combined = {"status": "success", "generated": 0, "skipped": 0, "drafts": []}
            remaining = max(1, min(request.limit, 500))
            for org_id in tenant_service.list_active_subscription_organization_ids():
                if remaining <= 0:
                    break
                result = sequence_service.generate_due_followup_drafts(
                    campaign_id=request.campaign_id,
                    limit=remaining,
                    organization_id=org_id,
                )
                combined["generated"] += result.get("generated", 0)
                combined["skipped"] += result.get("skipped", 0)
                combined["drafts"].extend(result.get("drafts", []))
                remaining -= result.get("generated", 0)
            await outbound_event_service.emit_event("followup_drafts_generated", combined)
            return combined
        result = sequence_service.generate_due_followup_drafts(
            campaign_id=request.campaign_id,
            limit=request.limit,
            organization_id=resolved_org_id,
        )
        await outbound_event_service.emit_event("followup_drafts_generated", result)
        return result
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to generate follow-up drafts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _csv_stream(rows: list[dict[str, Any]], filename: str) -> StreamingResponse:
    buffer = io.StringIO()
    fieldnames = sorted({key for row in rows for key in row.keys()})
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/leads/export.csv")
async def export_leads_csv(user: dict = Depends(get_current_user), organization_id: Optional[int] = None):
    """Export leads and campaign assignment context as CSV."""
    try:
        from utils.db_connection import get_conn, sql_group_concat_distinct

        gcat_names = sql_group_concat_distinct("c.name")
        gcat_ids = sql_group_concat_distinct("c.id")
        resolved_org_id = _org_id(user, organization_id, tenant_service.READ_ROLES)
        with get_conn() as conn:
            rows = [
                dict(row)
                for row in conn.execute(
                    "SELECT l.id, l.email, l.name, l.company, l.industry, l.pain_points, l.status, "
                    "l.email_opt_out, l.touch_count, l.last_contacted_at, l.last_inbound_at, l.created_at, "
                    f"{gcat_names} AS campaigns, {gcat_ids} AS campaign_ids "
                    "FROM leads l "
                    "LEFT JOIN campaign_leads cl ON cl.lead_id = l.id "
                    "LEFT JOIN campaigns c ON c.id = cl.campaign_id "
                    "WHERE l.organization_id = ? GROUP BY l.id ORDER BY l.id DESC",
                    (resolved_org_id,),
                ).fetchall()
            ]
        return _csv_stream(rows, "leads-export.csv")
    except Exception as e:
        logger.error(f"Failed to export leads: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/campaigns/{campaign_id}/results/export.csv")
async def export_campaign_results_csv(
    campaign_id: int,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Export campaign lead and outbound-message results as CSV."""
    try:
        from utils.db_connection import get_conn

        resolved_org_id = _org_id(user, organization_id, tenant_service.READ_ROLES)
        with get_conn() as conn:
            rows = [
                dict(row)
                for row in conn.execute(
                    "SELECT c.id AS campaign_id, c.name AS campaign_name, l.id AS lead_id, l.email, l.name, "
                    "l.company, l.status AS lead_status, cl.emails_sent, cl.responded, cl.meeting_booked, "
                    "em.id AS email_id, em.subject, em.status AS email_status, em.approved, "
                    "em.scheduled_send_at, em.sent_at, em.created_at AS email_created_at "
                    "FROM campaigns c "
                    "JOIN campaign_leads cl ON cl.campaign_id = c.id "
                    "JOIN leads l ON l.id = cl.lead_id "
                    "LEFT JOIN email_messages em ON em.campaign_id = c.id AND em.lead_id = l.id "
                    "WHERE c.id = ? AND c.organization_id = ? ORDER BY l.id DESC, em.id DESC",
                    (campaign_id, resolved_org_id),
                ).fetchall()
            ]
        return _csv_stream(rows, f"campaign-{campaign_id}-results.csv")
    except Exception as e:
        logger.error(f"Failed to export campaign results: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class OutboundWebhookCreate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str
    target_url: str
    event_types: List[str] = ["all"]
    secret: Optional[str] = None
    active: bool = True


@app.get("/api/webhooks/outbound")
async def list_outbound_webhooks(user: dict = Depends(get_current_user)):
    return {"webhooks": outbound_event_service.list_webhooks()}


@app.post("/api/webhooks/outbound")
async def create_outbound_webhook(request: OutboundWebhookCreate, user: dict = Depends(get_current_user)):
    try:
        webhook = outbound_event_service.create_webhook(request.model_dump())
        return {"status": "success", "webhook": webhook}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/webhooks/outbound/deliveries")
async def list_outbound_webhook_deliveries(user: dict = Depends(get_current_user), limit: int = 100):
    return {"deliveries": outbound_event_service.recent_deliveries(limit=limit)}


@app.delete("/api/webhooks/outbound/{webhook_id}")
async def delete_outbound_webhook(webhook_id: int, user: dict = Depends(get_current_user)):
    if not outbound_event_service.delete_webhook(webhook_id):
        raise HTTPException(status_code=404, detail="Webhook not found")
    return {"status": "success"}


class CrmImportRequest(BaseModel):
    model_config = {"extra": "forbid"}

    provider: Optional[str] = None
    limit: int = 100
    campaign_ids: List[int] = []
    upsert: bool = True


@app.post("/api/integrations/crm/import")
async def import_from_crm(
    request: CrmImportRequest,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Fetch CRM contacts and import them into the lead pipeline."""
    try:
        leads = await crm_service.fetch_crm_leads(provider=request.provider, limit=request.limit)
        resolved_org_id = _workflow_org_id(user, organization_id, tenant_service.WORKFLOW_ROLES)
        result = lead_service.bulk_import_leads(
            leads,
            campaign_ids=request.campaign_ids,
            upsert=request.upsert,
            source=f"crm:{request.provider or settings.crm_provider or 'hubspot'}",
            organization_id=resolved_org_id,
        )
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])
        await outbound_event_service.emit_event("leads_imported", result["data"])
        return result["data"]
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to import from CRM: {e}")
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/analytics/summary")
async def get_analytics_summary(user: dict = Depends(get_current_user), organization_id: Optional[int] = None):
    resolved_org_id = _org_id(user, organization_id, tenant_service.READ_ROLES)
    return analytics_service.summary(resolved_org_id)


@app.get("/api/audit/events")
async def list_audit_events(
    user: dict = Depends(get_current_user),
    limit: int = 100,
    event_type: Optional[str] = None,
    organization_id: Optional[int] = None,
):
    """List durable business audit events. Restricted to platform system owners."""
    try:
        tenant_service.require_system_owner(user)
        resolved_org_id = _org_id(user, organization_id, tenant_service.READ_ROLES) if organization_id else None
        return {"events": audit_service.list_events(limit=limit, event_type=event_type, organization_id=resolved_org_id)}
    except Exception as e:
        _raise_service_error(e)


@app.get("/api/audit/streams")
async def list_audit_streams(user: dict = Depends(get_current_user)):
    """Describe available log/audit streams and role access."""
    try:
        tenant_service.ensure_app_user(user)
        return {
            "streams": audit_service.list_log_streams(),
            "roles": audit_service.role_access_matrix(),
        }
    except Exception as e:
        _raise_service_error(e)

@app.get("/api/outreach/stream")
async def stream_outreach(
    campaign_name: Optional[str] = None,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Execute campaign and stream progress via SSE."""
    async def event_generator():
        try:
            resolved_org_id = _workflow_org_id(user, organization_id, tenant_service.WORKFLOW_ROLES)
            terminal_sent = False
            # Helper to yield SSE events
            async def sse_callback(status: str, message: str):
                nonlocal terminal_sent
                if status in {"success", "error"}:
                    terminal_sent = True
                data = json.dumps({"status": status, "message": message})
                # Note: We need to use a non-blocking yield here, but since this is 
                # called from within the orchestrator, we'll use a queue or 
                # just yield directly if possible.
                # For this implementation, we'll use a simple queue to bridge 
                # the orchestrator and the generator.
                await queue.put(f"data: {data}\n\n")

            queue = asyncio.Queue()
            
            # Start orchestrator in a background task
            task = asyncio.create_task(
                outreach_orchestrator.execute_campaign(
                    campaign_name=campaign_name, 
                    organization_id=resolved_org_id,
                    callback=sse_callback
                )
            )

            # Yield events from the queue until the task is done
            while not task.done() or not queue.empty():
                try:
                    # Wait for an event with a timeout to check task status
                    event = await asyncio.wait_for(queue.get(), timeout=0.1)
                    yield event
                except asyncio.TimeoutError:
                    continue
            
            # Final check for exceptions
            if task.exception():
                raise task.exception()
            result = task.result()
            if not terminal_sent:
                status = "success" if result.get("success") else "error"
                message = result.get("message") or result.get("error") or "Outreach run finished."
                yield f"data: {json.dumps({'status': status, 'message': message})}\n\n"
                
        except Exception as e:
            logger.error(f"Streaming outreach failed: {e}")
            yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/outreach/campaign")  
@observe()
async def execute_marketing_campaign(
    background_tasks: BackgroundTasks,
    campaign_name: Optional[str] = None,
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
) -> dict:
    """Execute intelligent outreach campaign via Orchestrator (database-driven)."""
    try:
        resolved_org_id = _workflow_org_id(user, organization_id, tenant_service.WORKFLOW_ROLES)
        background_tasks.add_task(outreach_orchestrator.execute_campaign, campaign_name, resolved_org_id)
        return {
            "status": "accepted", 
            "message": f"Campaign execution started in background for {campaign_name or 'random active campaign'}"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Marketing campaign failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/webhooks/stream")
async def stream_webhooks(
    user: dict = Depends(get_current_user),
    organization_id: Optional[int] = None,
):
    """Stream incoming webhook processing logs via SSE."""
    resolved_org_id = _org_id(user, organization_id, tenant_service.READ_ROLES) if organization_id is not None else None
    queue: asyncio.Queue = asyncio.Queue(maxsize=256)
    connection = {"queue": queue, "organization_id": resolved_org_id}
    webhook_broadcaster.connections.append(connection)
    
    async def event_generator():
        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield f"data: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    # Keep-alive ping
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if connection in webhook_broadcaster.connections:
                webhook_broadcaster.connections.remove(connection)
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")


# Email monitoring endpoints
@app.post("/webhook")
async def handle_webhook(request: Request) -> Dict[str, Any]:
    """Handle AgentMail webhook events (received messages only) with simplified loop prevention."""
    try:
        # Validate webhook secret when configured
        if settings.webhook_secret:
            sig = request.headers.get("x-webhook-signature", "")
            raw_body = await request.body()
            expected = hmac.HMAC(
                settings.webhook_secret.encode(), raw_body, hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(sig, expected):
                logger.warning("Webhook signature mismatch - rejecting request")
                raise HTTPException(status_code=403, detail="Invalid webhook signature")
            payload = json.loads(raw_body)
        else:
            payload = await request.json()
        event = WebhookEvent(**payload)
        
        sender_email = extract_sender_email(event.message)
        sender_name = extract_sender_name(event.message)
        subject = extract_subject(event.message)
        logger.info(f"Received webhook: {event.event_id}")
        
        cb = webhook_broadcaster.scoped(event.event_id)
        await cb(
            "info",
            f"Received webhook: {event.event_type} - {event.event_id} | From: {sender_name} <{sender_email}> | Subject: {subject}"
        )
        
        # Simplified processing decision (webhooks are received-only)
        should_process, reason = await should_process_webhook(
            event.event_id, 
            event.event_type, 
            event.message,
            DEFAULT_LOOP_PREVENTION
        )
        
        if not should_process:
            logger.info(f"Skipping webhook {event.event_id}: {reason}")
            await cb("warning", f"Skipping webhook {event.event_id}: {reason}")
            return {"status": "skipped", "reason": reason, "event_id": event.event_id}
        
        # Process received message
        logger.info(f"Processing received message: {event.event_id}")
        await cb("info", f"Starting pipeline for message: {event.event_id}")
        
        result = await email_monitor.process_incoming_email(event.message, callback=cb)
        
        return {
            "status": "processed", 
            "event_id": event.event_id,
            "action": result.action_taken,
            "success": result.success,
            "message_id": result.message_id,
            "error": result.error
        }
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        await webhook_broadcaster.broadcast("error", f"Webhook error: {str(e)}", event_id=getattr(event, 'event_id', '') if 'event' in dir() else "")
        raise HTTPException(status_code=500, detail=str(e))


async def _process_resend_webhook(request: Request, mailbox_id: int | None = None) -> Dict[str, Any]:
    """Handle Resend webhook events and route received emails into the monitor."""
    event_id = ""
    organization_id = None
    try:
        raw_body = await request.body()
        api_key = None
        webhook_secret = None
        if mailbox_id is not None:
            mailbox = tenant_service.get_resend_webhook_mailbox(mailbox_id)
            api_key = tenant_service.decrypt_secret(mailbox.get("resend_api_key_secret"))
            webhook_secret = tenant_service.decrypt_secret(mailbox.get("resend_webhook_secret_secret"))
            organization_id = int(mailbox["organization_id"])
            if not webhook_secret:
                raise HTTPException(status_code=400, detail="Resend webhook secret is not configured for this mailbox")

        if not verify_resend_webhook_signature(raw_body, dict(request.headers), secret=webhook_secret):
            logger.warning("Resend webhook signature mismatch - rejecting request")
            raise HTTPException(status_code=403, detail="Invalid Resend webhook signature")

        payload = json.loads(raw_body)
        event_type = payload.get("type") or payload.get("event_type")
        event_id, message = normalize_resend_received_email(
            payload,
            api_key=api_key,
            organization_id=organization_id,
            mailbox_id=mailbox_id,
        )

        if event_type != "email.received":
            return {"status": "ignored", "event_id": event_id, "event_type": event_type}

        sender_email = extract_sender_email(message)
        sender_name = extract_sender_name(message)
        subject = extract_subject(message)
        cb = webhook_broadcaster.scoped(event_id, organization_id=organization_id)
        await cb(
            "info",
            f"Received Resend webhook: {event_id} | From: {sender_name} <{sender_email}> | Subject: {subject}",
        )

        should_process, reason = await should_process_webhook(
            event_id,
            "message.received",
            message,
            DEFAULT_LOOP_PREVENTION,
        )
        if not should_process:
            logger.info(f"Skipping Resend webhook {event_id}: {reason}")
            await cb("warning", f"Skipping webhook {event_id}: {reason}")
            return {"status": "skipped", "reason": reason, "event_id": event_id}

        result = await email_monitor.process_incoming_email(message, callback=cb)
        return {
            "status": "processed",
            "event_id": event_id,
            "action": result.action_taken,
            "success": result.success,
            "message_id": result.message_id,
            "error": result.error,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Resend webhook error: {e}")
        await webhook_broadcaster.broadcast(
            "error",
            f"Resend webhook error: {str(e)}",
            event_id=event_id,
            organization_id=organization_id,
        )
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/webhooks/email/resend")
async def handle_resend_webhook(request: Request) -> Dict[str, Any]:
    """Handle Resend webhooks using the global platform Resend config."""
    return await _process_resend_webhook(request)


@app.post("/webhooks/email/resend/{mailbox_id}")
async def handle_tenant_resend_webhook(mailbox_id: int, request: Request) -> Dict[str, Any]:
    """Handle Resend webhooks for a tenant-owned Resend mailbox."""
    return await _process_resend_webhook(request, mailbox_id=mailbox_id)


@app.get("/email-monitor/health")
async def email_monitor_health() -> Dict[str, str]:
    """Email monitor health check."""
    return {"status": "healthy", "service": "email_monitor"}


def _is_our_message(message_data: Dict[str, Any]) -> bool:
    """Legacy function - replaced by enhanced webhook_utils.is_our_outgoing_message()"""
    labels = message_data.get('labels', [])
    return 'sent' in labels
