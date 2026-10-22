"""Tests for gateway HMAC signature verification.

The api-gateway signs X-Auth-Signature = "{sha256_hex}:{unix_ts}" over
message "{token}|{tenant}|{ts}". Window = 300s. See services/common/keycloak_auth.py
(generate_hmac_signature / verify_hmac_signature) for the canonical format.
"""
import hashlib
import hmac as _hmac
import time

from app.middleware.hmac import verify_gateway_hmac


SECRET = "shared-secret"


def _sign(token: str, tenant: str, ts: int, secret: str = SECRET) -> str:
    msg = f"{token}|{tenant}|{ts}".encode()
    sig = _hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()
    return f"{sig}:{ts}"


def test_valid_signature_accepted():
    ts = int(time.time())
    token, tenant = "tok123", "tenant-a"
    assert verify_gateway_hmac(
        _sign(token, tenant, ts), token, tenant, secret=SECRET, now=ts
    ) is True


def test_wrong_tenant_rejected():
    ts = int(time.time())
    sig = _sign("tok123", "tenant-a", ts)
    assert verify_gateway_hmac(sig, "tok123", "tenant-b", secret=SECRET, now=ts) is False


def test_wrong_secret_rejected():
    ts = int(time.time())
    sig = _sign("tok", "t", ts, secret=SECRET)
    assert verify_gateway_hmac(sig, "tok", "t", secret="other", now=ts) is False


def test_expired_signature_rejected():
    old_ts = int(time.time()) - 400  # > 300s window
    assert verify_gateway_hmac(
        _sign("tok", "t", old_ts), "tok", "t", secret=SECRET, now=int(time.time())
    ) is False


def test_malformed_header_rejected():
    assert verify_gateway_hmac("garbage", "tok", "t", secret=SECRET) is False
    assert verify_gateway_hmac("", "tok", "t", secret=SECRET) is False


def test_empty_secret_fails_closed_when_required():
    # fail-closed: no secret configured + require=True -> reject (NOT fail-open)
    assert verify_gateway_hmac(
        "anything", "tok", "t", secret="", require=True
    ) is False
