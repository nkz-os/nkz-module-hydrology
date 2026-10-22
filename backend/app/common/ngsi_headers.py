"""Canonical NGSI-LD header injection for standalone modules.

ETSI NGSI-LD spec rule (mutual exclusivity):
  - @context in body  → Content-Type: application/ld+json, NO Link header
  - @context NOT in body → Content-Type: application/json, Link header with @context URL

NEVER set both Content-Type: application/ld+json AND a Link header simultaneously.

Usage:
    from app.common.ngsi_headers import inject_fiware_headers

    # GET request (no body)
    headers = inject_fiware_headers({}, tenant_id)

    # POST with @context in body
    headers = inject_fiware_headers({}, tenant_id, has_context_in_body=True)

    # POST without @context in body
    headers = inject_fiware_headers({}, tenant_id, has_context_in_body=False)
"""

import os

from app.common.tenant_utils import normalize_tenant_id

CONTEXT_URL = os.getenv("CONTEXT_URL", "http://api-gateway-service:5000/ngsi-ld-context.json")


def inject_fiware_headers(
    headers: dict,
    tenant: str | None = None,
    has_context_in_body: bool = False,
) -> dict:
    """Inject NGSI-LD + FIWARE tenant headers for Orion-LD multitenancy.

    Args:
        headers: Existing headers dict. Modified in-place AND returned.
        tenant: Raw tenant ID (will be normalized via normalize_tenant_id).
        has_context_in_body: True if the JSON body contains an @context key.

    Returns:
        The same dict (modified in-place).
    """
    if tenant:
        normalized = normalize_tenant_id(tenant)
        headers["NGSILD-Tenant"] = normalized
        headers["Fiware-Service"] = normalized
        headers["Fiware-ServicePath"] = "/"

    if has_context_in_body:
        headers["Content-Type"] = "application/ld+json"
    else:
        headers["Content-Type"] = "application/json"
        if CONTEXT_URL:
            headers["Link"] = (
                f"<{CONTEXT_URL}>; "
                f'rel="http://www.w3.org/ns/json-ld#context"; '
                f'type="application/ld+json"'
            )

    headers.setdefault("Accept", "application/ld+json")
    return headers
