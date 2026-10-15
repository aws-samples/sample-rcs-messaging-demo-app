"""
API Gateway Lambda authorizer for AnyHealth's protected endpoints.

Gates two groups of routes with a shared secret stored in Secrets Manager
(created by the CDK stack) and passed by the caller as the `X-Api-Key` header:

  * Writes — can send real RCS messages to real phones, change keywords or wipe
    demo data: /api/trigger, /api/push, /api/reply, /api/reset, /api/mode,
    /api/video/start, /api/video/preview, and the tester and keyword management
    routes (POST, PUT, DELETE).
  * Reads that disclose recipient or account data: GET /api/testers (+ /names,
    /status, /metrics), /api/conversations (+ /{proxy+}), /api/media/latest,
    /api/mode, /api/typing, /api/keywords, /api/agent-identity and /api/health.

What stays open is open because something that cannot hold the operator's key
has to call it: the member-facing webview and upload routes, static demo
metadata (/api/brand, /api/vignettes*), and GET /api/media, whose response is
consumed as an <img src> and which is instead restricted server-side to an
allow-list of key prefixes (see dashboard_handler._MEDIA_ALLOWED_PREFIXES).
The authoritative route split is in cdk/lib/anyhealth-stack.ts, and SECURITY.md
lists both sets.

This is a lightweight control appropriate for a demo, not a substitute for a
real identity provider (a JWT authorizer with an Amazon Cognito user pool, or
IAM authorization) in a production deployment.
"""

import hmac
import os
import time

import boto3

SECRET_ARN = os.environ.get("API_KEY_SECRET_ARN", "")

# How long a warm container trusts the secret it last read. Once the cached copy
# is older than this, the next request re-reads Secrets Manager, so a rotated
# key's predecessor stops working here within this window. The HTTP API's own
# result cache (resultsCacheTtl in cdk/lib/anyhealth-stack.ts) adds to the
# delay; SECURITY.md ("Rotating the API key") has the combined worst case.
SECRET_CACHE_TTL_SECONDS = 60

_secrets = boto3.client("secretsmanager")
_cached_secret = None  # bytes: the key as of the last read
_cached_at = 0.0  # time.time() of that read


def _fetch_secret() -> bytes:
    """Read the current secret from Secrets Manager and cache it."""
    global _cached_secret, _cached_at
    resp = _secrets.get_secret_value(SecretId=SECRET_ARN)
    _cached_secret = resp["SecretString"].encode("utf-8")
    _cached_at = time.time()
    return _cached_secret


def _cache_is_fresh() -> bool:
    # Wall-clock time, so the age includes the time a container spends frozen
    # between invocations. A clock that steps backwards reads as expired.
    return _cached_secret is not None and 0 <= time.time() - _cached_at < SECRET_CACHE_TTL_SECONDS


def _key_matches(provided: bytes) -> bool:
    """True if `provided` is the current key.

    Raises if the secret cannot be read. An expired cache is never served as a
    fallback, so a Secrets Manager outage cannot keep a revoked key working.
    """
    refreshed = not _cache_is_fresh()
    expected = _fetch_secret() if refreshed else _cached_secret
    # Bytes, not str: compare_digest raises TypeError on a non-ASCII str.
    if hmac.compare_digest(provided, expected):
        return True
    if refreshed:
        return False
    # A mismatch against a cached value may just mean the key was rotated since
    # the cache was filled. Re-read once before denying so a new key works
    # immediately instead of waiting out the TTL.
    return hmac.compare_digest(provided, _fetch_secret())


def handler(event, context):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    provided = headers.get("x-api-key", "")

    # Anything but a non-empty string cannot be the key; skip the secret read.
    if not provided or not isinstance(provided, str):
        return {"isAuthorized": False}

    try:
        # surrogatepass keeps a lone surrogate in the header from raising here.
        is_authorized = _key_matches(provided.encode("utf-8", "surrogatepass"))
    except Exception as e:  # noqa: BLE001
        # Fail closed: any error reading the secret denies the request. Neither
        # the secret nor the presented key is ever logged.
        print(f"authorizer: failed to load secret: {e}")
        return {"isAuthorized": False}
    return {"isAuthorized": is_authorized}
