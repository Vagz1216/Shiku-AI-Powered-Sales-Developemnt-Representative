import os
import time
import httpx
import logging
import threading
from typing import Optional, Dict, Any
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

CLERK_JWKS_URL = os.getenv("CLERK_JWKS_URL")
CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY")

JWKS_TTL_SECONDS = 3600  # re-fetch keys every hour

security = HTTPBearer(auto_error=False)

class ClerkAuth:
    def __init__(self):
        self.jwks: Optional[Dict[str, Any]] = None
        self._jwks_fetched_at: float = 0.0
        self._user_cache: dict[str, tuple[float, Dict[str, Any]]] = {}
        self._user_cache_lock = threading.Lock()

    async def get_jwks(self):
        now = time.time()
        if self.jwks is None or (now - self._jwks_fetched_at) > JWKS_TTL_SECONDS:
            if not CLERK_JWKS_URL:
                logger.error("CLERK_JWKS_URL not set")
                return None
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(CLERK_JWKS_URL)
                    self.jwks = response.json()
                    self._jwks_fetched_at = now
                    logger.info("JWKS refreshed from Clerk")
            except Exception as e:
                logger.error(f"Failed to refresh JWKS: {e}")
                if self.jwks is not None:
                    return self.jwks
                return None
        return self.jwks

    async def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        jwks = await self.get_jwks()
        if not jwks:
            return None

        try:
            # Get the kid from the token header
            unverified_header = jwt.get_unverified_header(token)
            kid = unverified_header.get("kid")
            
            # Find the correct key in JWKS
            key = next((k for k in jwks["keys"] if k["kid"] == kid), None)
            if not key:
                logger.error(f"No matching key found for kid: {kid}")
                return None

            # Verify the token
            payload = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                options={"verify_aud": False} # Clerk uses dynamic audiences sometimes
            )
            payload = await self.enrich_payload(payload)
            return payload
        except JWTError as e:
            logger.error(f"JWT verification failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during auth: {e}")
            return None

    async def enrich_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Populate email/name from Clerk when the session JWT omits them."""
        if payload.get("email") or not CLERK_SECRET_KEY or not payload.get("sub"):
            return payload

        from config.settings import settings

        user_id = str(payload["sub"])
        cache_ttl = settings.clerk_user_cache_ttl_seconds
        now = time.time()
        if cache_ttl > 0:
            with self._user_cache_lock:
                cached = self._user_cache.get(user_id)
                if cached and cached[0] > now:
                    payload.update(cached[1])
                    return payload
                if cached:
                    self._user_cache.pop(user_id, None)

        try:
            started = time.perf_counter()
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"https://api.clerk.com/v1/users/{user_id}",
                    headers={"Authorization": f"Bearer {CLERK_SECRET_KEY}"},
                )
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            if duration_ms > 1000:
                logger.warning(
                    "Slow Clerk user enrichment: %.2fms",
                    duration_ms,
                    extra={"kind": "external_dependency_slow", "component": "auth"},
                )
            if response.status_code >= 400:
                logger.warning("Could not enrich Clerk user payload: %s", response.status_code)
                return payload

            user_data = response.json()
            primary_id = user_data.get("primary_email_address_id")
            emails = user_data.get("email_addresses") or []
            primary = next((item for item in emails if item.get("id") == primary_id), None)
            primary = primary or (emails[0] if emails else None)
            email = primary.get("email_address") if primary else None
            if email:
                payload["email"] = email
            name = " ".join(
                part for part in [user_data.get("first_name"), user_data.get("last_name")] if part
            ).strip()
            if name:
                payload["name"] = name
            if cache_ttl > 0:
                profile = {k: payload[k] for k in ("email", "name") if payload.get(k)}
                if profile:
                    with self._user_cache_lock:
                        self._user_cache[user_id] = (time.time() + cache_ttl, profile)
        except Exception as e:
            logger.warning("Failed to enrich Clerk user payload: %s", e)
        return payload

clerk_auth = ClerkAuth()

async def get_current_user(request: Request, auth: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    token = None
    if auth:
        token = auth.credentials
    else:
        # Fallback to query parameter for SSE
        token = request.query_params.get("token")

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = await clerk_auth.verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


async def get_current_user_or_cron(
    request: Request,
    auth: Optional[HTTPAuthorizationCredentials] = Depends(security),
):
    """Allow either a Clerk user token or a trusted scheduler secret."""
    from config.settings import settings

    cron_secret = request.headers.get("X-Cron-Secret")
    if settings.cron_secret and cron_secret and cron_secret == settings.cron_secret:
        return {"sub": "scheduler", "email": None, "name": "Scheduler", "cron": True}
    return await get_current_user(request, auth)
