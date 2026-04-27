import os
import time
import httpx
import logging
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
            return payload
        except JWTError as e:
            logger.error(f"JWT verification failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during auth: {e}")
            return None

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
