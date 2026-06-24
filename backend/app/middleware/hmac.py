"""Gateway HMAC signature verification.

The api-gateway (services/common/keycloak_auth.py) signs every proxied request:

    timestamp = str(int(time.time()))
    message   = f"{token}|{tenant_id}|{timestamp}"
    sig       = hmac_sha256(HMAC_SECRET, message).hexdigest()
    header    = f"{sig}:{timestamp}"

This module mirrors that verification exactly (300s window) and is FAIL-CLOSED:
if HMAC_SECRET is empty and require=True, every request is rejected. This differs
from the SDK default (fail-open) because here the HMAC is the seal that guarantees
the X-Tenant-ID was set by the gateway, not forged by a pod in the namespace.
"""

import hashlib
import hmac
import logging
import time

logger = logging.getLogger(__name__)

_SIGNATURE_WINDOW_SECONDS = 300


def verify_gateway_hmac(
    signature_header: str,
    token: str,
    tenant_id: str,
    *,
    secret: str,
    require: bool = True,
    now: int | None = None,
) -> bool:
    """Return True iff *signature_header* is a valid gateway signature.

    Fail-closed: empty *secret* with require=True -> False.
    """
    if not secret:
        if require:
            logger.error("HMAC secret missing while require=True - rejecting (fail-closed)")
            return False
        return True  # validation disabled, not required

    if not signature_header or ":" not in signature_header:
        return False

    provided, _, ts_str = signature_header.partition(":")
    try:
        ts = int(ts_str)
    except ValueError:
        return False

    if now is None:
        now = int(time.time())
    if abs(now - ts) > _SIGNATURE_WINDOW_SECONDS:
        return False

    message = f"{token}|{tenant_id}|{ts}"
    expected = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided, expected)
