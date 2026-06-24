"""Auth for NKZ Water Studio backend.

Trusts the api-gateway (which validates JWT vs Keycloak) and additionally
verifies the X-Auth-Signature HMAC it injects - fail-closed. This is the seal
that guarantees X-Tenant-ID was set by the gateway, not forged from inside the
cluster, and is what makes tenant isolation hermetic.

The SDK's require_auth() reads X-Tenant-ID / X-User-ID / X-User-Roles and yields
an AuthContext; we wrap it so the HMAC is enforced on the same request.
"""

from fastapi import HTTPException, Request, Depends

from nkz_platform_sdk import require_auth as _sdk_require_auth, AuthContext

from app.config import get_settings
from app.middleware.hmac import verify_gateway_hmac


def _bearer_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[len("Bearer "):]
    return request.headers.get("Cookie", "")  # best-effort; HMAC needs the raw token


def require_auth(roles=None):
    """FastAPI dependency: SDK header validation + gateway HMAC gate."""
    sdk_dep = _sdk_require_auth(roles)

    async def _dependency(ctx: AuthContext = sdk_dep, request: Request = None) -> AuthContext:
        # ctx is already AuthContext from the SDK (tenant_id/user_id/roles present).
        # Now enforce the HMAC signature.
        settings = get_settings()
        signature = request.headers.get("X-Auth-Signature", "")
        token = _bearer_token(request)
        if not verify_gateway_hmac(
            signature,
            token,
            ctx.tenant_id,
            secret=settings.hmac_secret,
            require=settings.require_hmac,
        ):
            # Silent 401 - no detail leaked (AGENTS: silent 401 for unsigned reqs).
            raise HTTPException(status_code=401, detail="Unauthorized")
        return ctx

    return Depends(_dependency)
