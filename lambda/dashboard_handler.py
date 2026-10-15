"""
AnyHealth — Dashboard API Lambda.

Serves the React dashboard: brand/theme config, conversation history, tester
management, the vignette catalog, push triggers, and the live-agent console
(human reply + take-over/release). Also serves the in-message webviews.

Everything brand-specific comes from content/*.md via common. No hardcoding.
"""

import base64
import gzip
import json
import os
import re
import time
import urllib.parse
from html import escape as html_escape

import boto3
from boto3.dynamodb.conditions import Key

import common as c
import video_visit
from flows import get_flow, welcome, otp

RCS_AGENT_ID = c.RCS_AGENT_ID
LAMBDA_CHANNEL_ADAPTER = os.environ.get("CHANNEL_ADAPTER_FN", "")

lambda_client = boto3.client("lambda", region_name=c.REGION)

HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


class ApiError(Exception):
    """A deliberate non-2xx answer: an HTTP status, a stable `code` clients can
    branch on, and a `message` that is safe to show an operator. The message is
    never exception text — AWS error strings carry the caller's role ARN and the
    account id — so a handler logs the detail and raises this instead.
    """

    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


# Each vignette's `features` are *keys* into content/rcs-features.json, not
# display strings. The registry holds the name, the explanation, the AWS
# documentation link and the documented limits for each one, and
# _resolve_features() below expands them on the way out through /api/vignettes
# so the dashboard can render a tooltip per feature. Add a key here and the
# dashboard teaches it; there is no second list to keep in step.
VIGNETTES = [
    # Customer/member-facing vignettes.
    {"id": "welcome", "name": "Welcome & RCS Intro", "category": "deterministic", "audience": "customer",
     "trigger": "Start: Welcome",
     "description": "Educational front door — what RCS is, verified brand identity, opt-in/out, SMS fallback",
     "features": ["rich_card", "verified_identity", "per_message_fallback",
                  "suggested_replies", "postback_navigation"]},
    {"id": "rx_refill", "name": "Pharmacy Rx Refill", "category": "deterministic", "audience": "customer",
     "trigger": "Start: Rx_Refill",
     "description": "Refill flow; sends one PDF over RCS and one through a secure webview",
     # Both caveats, deliberately: "Rx Documents" sends the generic fact sheet as
     # a FileMessage (not_for_phi — those bytes cross the carrier network) and
     # offers the member's own record through a webview (compliance_forward).
     # The contrast is the point, so the card carries both tooltips.
     "features": ["rich_card", "suggested_actions", "dial_phone", "show_location",
                  "file_message", "event_driven_send", "webview",
                  "not_for_phi", "compliance_forward"]},
    {"id": "appt_reminder", "name": "Appointment Reminder", "category": "deterministic", "audience": "customer",
     "trigger": "Start: Appt_Reminder", "description": "Appointment with confirm/reschedule",
     "features": ["rich_card", "two_way", "calendar_event", "show_location", "webview"]},
    {"id": "appt_reschedule", "name": "Clinic-Initiated Reschedule", "category": "deterministic", "audience": "customer",
     "trigger": "Start: Appt_Reschedule", "description": "The clinic moves a visit; member picks a new slot",
     "features": ["event_driven_send", "suggested_replies", "conversational_flow"]},
    {"id": "verification", "name": "Verification Code", "category": "deterministic", "audience": "customer",
     "trigger": "Start: Verification", "description": "One-time code with expiration (TimeToLive)",
     "features": ["time_to_live", "per_message_fallback", "otp", "suggested_replies"]},
    {"id": "store", "name": "Wellness Store", "category": "deterministic", "audience": "customer",
     "trigger": "Start: Store", "description": "Conversational cart & catalog",
     "features": ["carousel", "persistent_cart", "checkout"]},
    {"id": "benefits_qa", "name": "Benefits & Coverage Q&A", "category": "ai-driven", "audience": "customer",
     "trigger": "Start: Benefits_QA", "description": "AI conversation about plan details",
     "features": ["ai_agent", "natural_language", "suggested_actions"]},
    {"id": "find_care", "name": "Find a Provider", "category": "ai-driven", "audience": "customer",
     "trigger": "Start: Find_Care", "description": "AI-assisted in-network provider search",
     "features": ["ai_agent", "request_location", "provider_directory"]},
    {"id": "handover", "name": "Live-Agent Handover", "category": "deterministic", "audience": "customer",
     "trigger": "Start: Handover", "description": "Escalate from AI to a human agent",
     "features": ["human_handover", "agent_console"]},
    # Internal staff/employee-facing vignettes — same RCS channel, showing
    # workforce self-service use cases alongside the member-facing ones above.
    {"id": "clock_in_out", "name": "Clock In / Out", "category": "deterministic", "audience": "internal",
     "trigger": "Start: Clock_In_Out", "description": "Employee attendance — start or end a shift",
     "features": ["rich_card", "two_way", "webview"]},
    {"id": "my_schedule", "name": "My Schedule", "category": "deterministic", "audience": "internal",
     "trigger": "Start: My_Schedule", "description": "Employee shift schedule, with PTO & swap shortcuts",
     "features": ["rich_card", "webview", "cross_flow_navigation"]},
    {"id": "pto_request", "name": "PTO Request", "category": "deterministic", "audience": "internal",
     "trigger": "Start: PTO_Request", "description": "Request time off and track manager approval",
     "features": ["rich_card", "two_way", "approval_flow", "calendar_event"]},
    {"id": "shift_swap", "name": "Shift Swap", "category": "deterministic", "audience": "internal",
     "trigger": "Start: Shift_Swap", "description": "Offer a shift to a coworker and track acceptance",
     "features": ["rich_card", "two_way", "approval_flow", "webview"]},
    # Rich-media demos — native RCS inbound media vs. compliance-forward
    # webview upload, for the same "member sends us a photo" use case. See
    # each flow module's docstring for the PII/PHI trade-off, and the
    # dashboard's PII guidance tooltip (rendered client-side) for the
    # member-facing explanation.
    {"id": "photo_submission", "name": "Classify a Photo", "category": "deterministic", "audience": "customer",
     "trigger": "Start: Photo_Submission", "description": "Native RCS inbound photo — not for PII/PHI",
     "features": ["inbound_media", "genai_classification", "not_for_phi"]},
    {"id": "insurance_upload", "name": "Secure Document Upload", "category": "deterministic", "audience": "customer",
     "trigger": "Start: Insurance_Upload", "description": "Webview upload with HEIC conversion — keeps the file off the carrier path; the demo page itself is unauthenticated",
     "features": ["webview", "heic_conversion", "genai_classification", "compliance_forward"]},
    # Signable document sent OUT to be read and signed in a webview — the
    # counterpart to Secure Document Upload's inbound direction. The agreement
    # and signature stay in the webview, never crossing the RCS/carrier network.
    {"id": "loan_agreement", "name": "Loan Agreement (e-sign)", "category": "deterministic", "audience": "customer",
     "trigger": "Start: Loan_Agreement", "description": "Read-and-sign document in a webview — initials, signature, audit receipt",
     "features": ["rich_card", "webview", "compliance_forward"]},
    # Diagnostic, not a demo of anything a member would see: opens one page three
    # ways (webview full, webview half, device browser) and reports whether the
    # page can reach getUserMedia in each. See lambda/flows/media_probe.py.
    # `trigger` is not decoration: the dashboard's Send button POSTs this exact
    # string to /api/trigger, which strips "Start: " and hands the remainder to
    # the channel adapter as the flow key (see trigger_flow below). A prose value
    # here — "Dashboard only" — normalizes to a key no flow owns, and the adapter
    # quietly falls back to the welcome carousel, so the wrong vignette arrives
    # on the handset with nothing logged as an error. It must round-trip to a
    # FLOW_MAP key.
    {"id": "media_probe", "name": "Camera & Mic Probe", "category": "deterministic", "audience": "internal",
     "trigger": "Start: Media_Probe", "description": "Diagnostic: reports whether an RCS webview exposes the camera and mic on this handset",
     "features": ["text_message", "webview", "suggested_actions"]},
    # Experimental: a WebRTC video call (Amazon Chime SDK JS) running inside the
    # in-conversation webview. See lambda/flows/video_visit.py.
    {"id": "video_visit", "name": "Video Visit (WebRTC)", "category": "deterministic", "audience": "customer",
     "trigger": "Start: Video_Visit", "description": "Experimental: Chime SDK video call inside the RCS webview",
     "features": ["rich_card", "webview", "suggested_actions"]},
    # Experiment, surfaced in the Settings tab (like Camera & Mic Probe), not the
    # member-facing list: opens the external Amazon IVS iCasino live-video demo
    # as a top-level RCS webview, to try IVS low-latency video there.
    {"id": "ivs_experiment", "name": "IVS iCasino Webview (experiment)", "category": "deterministic", "audience": "internal",
     "trigger": "Start: IVS_Experiment", "description": "Experiment: opens a live Amazon IVS video stream in an RCS webview",
     "features": ["text_message", "webview", "suggested_actions"]},
    {"id": "ivs_fitness", "name": "IVS Interactive Fitness Webview (experiment)", "category": "deterministic", "audience": "internal",
     "trigger": "Start: IVS_Fitness", "description": "Experiment: opens a live Amazon IVS interactive fitness stream in an RCS webview",
     "features": ["text_message", "webview", "suggested_actions"]},
]


def _resolve_features(vignettes):
    """Expand each vignette's feature keys into the registry entries the
    dashboard renders as tooltips.

    An unknown key raises rather than degrading to a bare label. A silently
    unresolved key is exactly the failure this registry exists to prevent: the
    card would still look fine, just with the teaching content missing, and
    nobody would notice. scripts/check-rcs-registry.py catches it before deploy.
    """
    out = []
    for v in vignettes:
        resolved = []
        for key in v.get("features", []):
            entry = c.rcs_feature(key)
            if not entry:
                raise RuntimeError(
                    f"vignette {v['id']!r} references unknown RCS feature key "
                    f"{key!r} — add it to content/rcs-features.json"
                )
            resolved.append({
                "key": key,
                "name": entry.get("name", key),
                "kind": entry.get("kind", "rcs-api"),
                "blurb": entry.get("blurb", ""),
                "gotcha": entry.get("gotcha", ""),
                "apiShape": entry.get("apiShape", ""),
                "status": entry.get("status", "demonstrated"),
                "statusNote": entry.get("statusNote", ""),
                "docUrl": c.rcs_doc_url(entry.get("doc", "")),
                "limits": [
                    {
                        "label": lim["label"],
                        "value": lim["value"],
                        "unit": lim.get("unit", ""),
                        "docUrl": c.rcs_doc_url(lim.get("doc", "")),
                    }
                    for lim in (
                        c.rcs_registry()["limits"][k]
                        for k in entry.get("limitRefs", [])
                    )
                ],
            })
        out.append({**v, "features": resolved})
    return out


# Vignettes whose RCS content is fixed/deterministic and safe to render for a
# dashboard preview with zero side effects (no DynamoDB writes, no real send,
# no phone number). AI-driven vignettes (benefits_qa, find_care) are excluded:
# their content is generated live by Bedrock per conversation, so there's no
# fixed content to preview, and invoking the model on every card hover would
# cost real money for no accurate benefit.
_PREVIEWABLE = {
    "welcome": lambda: welcome.on_start("", ""),
    "rx_refill": lambda: get_flow("rx_refill").on_start("", ""),
    "appt_reminder": lambda: get_flow("appt_reminder").on_start("", ""),
    "appt_reschedule": lambda: get_flow("appt_reschedule").on_trigger("", "", "appt_reschedule"),
    "verification": lambda: otp.preview_message(),
    "store": lambda: get_flow("store").on_start("", ""),
    "handover": lambda: get_flow("handover").on_start("", ""),
    # Internal staff vignettes — on_start for each of these only reads
    # DynamoDB (never writes) when phone_hash is "", so it's safe to preview
    # directly without a dedicated preview_message() override.
    "clock_in_out": lambda: get_flow("clock_in_out").on_start("", ""),
    "my_schedule": lambda: get_flow("my_schedule").on_start("", ""),
    "pto_request": lambda: get_flow("pto_request").on_start("", ""),
    "shift_swap": lambda: get_flow("shift_swap").on_start("", ""),
    # Rich-media demos — on_start only builds a card/webview link from an
    # empty phone_hash (no DynamoDB write), so these are safe to preview too.
    "photo_submission": lambda: get_flow("photo_submission").on_start("", ""),
    "insurance_upload": lambda: get_flow("insurance_upload").on_start("", ""),
    "loan_agreement": lambda: get_flow("loan_agreement").preview_message(),
    "media_probe": lambda: get_flow("media_probe").preview_message(),
    # preview_message() rather than on_start(): on_start mints a visit token,
    # which is a DynamoDB write, and previewing must stay side-effect free.
    "video_visit": lambda: get_flow("video_visit").preview_message(),
    "ivs_experiment": lambda: get_flow("ivs_experiment").preview_message(),
    "ivs_fitness": lambda: get_flow("ivs_fitness").preview_message(),
}


def preview_vignette(vignette_id):
    """Render the exact RCS message content a vignette would send, without
    sending anything or touching DynamoDB. Used by the dashboard's phone
    preview tooltip on the Interactive Demos tab."""
    builder = _PREVIEWABLE.get((vignette_id or "").lower())
    if not builder:
        return {"available": False}
    try:
        messages = builder()
    except Exception as e:  # noqa: BLE001
        print(f"preview_vignette({vignette_id}) failed: {e}")
        return {"available": False}
    # Run the same validation send_rcs runs. Without this the preview happily
    # renders content the API would reject, which is exactly how an over-long
    # welcome carousel looked healthy on the dashboard while failing on every
    # handset. Surfaced as an error rather than a plain "unavailable" so the
    # operator can tell a content bug from an AI-generated vignette.
    for m in messages:
        invalid = c.validate_rcs_content(m)
        if invalid:
            print(f"preview_vignette({vignette_id}) would fail to send: {invalid}")
            return {"available": False, "error": invalid}
    return {"available": True, "messages": [_resolve_media_urls(m) for m in messages]}


def _resolve_media_urls(node):
    """Walk RCS message content and rewrite s3://<bucket>/<key> FileUrl
    values (what common.resolve_media produces) into a bare media key the
    frontend can pass to its existing api.mediaUrl(key) helper (-> GET
    /api/media?key=..., which 302s to a presigned URL). This handler has no
    reliable base-URL of its own — API_BASE_URL is only injected on the
    channel-adapter function to avoid a CFN cycle with this HTTP API — but
    the dashboard frontend already knows its own API base URL, so resolve
    to a relative key and let it build the final URL."""
    prefix = f"s3://{c.S3_BUCKET}/"
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k == "FileUrl" and isinstance(v, str) and v.startswith(prefix):
                out[k] = v[len(prefix):]
            else:
                out[k] = _resolve_media_urls(v)
        return out
    if isinstance(node, list):
        return [_resolve_media_urls(v) for v in node]
    return node


def _load_webviews():
    wv = {}
    wv_dir = os.path.join(os.path.dirname(__file__), "webviews")
    if os.path.isdir(wv_dir):
        for f in os.listdir(wv_dir):
            if f.endswith(".html"):
                with open(os.path.join(wv_dir, f), encoding="utf-8") as fh:
                    wv[f[:-5]] = fh.read()
    return wv


WEBVIEWS = _load_webviews()

# Static assets served from the same directory as the webviews, currently just
# the vendored Chime SDK bundle (see scripts/vendor-chime-sdk.mjs). Deliberately
# NOT read at cold start like the HTML above: the bundle is ~1.6 MB and every
# dashboard request pays for this module's import, while only the video-visit
# page ever asks for it. Read and compressed on first request, then cached for
# the life of the container.
_ASSET_TYPES = {".js": "text/javascript; charset=utf-8"}
_ASSET_CACHE = {}


def _serve_asset(page):
    """Serve a static webview asset, or None if `page` isn't one.

    gzipped rather than sent raw because the client is a handset on cellular and
    the bundle compresses about 4:1 — a second or two of staring at a blank
    video-visit page. API Gateway does not compress Lambda responses itself, so
    this is the only place it can happen.
    """
    # basename() before anything else: `page` is attacker-controlled path text,
    # and "../../etc/passwd" must not reach open(). The extension allowlist is
    # the second gate — nothing outside _ASSET_TYPES is servable at all.
    name = os.path.basename(page)
    ctype = _ASSET_TYPES.get(os.path.splitext(name)[1])
    if not ctype:
        return None
    if name not in _ASSET_CACHE:
        full = os.path.join(os.path.dirname(__file__), "webviews", name)
        if not os.path.isfile(full):
            return None
        with open(full, "rb") as fh:
            _ASSET_CACHE[name] = base64.b64encode(gzip.compress(fh.read(), 6)).decode()
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": ctype,
            "Content-Encoding": "gzip",
            # Immutable because the importing page cache-busts on the SDK version
            # (see _chime_sdk_src) — a version bump changes the URL, so a stale
            # copy can never be paired with a newer page.
            "Cache-Control": "public, max-age=31536000, immutable",
            "Access-Control-Allow-Origin": "*",
        },
        "body": _ASSET_CACHE[name],
        "isBase64Encoded": True,
    }


_chime_sdk_src_cache = None


def _chime_sdk_src():
    """The import specifier substituted into video-visit.html.

    Relative, so it resolves against /webview/ and stays same-origin — the point
    of vendoring the SDK in the first place. The version comes from the generated
    bundle's own banner line, which makes the query string change when the SDK is
    re-vendored and lets the asset be cached immutably in between. Only the first
    line is read; the megabyte behind it is not touched here.
    """
    global _chime_sdk_src_cache
    if _chime_sdk_src_cache is None:
        version = "0"
        try:
            full = os.path.join(os.path.dirname(__file__), "webviews", "chime-sdk.js")
            with open(full, encoding="utf-8") as fh:
                first = fh.readline()
            if "@" in first:
                version = first.split("@")[1].split()[0].strip()
        except OSError:
            pass
        _chime_sdk_src_cache = f"./chime-sdk.js?v={urllib.parse.quote(version)}"
    return _chime_sdk_src_cache


def serve_webview(path, params=None):
    page = path.replace("/webview/", "").rstrip("/")
    # media-probe.html reports its findings by re-fetching its own URL with a
    # ?report= query string, rather than through a new endpoint — so the
    # diagnostic adds no writable surface and no route: this only logs. A
    # HALF-mode webview can be too small to read and the messaging app may close
    # it before the tester has finished looking, so CloudWatch is the durable
    # copy. Truncated because a query string is unbounded input; the report
    # carries capability flags and a user agent, no phone number and no media.
    report = (params or {}).get("report")
    if report:
        print(f"WEBVIEW_PROBE_REPORT page={page} {report[:4000]}")
        # Answer the report itself rather than re-serving the page: the caller is
        # an Image() GET that wants nothing back.
        return {"statusCode": 204, "headers": {"Access-Control-Allow-Origin": "*"}, "body": ""}
    asset = _serve_asset(page)
    if asset:
        return asset
    html = WEBVIEWS.get(page)
    # Light brand token substitution so webviews match the brand.
    if html:
        # {{BRAND_NAME}} lands in markup (title, header text), so it is escaped
        # for HTML: a brand with "<", "&" or a quote is text, not markup. It is
        # not safe inside a <script>, where entities are not decoded and a quote
        # ends the string literal — templates must keep the token out of scripts
        # and read the rendered text from the DOM instead (see video-visit.html).
        html = (html.replace("{{BRAND_NAME}}", html_escape(str(c.brand_name()), quote=True))
                    .replace("{{ACCENT}}", c.accent_color())
                    .replace("{{CHIME_SDK_SRC}}", _chime_sdk_src()))
        return {"statusCode": 200, "headers": {"Content-Type": "text/html", "Access-Control-Allow-Origin": "*"}, "body": html}
    return {"statusCode": 404, "headers": {"Content-Type": "text/html"}, "body": "<h1>Not found</h1>"}


def handler(event, context):
    path = event.get("rawPath", event.get("path", ""))
    method = event.get("requestContext", {}).get("http", {}).get("method", event.get("httpMethod", "GET"))

    if method == "OPTIONS":
        return {"statusCode": 200, "headers": HEADERS, "body": ""}

    try:
        if path.startswith("/webview/"):
            return serve_webview(path, event.get("queryStringParameters") or {})
        if path in ("/api/video/join", "/api/video/ping", "/api/video/status", "/api/video/end"):
            # Unauthenticated by design, like /api/uploads/presign: the caller is
            # the member's in-app browser, which cannot hold the dashboard API
            # key. The control is the pre-minted, expiring visit token plus the
            # per-visit join budget — see lambda/video_visit.py.
            #
            # `role` says which side is calling, and video_visit rejects anything
            # that isn't one of its two known roles. It is not a permission (an
            # unauthenticated caller can claim either one) — it exists so the two
            # clients' lifecycles don't fight: the member's page being
            # backgrounded must not end the visit the clinician is sitting in.
            params = event.get("queryStringParameters") or {}
            visit, role = params.get("visit", ""), params.get("role", "member")
            if path == "/api/video/join":
                body = video_visit.join(visit, role)
            elif path == "/api/video/ping":
                body = video_visit.ping(visit, role)
            elif path == "/api/video/status":
                body = video_visit.status(visit)
            else:  # /api/video/end
                body = video_visit.end(visit, role)
        elif path == "/api/health":
            body = get_health()
        elif path == "/api/version":
            body = get_version()
        elif path == "/api/typing":
            body = {"typing": c.typing_now(), "staleAfterSeconds": c.TYPING_STALE_SECONDS}
        elif path == "/api/agent-identity":
            body = get_agent_identity()
        elif path == "/api/brand":
            body = get_brand()
        elif path == "/api/vignettes":
            body = _resolve_features(VIGNETTES)
        elif path == "/api/vignettes/features":
            # The whole RCS feature registry, including the features this demo
            # deliberately does not implement — the Guide tab's "Learn RCS"
            # section lists those too, so a builder can see what the service
            # offers beyond what is on screen.
            reg = c.rcs_registry()
            body = {
                # The date a person last read the limits against the AWS user
                # guide (content/rcs-features.json -> reviewedOn), for the Guide tab.
                "reviewedOn": reg.get("reviewedOn", ""),
                "features": [
                    {**f, "docUrl": c.rcs_doc_url(f.get("doc", ""))}
                    for f in reg.get("features", [])
                ],
                "limits": [
                    {"key": k, **v, "docUrl": c.rcs_doc_url(v.get("doc", ""))}
                    for k, v in reg.get("limits", {}).items()
                ],
            }
        elif path == "/api/vignettes/preview":
            params = event.get("queryStringParameters") or {}
            body = preview_vignette(params.get("id", ""))
        elif path == "/api/testers" and method == "GET":
            body = get_testers()
        elif path == "/api/testers" and method == "POST":
            p = json.loads(event.get("body", "{}"))
            body = add_tester(p.get("phone", ""), p.get("name", ""))
        elif path == "/api/testers/names":
            body = get_tester_names()
        elif path == "/api/testers/status":
            params = event.get("queryStringParameters") or {}
            body = get_tester_status(params.get("phone", ""))
        elif path == "/api/testers/metrics" and method == "GET":
            body = get_testers_with_metrics()
        elif path.startswith("/api/testers/") and method == "PUT":
            # rawPath segments are NOT url-decoded by API Gateway HTTP API v2,
            # so a phone number sent as %2B12065550100 (encodeURIComponent of
            # "+1...") arrives literally encoded — decode it here. `unquote`
            # (not `unquote_plus`) leaves a literal "+" untouched if the
            # caller didn't encode it, so both forms work.
            phone = urllib.parse.unquote(path.split("/api/testers/")[1].replace("/name", ""))
            p = json.loads(event.get("body", "{}"))
            body = set_tester_name(phone, p.get("name", ""))
        elif path.startswith("/api/testers/") and method == "DELETE":
            # Same encoding caveat as the PUT above: the "+" of an E.164 number
            # arrives as sent, encoded or not, and unquote handles both.
            body = delete_tester(urllib.parse.unquote(path.split("/api/testers/")[1]))
        elif path == "/api/keywords" and method == "GET":
            body = get_keywords()
        elif path == "/api/keywords" and method == "POST":
            p = json.loads(event.get("body", "{}"))
            body = create_keyword(p.get("keyword", ""), p.get("message", ""),
                                  p.get("action", "AUTOMATIC_RESPONSE"))
        elif path.startswith("/api/keywords/") and method == "DELETE":
            # Same encoding caveat as the tester DELETE above.
            body = delete_keyword(urllib.parse.unquote(path.split("/api/keywords/")[1]))
        elif path == "/api/conversations":
            body = get_conversations()
        elif path.startswith("/api/conversations/") and method == "GET":
            ph = path.split("/api/conversations/")[1]
            params = event.get("queryStringParameters") or {}
            body = get_conversation_detail(ph, include_events=params.get("include_events") == "true")
        elif path == "/api/trigger" and method == "POST":
            p = json.loads(event.get("body", "{}"))
            body = trigger_flow(p.get("phone", ""), p.get("trigger", ""))
        elif path == "/api/push" and method == "POST":
            body = push_message(json.loads(event.get("body", "{}")))
        elif path == "/api/video/start" and method == "POST":
            # Authenticated, unlike /api/video/join above: this one spends money
            # (a send, plus the Chime meeting the operator is about to create) and
            # the caller is the dashboard, which does hold the API key.
            body = start_video_visit(json.loads(event.get("body", "{}")))
        elif path == "/api/video/preview" and method == "POST":
            # Mints a token and sends nothing — the video-visit equivalent of the
            # device preview on every other vignette card. Authenticated for the
            # same reason as /api/video/start: a token is a spendable thing, and
            # only the dashboard should be able to mint one.
            body = preview_video_visit(json.loads(event.get("body", "{}")))
        elif path == "/api/reply" and method == "POST":
            body = agent_reply(json.loads(event.get("body", "{}")))
        elif path == "/api/mode" and method == "GET":
            params = event.get("queryStringParameters") or {}
            body = get_mode(params.get("phone", ""))
        elif path == "/api/mode" and method == "POST":
            body = set_mode(json.loads(event.get("body", "{}")))
        elif path == "/api/media":
            params = event.get("queryStringParameters") or {}
            url = get_media_url(params.get("key", ""))
            if isinstance(url, str):
                return {"statusCode": 302, "headers": {**HEADERS, "Location": url}, "body": ""}
            body = url
        elif path == "/api/secure-doc" and method == "GET":
            # Unauthenticated for the same reason as /api/uploads/presign: the
            # caller is a member's in-app webview, which holds no API key. See
            # get_secure_doc for what that does and does not protect.
            params = event.get("queryStringParameters") or {}
            body = get_secure_doc(params.get("ph", ""), params.get("doc", ""))
        elif path == "/api/media/latest":
            params = event.get("queryStringParameters") or {}
            body = get_latest_media_for_demo(params.get("phone", ""))
        elif path == "/api/uploads/presign" and method == "POST":
            # Public/unauthenticated by design: this is called from inside a
            # member-facing webview (an in-app browser session), which has no
            # way to hold the operator's dashboard API key. See
            # upload-insurance-card.html and insurance_upload.py.
            body = create_upload_url(json.loads(event.get("body", "{}")))
        elif path.startswith("/api/uploads/") and path.endswith("/status") and method == "GET":
            parts = path.split("/")
            # /api/uploads/{ph}/{upload_id}/status
            ph, upload_id = parts[3], parts[4]
            body = get_upload_status(ph, upload_id)
        elif path == "/api/reset" and method == "POST":
            body = reset_data()
        else:
            return {"statusCode": 404, "headers": HEADERS, "body": json.dumps({"error": "Not found"})}
    except ApiError as e:
        return {
            "statusCode": e.status,
            "headers": HEADERS,
            "body": json.dumps({"error": e.message, "code": e.code}),
        }
    except Exception as e:  # noqa: BLE001
        # Log only exception type + request metadata — never the full traceback
        # (traceback.print_exc dumps every frame's locals, which here include the
        # raw `event` dict: request bodies with phone numbers and conversation
        # content). Correlate with CloudWatch via the request id instead.
        request_id = getattr(context, "aws_request_id", "")
        print(f"handler error: {type(e).__name__} on {method} {path} (requestId={request_id})")
        return {"statusCode": 500, "headers": HEADERS, "body": json.dumps({"error": "Internal server error"})}

    return {"statusCode": 200, "headers": HEADERS, "body": json.dumps(body, default=str)}


# ── Version ─────────────────────────────────────────────────────────────────
def get_version():
    """The deployed backend's version string, shown in the dashboard status bar
    beside the frontend's own (which the browser already knows, having had it
    compiled in). Baked into the function's environment at synth time by
    cdk/lib/anyhealth-stack.ts — there is nothing to compute at runtime, and a
    Lambda has no git tree to ask.

    'unknown' means the stack was synthesized somewhere the version script
    couldn't run. Cosmetic either way: nothing branches on this value.
    """
    return {"backend": os.environ.get("APP_VERSION", "unknown")}


# ── Health / account-level alerts ────────────────────────────────────────────
def get_health():
    """Account-wide send health, polled by the dashboard status bar. Distinct from
    per-recipient device status (GET /api/testers/status): the RCS monthly
    spend/quota limit is a property of the AWS account, not of any one
    destination, so a failure here means every send is currently rejected
    regardless of which device is targeted.

    rcsQuotaAlert.active is set from the last SEND_FAILED whose error message
    matched a quota/spend-limit reason (see common.note_send_error), and
    clears itself the next time any send succeeds (common.clear_quota_alert).
    We also cross-check the account's current enforced spend limit here so a
    fresh page load can show the warning even before another send is
    attempted.
    """
    alert = c.get_quota_alert()
    spend_limit = None
    try:
        resp = c.sms_voice.describe_spend_limits()
        for limit in resp.get("SpendLimits", []):
            if limit.get("Name") == "RCS_MESSAGE_MONTHLY_SPEND_LIMIT":
                spend_limit = {
                    "enforcedLimit": limit.get("EnforcedLimit"),
                    "maxLimit": limit.get("MaxLimit"),
                    "overridden": limit.get("Overridden", False),
                }
                break
    except Exception as e:  # noqa: BLE001
        print(f"describe_spend_limits failed: {e}")
    return {
        "rcsQuotaAlert": {
            "active": bool(alert),
            "error": alert.get("error", ""),
            "lastSeen": alert.get("last_seen", ""),
        },
        "rcsSpendLimit": spend_limit,
    }


# ── Live agent identity ─────────────────────────────────────────────────────
# The brand a recipient actually sees comes from the RCS registration on the
# AWS account, not from content/brand.md. The two are usually different: this
# demo's placeholder brand is "AnyHealth", while the agent doing the sending
# carries whatever identity was registered. Showing the placeholder in a device
# preview teaches the wrong thing -- the handset displays the registered logo
# and senderDisplayName.
#
# Reading it takes three calls:
#   DescribeRcsAgents            -> TestingAgent.RegistrationId
#   DescribeRegistrationFieldValues -> agentDetails.* incl. attachment ids for
#                                   logoImage / bannerImage
#   DescribeRegistrationAttachments -> AttachmentUrl, a presigned CloudFront URL
#                                   to the uploaded image itself
# That last one means the real brand assets are retrievable, not just their
# ids -- the URL goes straight into an <img src>. It is time-limited, which is
# why this is cached for minutes rather than resolved once at deploy time.
_IDENTITY_TTL_SECONDS = 240
_identity_cache = {"expires": 0.0, "value": None}


def _registration_field_values(registration_id):
    """FieldPath -> value, flattened across the three value shapes the API uses.

    A field carries exactly one of TextValue, SelectChoices (a list) or
    RegistrationAttachmentId, depending on the field — there is no single
    "value" key to read.
    """
    resp = c.sms_voice.describe_registration_field_values(RegistrationId=registration_id)
    out = {}
    for f in resp.get("RegistrationFieldValues", []):
        path = f.get("FieldPath", "")
        if "TextValue" in f:
            out[path] = f["TextValue"]
        elif f.get("SelectChoices"):
            out[path] = f["SelectChoices"][0]
        elif f.get("RegistrationAttachmentId"):
            out[path] = {"attachmentId": f["RegistrationAttachmentId"]}
    return out


def _attachment_urls(attachment_ids):
    """Presigned URLs for the given registration attachments, keyed by id."""
    ids = [a for a in attachment_ids if a]
    if not ids:
        return {}
    resp = c.sms_voice.describe_registration_attachments(RegistrationAttachmentIds=ids)
    return {
        a.get("RegistrationAttachmentId"): a.get("AttachmentUrl", "")
        for a in resp.get("RegistrationAttachments", [])
        if a.get("AttachmentStatus") == "UPLOAD_COMPLETE"
    }


def get_agent_identity():
    """The registered identity of the sending agent, read live from AWS.

    Returns source="live" with the real logo/banner URLs and display name, or
    source="unavailable" with a reason. Never raises: every caller treats this
    as an enhancement over content/brand.md, so a missing IAM permission or an
    agent whose registration is still in progress must degrade to the
    placeholder rather than break the Demo tab.
    """
    now = time.time()
    if _identity_cache["value"] and _identity_cache["expires"] > now:
        return _identity_cache["value"]

    # smsFallbackNumber is deployment config, not registration data: it comes
    # from `-c smsFallbackNumber=+1…` via the SMS_FALLBACK_NUMBER env var, so it
    # is set here on the initial dict rather than inside the try. It stays
    # readable even when the AWS registration read fails, because whether
    # fallback is configured is knowable without talking to AWS at all, and the
    # Settings tab should still be able to say so. Empty string means the
    # deployer supplied no SMS origination identity — the common case for a demo
    # deployment — and therefore that no message can ever
    # carry a FallbackConfiguration. See common.send_rcs. The account and Region
    # are the same kind of value: where this stack runs is knowable without
    # calling AWS, so the Settings tab can show them even when the read fails.
    result = {
        "source": "unavailable", "error": "", "agentId": c.RCS_AGENT_ID,
        "smsFallbackNumber": c.SMS_FALLBACK_NUMBER,
        "awsAccountId": c.DEPLOY_ACCOUNT_ID, "region": c.REGION,
    }
    try:
        if not c.RCS_AGENT_ID:
            raise RuntimeError("RCS_AGENT_ID is not configured on this deployment")
        agents = c.sms_voice.describe_rcs_agents(RcsAgentIds=[c.RCS_AGENT_ID]).get("RcsAgents", [])
        if not agents:
            raise RuntimeError(f"agent {c.RCS_AGENT_ID} not found in {c.REGION}")
        agent = agents[0]
        testing = agent.get("TestingAgent") or {}
        registration_id = testing.get("RegistrationId")
        if not registration_id:
            # A launched agent keeps brand assets on its country-launch
            # registrations instead; this demo only ever creates a testing one.
            raise RuntimeError("agent has no testing registration to read brand assets from")

        fields = _registration_field_values(registration_id)
        logo_id = (fields.get("agentDetails.logoImage") or {}).get("attachmentId")
        banner_id = (fields.get("agentDetails.bannerImage") or {}).get("attachmentId")
        urls = _attachment_urls([logo_id, banner_id])

        result = {
            "source": "live",
            "error": "",
            "agentId": c.RCS_AGENT_ID,
            # Deployment config, not registration data — see the note above.
            "smsFallbackNumber": c.SMS_FALLBACK_NUMBER,
            "awsAccountId": c.DEPLOY_ACCOUNT_ID,
            "region": c.REGION,
            "agentStatus": agent.get("Status", ""),
            "testingAgentStatus": testing.get("Status", ""),
            "testingAgentId": testing.get("TestingAgentId", ""),
            "registrationId": registration_id,
            "senderDisplayName": fields.get("agentDetails.senderDisplayName", ""),
            # brandName and senderDisplayName are separate fields and can
            # differ; only senderDisplayName reaches the handset.
            "brandName": fields.get("agentDetails.brandName", ""),
            "serviceName": fields.get("agentDetails.serviceName", ""),
            "agentDescription": fields.get("agentDetails.agentDescription", ""),
            "accentColor": fields.get("agentDetails.accentColor", ""),
            "useCase": fields.get("agentDetails.useCase", ""),
            "billingCategory": fields.get("agentDetails.billingCategory", ""),
            "logoUrl": urls.get(logo_id, ""),
            "bannerUrl": urls.get(banner_id, ""),
            "contacts": [
                {"kind": kind, "label": fields.get(label_path, ""), "value": fields.get(value_path, "")}
                for kind, label_path, value_path in (
                    ("Website", "agentDetails.contactWebsiteLabel", "agentDetails.contactWebsite"),
                    ("Phone", "agentDetails.contactPhoneLabel", "agentDetails.contactPhoneNumber"),
                    ("Email", "agentDetails.contactEmailLabel", "agentDetails.contactEmailAddress"),
                )
                if fields.get(value_path)
            ],
            "privacyPolicyUrl": fields.get("agentDetails.privacyPolicyUrl", ""),
            "termsAndConditionsUrl": fields.get("agentDetails.termsAndConditionsUrl", ""),
        }
    except Exception as e:  # noqa: BLE001
        print(f"get_agent_identity failed: {e}")
        result["error"] = str(e)

    # Cache failures too, briefly: an unauthorized call should not be retried
    # on every card render either.
    _identity_cache["value"] = result
    _identity_cache["expires"] = now + _IDENTITY_TTL_SECONDS
    return result


# ── Brand / theme ───────────────────────────────────────────────────────────
def get_brand():
    b = c.brand()
    sm = c.store_meta()
    return {
        "brandName": b.get("brandName", "AnyHealth"),
        "accentColor": b.get("accentColor", "#0B6E6F"),
        "tagline": b.get("tagline", ""),
        "memberServicesPhone": c.member_services_phone(),
        "storeName": sm.get("storeName", "Store"),
        # Lets the Recipients tab show the exact body to put in the agent's
        # inbound deep link, and warn if a pasted link disagrees with it.
        "deepLinkKeyword": c.deep_link_keyword(),
        # The RCS testing-registration fields, verbatim from brand.md
        # frontmatter. These are what a recipient's messaging app renders as
        # the agent's identity -- name, description, and the contact actions on
        # the agent profile -- so the Settings tab can show what was submitted
        # rather than leaving brand identity as an invisible setup step.
        # senderDisplayName is the string that appears on the handset; the
        # console "friendly name" is a tag and is never shown to recipients.
        "registration": {
            "senderDisplayName": b.get("senderDisplayName", ""),
            "serviceName": b.get("serviceName", ""),
            "agentDescription": b.get("agentDescription", ""),
            "useCase": b.get("useCase", ""),
            "logoImage": b.get("logoImage", ""),
            "bannerImage": b.get("bannerImage", ""),
            "privacyPolicyUrl": b.get("privacyPolicyUrl", ""),
            "termsAndConditionsUrl": b.get("termsAndConditionsUrl", ""),
            "averageMonthlyRcsFrequency": str(b.get("averageMonthlyRcsFrequency", "")),
            "monthlyRcsVolume": str(b.get("monthlyRcsVolume", "")),
            "contacts": [
                {"kind": kind, "label": b.get(label_key, ""), "value": str(b.get(value_key, ""))}
                for kind, label_key, value_key in (
                    ("Website", "contactWebsiteLabel", "contactWebsite"),
                    ("Phone", "contactPhoneLabel", "contactPhoneNumber"),
                    ("Email", "contactEmailLabel", "contactEmailAddress"),
                )
                if b.get(value_key)
            ],
        },
    }


# ── Testers ─────────────────────────────────────────────────────────────────
def get_testers():
    names = get_tester_names()
    # Account-wide opt-out list, fetched once and intersected with each verified
    # number below. A recipient opts out by texting a keyword whose
    # KeywordAction is OPT_OUT (reserved STOP, or a custom OPT_OUT keyword), and
    # the service then refuses further sends to that number, so the Recipients
    # tab flags it.
    opted_out = opted_out_numbers()
    try:
        resp = c.sms_voice.describe_verified_destination_numbers()
        out, seen = [], set()
        for num in resp.get("VerifiedDestinationNumbers", []):
            phone = num.get("DestinationPhoneNumber", "")
            if num.get("RcsAgentId") and num.get("RcsAgentId") != RCS_AGENT_ID:
                continue
            if phone in seen:
                continue
            seen.add(phone)
            ph = c.hash_phone(phone)
            out.append({"phone": phone, "phone_hash": ph, "name": names.get(ph, ""),
                        "status": num.get("Status", "unknown").upper(),
                        # True when this number is on the Default opt-out list;
                        # the recipient texted STOP or a custom OPT_OUT keyword.
                        "opted_out": phone in opted_out,
                        # The handle DeleteVerifiedDestinationNumber needs. Sent
                        # so the dashboard can show what it is about to delete;
                        # delete_tester re-resolves it from the phone rather
                        # than trusting a client-supplied id.
                        "id": num.get("VerifiedDestinationNumberId", ""),
                        "created": str(num.get("CreatedTimestamp", ""))})
        return out
    except Exception as e:  # noqa: BLE001
        print(f"list testers error: {e}")
        return [{"phone": "", "phone_hash": h, "name": n, "status": "UNKNOWN",
                 "opted_out": False} for h, n in names.items()]


def add_tester(phone, name=""):
    if not phone or not phone.startswith("+"):
        return {"error": "Invalid phone. Use E.164 (+1XXXXXXXXXX)"}
    vid = ""
    try:
        resp = c.sms_voice.create_verified_destination_number(DestinationPhoneNumber=phone, RcsAgentId=RCS_AGENT_ID)
        status, vid = "created", resp.get("VerifiedDestinationNumberId", "")
    except c.sms_voice.exceptions.ConflictException:
        status = "already_exists"
    except c.sms_voice.exceptions.ServiceQuotaExceededException as e:  # noqa: BLE001
        # Verified destination numbers are limited to 10 per agent (see
        # content/rcs-features.json limits.testDevicesPerAgent; the AWS quotas
        # page lists this quota as not adjustable). So the eleventh device is
        # only possible after a delete, which is what delete_tester below is
        # for. Named as its own
        # `reason` because the dashboard has to say "delete one first" rather
        # than showing a raw ServiceQuotaExceededException the operator has no
        # action for.
        return {"error": str(e), "reason": "QUOTA_EXCEEDED"}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    # The name is recorded only once AWS has accepted the number. Writing it
    # first (as this used to) left a profile row holding the raw E.164 behind
    # for every add that failed, including every one that hit the cap above.
    if name:
        c.table.put_item(Item={"pk": f"TESTER#{c.hash_phone(phone)}", "sk": "PROFILE", "name": name, "phone": phone})
    return {"status": status, "phone": phone, "name": name, "id": vid}


def delete_tester(phone):
    """Unregister a verified test device, freeing one of the agent's 10 slots.

    `DeleteVerifiedDestinationNumber` takes the `VerifiedDestinationNumberId`,
    not the phone number, so the id is resolved here from the number the
    operator clicked rather than trusted from the request — a client that sent
    the wrong id would otherwise delete someone else's device.

    Only numbers verified against *this* demo's agent are deleted. A number
    verified against a different RCS agent, or against an SMS origination
    identity (the sandbox OTP path), is left alone and reported instead: it
    isn't ours to remove, and it isn't occupying our cap.

    The stored profile row goes too — it holds the raw E.164 and the
    recipient's name, and keeping it once the registration is gone leaves
    contact details with nothing pointing at them. Transcripts are keyed by
    phone hash and are deliberately kept, so Conversations still shows the
    thread; it just loses the name. Re-adding the number restores the thread.
    """
    normalized = c.normalize_phone(phone)
    if not normalized:
        return {"error": f"Invalid phone: {phone}. Use E.164 (+1XXXXXXXXXX)"}
    try:
        resp = c.sms_voice.describe_verified_destination_numbers(DestinationPhoneNumbers=[normalized])
        nums = resp.get("VerifiedDestinationNumbers", [])
    except c.sms_voice.exceptions.ResourceNotFoundException:
        # DescribeVerifiedDestinationNumbers returns ResourceNotFoundException
        # for a number it has no record of — see get_tester_status.
        nums = []
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}

    ours = [n for n in nums if n.get("RcsAgentId") == RCS_AGENT_ID]
    ph = c.hash_phone(normalized)
    if not ours:
        c.table.delete_item(Key={"pk": f"TESTER#{ph}", "sk": "PROFILE"})
        if nums:
            return {"status": "not_ours", "phone": normalized,
                    "error": "Verified against a different origination identity, not this demo's "
                             "RCS agent — left registered. Remove it where it was created."}
        # Already gone from AWS; the local profile is now cleaned up too, so the
        # two agree. Reported as success: the operator's goal is a free slot.
        return {"status": "deleted", "phone": normalized, "ids": [], "note": "was not registered with AWS"}

    ids = []
    for n in ours:
        vid = n.get("VerifiedDestinationNumberId", "")
        try:
            c.sms_voice.delete_verified_destination_number(VerifiedDestinationNumberId=vid)
        except c.sms_voice.exceptions.ResourceNotFoundException:
            pass  # deleted between the describe and here — the end state is what we wanted
        except Exception as e:  # noqa: BLE001
            return {"error": str(e), "phone": normalized, "ids": ids}
        ids.append(vid)
    c.table.delete_item(Key={"pk": f"TESTER#{ph}", "sk": "PROFILE"})
    return {"status": "deleted", "phone": normalized, "ids": ids}


def set_tester_name(phone, name):
    if not phone or not name:
        return {"error": "phone and name required"}
    ph = c.hash_phone(phone)
    c.table.put_item(Item={"pk": f"TESTER#{ph}", "sk": "PROFILE", "name": name, "phone": phone})
    return {"status": "updated", "phone": phone, "name": name}


def get_tester_names():
    resp = c.table.scan(
        FilterExpression="sk = :p AND begins_with(pk, :x)",
        ExpressionAttributeValues={":p": "PROFILE", ":x": "TESTER#"},
    )
    return {i["pk"].replace("TESTER#", ""): i.get("name", "") for i in resp.get("Items", [])}


# ── Custom keywords ─────────────────────────────────────────────────────────
# These are AWS-registered keywords on the RCS agent (PutKeyword /
# DescribeKeywords / DeleteKeyword), NOT the app-side greeting router in
# channel_adapter.py. The distinction matters: when a recipient texts a keyword
# registered here, End User Messaging sends the configured KeywordMessage and
# applies the KeywordAction (AUTOMATIC_RESPONSE, OPT_IN or OPT_OUT), and also
# publishes the message to the two-way topic, so it still reaches this stack's
# Lambda. A keyword registered here arrives with messageKeyword set, and
# _screen_freetext in channel_adapter.py acts on it only when the message text
# begins with that keyword: no reply, no model call, so the member gets one
# answer, and ordinary text after a keyword is still answered.
# The app-side _GREETING_KEYWORDS router, by contrast, only sees messages the
# service forwards inbound and decides which flow to open.
#
# OriginationIdentity is the RCS agent id (verified: the keyword API accepts an
# agent id, so this agent-only stack needs no phone number or pool). HELP and
# STOP are the service's built-in keywords and are always present (they answer
# with the service's default "Default ..." text until put-keyword sets real
# text). This dashboard shows them read-only and refuses to edit or delete them
# (KEYWORD_RESERVED) so an operator cannot remove the compliance responses by
# accident; their text is set from the CLI (AGENTS.md).
_RESERVED_KEYWORDS = {"HELP", "STOP"}
_KEYWORD_ACTIONS = {"AUTOMATIC_RESPONSE", "OPT_IN", "OPT_OUT"}


def get_keywords():
    """List the keywords registered on this demo's RCS agent.

    Each carries its keyword text, the KeywordMessage the service replies with,
    the KeywordAction, and whether it is one of the service-reserved keywords
    (HELP/STOP) that cannot be deleted. Never raises: a failed read degrades to
    an error message in the body so the Settings panel can show that it failed
    rather than break the page. The AWS error text goes to the log, not the
    body, because it carries the caller's role ARN and the account id.
    """
    if not RCS_AGENT_ID:
        return {"keywords": [], "error": "This deployment has no RCS agent configured.", "code": "AGENT_NOT_CONFIGURED"}
    try:
        out, next_token = [], None
        while True:
            kwargs = {"OriginationIdentity": RCS_AGENT_ID, "MaxResults": 100}
            if next_token:
                kwargs["NextToken"] = next_token
            resp = c.sms_voice.describe_keywords(**kwargs)
            for k in resp.get("Keywords", []):
                word = k.get("Keyword", "")
                out.append({
                    "keyword": word,
                    "message": k.get("KeywordMessage", ""),
                    "action": k.get("KeywordAction", ""),
                    "reserved": word.upper() in _RESERVED_KEYWORDS,
                })
            next_token = resp.get("NextToken")
            if not next_token:
                break
        out.sort(key=lambda k: (not k["reserved"], k["keyword"].upper()))
        return {"keywords": out}
    except Exception as e:  # noqa: BLE001
        print(f"get_keywords error: {e}")
        return {
            "keywords": [],
            "error": "Could not load keywords. The cause is in the dashboard function's logs.",
            "code": "KEYWORDS_LOAD_FAILED",
        }


def create_keyword(keyword, message, action="AUTOMATIC_RESPONSE"):
    """Register (or update) a custom keyword on the agent via PutKeyword.

    PutKeyword is an upsert, so this doubles as edit — re-registering an existing
    keyword replaces its message/action.

    Every failure raises ApiError, so it reaches the client as a non-2xx status
    with an `{error, code}` body: a caller that only checks the status must not
    read a rejected write as saved. Input problems are 400. An AWS failure is
    logged here with its detail and answered with a fixed message — the AWS
    error text names the caller's role ARN and the account id.
    """
    keyword = (keyword or "").strip()
    message = (message or "").strip()
    action = (action or "AUTOMATIC_RESPONSE").strip().upper()
    if not keyword:
        raise ApiError(400, "KEYWORD_REQUIRED", "Keyword is required.")
    if not message:
        raise ApiError(400, "MESSAGE_REQUIRED", "Response message is required.")
    if action not in _KEYWORD_ACTIONS:
        raise ApiError(400, "KEYWORD_ACTION_INVALID",
                       f"Invalid keyword action. Use one of: {', '.join(sorted(_KEYWORD_ACTIONS))}.")
    if keyword.upper() in _RESERVED_KEYWORDS:
        raise ApiError(400, "KEYWORD_RESERVED",
                       f"{keyword.upper()} is a service-reserved keyword and cannot be changed here.")
    if not RCS_AGENT_ID:
        raise ApiError(503, "AGENT_NOT_CONFIGURED", "This deployment has no RCS agent configured.")
    try:
        c.sms_voice.put_keyword(
            OriginationIdentity=RCS_AGENT_ID,
            Keyword=keyword,
            KeywordMessage=message,
            KeywordAction=action,
        )
    except c.sms_voice.exceptions.ValidationException as e:
        print(f"create_keyword rejected by the service: {e}")
        raise ApiError(400, "KEYWORD_REJECTED",
                       "The service rejected that keyword or response. "
                       "Check its length and characters, then try again.")
    except Exception as e:  # noqa: BLE001
        print(f"create_keyword error: {e}")
        raise ApiError(502, "KEYWORD_SAVE_FAILED",
                       "Could not save the keyword. The cause is in the dashboard function's logs.")
    return {"status": "created", "keyword": keyword, "message": message, "action": action}


def delete_keyword(keyword):
    """Remove a custom keyword from the agent via DeleteKeyword.

    Reserved keywords (HELP/STOP) are refused by this dashboard: they are the
    service's built-in compliance responses and should not be removed from here.
    Failures raise ApiError with the same contract as create_keyword.
    """
    keyword = (keyword or "").strip()
    if not keyword:
        raise ApiError(400, "KEYWORD_REQUIRED", "Keyword is required.")
    if keyword.upper() in _RESERVED_KEYWORDS:
        raise ApiError(400, "KEYWORD_RESERVED",
                       f"{keyword.upper()} is a service-reserved keyword and cannot be deleted.")
    if not RCS_AGENT_ID:
        raise ApiError(503, "AGENT_NOT_CONFIGURED", "This deployment has no RCS agent configured.")
    try:
        c.sms_voice.delete_keyword(OriginationIdentity=RCS_AGENT_ID, Keyword=keyword)
    except c.sms_voice.exceptions.ResourceNotFoundException:
        # Already gone — the operator's goal (keyword absent) is met.
        return {"status": "deleted", "keyword": keyword, "note": "was not registered"}
    except Exception as e:  # noqa: BLE001
        print(f"delete_keyword error: {e}")
        raise ApiError(502, "KEYWORD_DELETE_FAILED",
                       "Could not delete the keyword. The cause is in the dashboard function's logs.")
    return {"status": "deleted", "keyword": keyword}


def opted_out_numbers():
    """The set of E.164 numbers currently on the account's Default opt-out list.

    A recipient lands here when they text a keyword whose KeywordAction is
    OPT_OUT (the service-reserved STOP, or any custom keyword an operator wires
    to OPT_OUT). It is account-wide, keyed by opt-out list name rather than by
    agent, so the Recipients tab intersects it with the verified numbers to show
    an opt-out column. Returns an empty set on any failure — the column simply
    shows no opt-outs rather than breaking the recipient list.
    """
    try:
        out, next_token = set(), None
        while True:
            kwargs = {"OptOutListName": "Default", "MaxResults": 100}
            if next_token:
                kwargs["NextToken"] = next_token
            resp = c.sms_voice.describe_opted_out_numbers(**kwargs)
            for n in resp.get("OptedOutNumbers", []):
                num = n.get("OptedOutNumber") if isinstance(n, dict) else n
                if num:
                    out.add(num)
            next_token = resp.get("NextToken")
            if not next_token:
                break
        return out
    except Exception as e:  # noqa: BLE001
        print(f"opted_out_numbers error: {e}")
        return set()


def get_testers_with_metrics():
    """Recipients tab data: registered testers + per-recipient RCS activity.

    Message delivery-lifecycle events (RCS_SENT/RCS_DELIVERED/RCS_READ/
    RCS_FAILED) arrive via the ConfigurationSetName event destination and are
    logged by common.log_event; conversation messages are logged by
    common.log_message. Both are stored under the same CONV#{phone_hash}
    partition, so a single query per tester yields everything we can report.
    """
    testers = get_testers()
    return [{**t, **_conversation_metrics(t["phone_hash"])} for t in testers]


def _conversation_metrics(ph):
    """Aggregate per-recipient RCS activity from two distinct sources:

    1. Synchronous SendRcsMessage outcomes (SEND_ACCEPTED / SEND_FAILED),
       logged by common.send_rcs on every call. These are always available
       and are what "Sent" reports on the Recipients tab.
    2. Async platform events (RCS_DELIVERED / RCS_READ / RCS_FAILED /
       RCS_TTL_EXPIRED), logged
       by common.log_event from the configuration set's SNS event destination.
       On a testing agent, delivery events appear once the agent is launched in
       a country; the RCSMessagesDelivered CloudWatch metric counts deliveries
       in the meantime. That metric has no per-recipient dimension, so it
       cannot back these columns. They are counted here so they populate on
       their own after a country launch.

    Delivered/read/failed are keyed on messageStatus, not on the event type:
    RCS_DELIVERED is the type for the whole delivery lifecycle and carries
    DELIVERED, PENDING, UNDELIVERABLE or REJECTED, so a rejected message would
    otherwise be counted as delivered. PENDING and RCS_QUEUED/RCS_SENT are
    deliberately not counted anywhere — "Sent" already comes from the
    synchronous API result, and counting both would double every send.
    RCS_TYPING/CONVERSATION_STARTED are inbound signals stored in the same event
    shape (see common.log_indicator) and are counted in no column at all.

    A message that fell back to SMS can legitimately increment *both*
    fell_back_to_sms and failed, because two separate events describe it: the
    RCS leg genuinely failed (RCS_FAILED or RCS_TTL_EXPIRED) and then
    RCS_FALLEN_BACK_TO_SMS says the member was reached anyway. They are not
    deduplicated — correlating them would mean matching on messageId across
    rows, and the honest reading of the two columns together is "RCS didn't
    land, SMS covered it", which is exactly what the fallback demo is showing.
    """
    resp = c.table.query(
        KeyConditionExpression=Key("pk").eq(f"CONV#{ph}") & Key("sk").begins_with("MSG#"),
    )
    sent = delivered = read = failed = inbound = outbound = fell_back = 0
    last_activity = ""
    for i in resp.get("Items", []):
        ts = i.get("timestamp", "")
        if ts > last_activity:
            last_activity = ts
        direction = i.get("direction", "")
        if direction == "event":
            event_type = i.get("event_type", "")
            status = i.get("message_status", "")
            if event_type == "SEND_ACCEPTED":
                sent += 1
            elif event_type == "SEND_FAILED":
                failed += 1
            elif event_type == "RCS_READ" or status == "READ":
                read += 1
            elif status == "DELIVERED" or (event_type == "RCS_DELIVERED" and not status):
                # The "and not status" arm covers an event that arrives without
                # messageStatus: the type alone still means the delivery
                # lifecycle reached a terminal success.
                delivered += 1
            elif event_type == "RCS_FALLEN_BACK_TO_SMS":
                # Previously matched no branch at all, so a fallback — the one
                # outcome this demo most wants to show — was invisible. Its own
                # column rather than folded into failed: the RCS attempt failed
                # but the member was still reached, and calling that a failure
                # undersells the feature while calling it a delivery overstates
                # it. The RCS_FAILED/RCS_TTL_EXPIRED sibling event still counts
                # in failed; see the docstring on why that isn't deduplicated.
                fell_back += 1
            elif status in ("UNDELIVERABLE", "REJECTED") or event_type in (
                # RCS_TTL_EXPIRED is the event for TTL expiry: no delivery
                # confirmation arrived, which is a failed RCS delivery. See
                # common._EVENT_EXPLANATIONS for the enum.
                "RCS_FAILED", "RCS_TTL_EXPIRED", "RCS_PROTECT_BLOCKED"
            ):
                failed += 1
        elif direction == "inbound":
            inbound += 1
        elif direction == "outbound":
            outbound += 1
    return {
        "messages_sent": sent,
        "messages_received": inbound,
        "delivered": delivered,
        "read": read,
        "failed": failed,
        "fell_back_to_sms": fell_back,
        "last_activity": last_activity,
    }


def get_tester_status(phone):
    if not phone:
        return {"error": "phone required"}
    # DescribeVerifiedDestinationNumbers expects exact E.164 (a stored phone
    # missing its leading "+" returns ResourceNotFoundException), which this
    # endpoint used to return as an opaque {"error": ...} with no "status" field —
    # the dashboard then showed "unknown" with no indication why. Normalize
    # first so a number that is not yet in E.164 form still resolves correctly.
    normalized = c.normalize_phone(phone)
    if not normalized:
        return {"phone": phone, "status": "INVALID_PHONE"}
    try:
        resp = c.sms_voice.describe_verified_destination_numbers(DestinationPhoneNumbers=[normalized])
        nums = resp.get("VerifiedDestinationNumbers", [])
        return {"phone": normalized, "status": nums[0].get("Status", "unknown").upper() if nums else "NOT_FOUND"}
    except Exception as e:  # noqa: BLE001
        return {"phone": normalized, "status": "ERROR", "error": str(e)}


# ── Conversations ───────────────────────────────────────────────────────────
def get_conversations():
    resp = c.table.scan(
        FilterExpression="sk = :m AND begins_with(pk, :x)",
        ExpressionAttributeValues={":m": "META", ":x": "CONV#"},
    )
    names = get_tester_names()
    convs = []
    for i in resp.get("Items", []):
        ph = i["pk"].replace("CONV#", "")
        convs.append({"phone_hash": ph, "name": names.get(ph, ""),
                      "last_message": i.get("last_message", ""), "last_direction": i.get("last_direction", ""),
                      "mode": c.get_mode(ph)})
    convs.sort(key=lambda x: x.get("last_message", ""), reverse=True)
    return {"conversations": convs[:50]}


# The transcript is the newest _CONVERSATION_ROWS rows of the conversation,
# returned oldest first. Event rows (send results, delivery receipts) share the
# MSG# key space with messages, so they would crowd real messages out of that
# budget; when they are not wanted they are dropped *before* counting. DynamoDB
# applies Limit ahead of any filter, so the query is paged and filtered here
# rather than asking for 200 rows and hoping enough of them are messages. The
# page cap bounds the work: at most _CONVERSATION_MAX_PAGES * _CONVERSATION_ROWS
# of the newest rows are read, which only matters to a conversation that is
# overwhelmingly events (they expire after 7 days, messages after 30).
_CONVERSATION_ROWS = 200
_CONVERSATION_MAX_PAGES = 5


def get_conversation_detail(ph, include_events=False):
    # Newest first, so the budget is spent on the latest rows; reversed below to
    # the chronological order the dashboard renders. (Ascending order with a
    # Limit would return the *oldest* rows and silently drop everything recent
    # once a conversation outgrows the limit.)
    query = {
        "KeyConditionExpression": Key("pk").eq(f"CONV#{ph}") & Key("sk").begins_with("MSG#"),
        "ScanIndexForward": False,
        "Limit": _CONVERSATION_ROWS,
    }
    rows = []
    for _ in range(_CONVERSATION_MAX_PAGES):
        resp = c.table.query(**query)
        rows.extend(
            i for i in resp.get("Items", [])
            if include_events or i.get("direction", "") != "event"
        )
        last_key = resp.get("LastEvaluatedKey")
        if len(rows) >= _CONVERSATION_ROWS or not last_key:
            break
        query["ExclusiveStartKey"] = last_key
    rows = rows[:_CONVERSATION_ROWS]
    rows.reverse()

    messages = []
    for i in rows:
        d = i.get("direction", "")
        if d == "event":
            messages.append({"type": "event", "event_type": i.get("event_type", i.get("body", "")), "timestamp": i.get("timestamp", "")})
            continue
        msg = {"type": "message", "direction": d, "body": i.get("body", ""), "timestamp": i.get("timestamp", "")}
        if i.get("actor"):
            msg["actor"] = i["actor"]
        if i.get("rcs_content"):
            try:
                msg["rcs_content"] = json.loads(i["rcs_content"])
            except (json.JSONDecodeError, TypeError):
                pass
        if i.get("media_content"):
            try:
                msg["media_content"] = json.loads(i["media_content"])
            except (json.JSONDecodeError, TypeError):
                pass
        messages.append(msg)
    names = get_tester_names()
    return {"phone_hash": ph, "name": names.get(ph, ""), "mode": c.get_mode(ph), "messages": messages}


# ── Triggers / push / agent console ─────────────────────────────────────────
def _invoke_adapter(push):
    lambda_client.invoke(
        FunctionName=LAMBDA_CHANNEL_ADAPTER,
        InvocationType="Event",
        Payload=json.dumps({"push": push}).encode(),
    )


def trigger_flow(phone, trigger):
    if not phone or not trigger:
        return {"error": "phone and trigger required"}
    vignette = trigger.replace("Start: ", "").replace("push:", "").strip()
    _invoke_adapter({"phone": phone, "vignette": vignette})
    return {"status": "triggered", "phone": phone, "vignette": vignette}


def push_message(p):
    if not p.get("phone"):
        return {"error": "phone required"}
    _invoke_adapter({"phone": p["phone"], "rcs_content": p.get("rcs_content")})
    return {"status": "pushed", "phone": p["phone"]}


def start_video_visit(p):
    """Operator side of the video visit: mint one visit token, send the member
    the invitation card, and hand the same token back so the dashboard modal can
    join the same Chime meeting as the clinician.

    The token has to be minted here rather than inside the flow, because both
    ends need it and the flow's own send path has no way to return anything to
    the caller — the push into the channel adapter is an async Event invoke.
    """
    phone = p.get("phone", "")
    if not phone:
        return {"error": "phone required"}
    token = video_visit.create_visit(phone_hash=c.hash_phone(phone), label="Video visit")
    # Push the token, not a built card. Two reasons, in order of importance:
    #
    #  • The card's chips are webview links, and c.webview_url() only produces an
    #    absolute https:// URL where API_BASE_URL is set — which is the channel
    #    adapter, not here. Built in this function the URLs come out relative and
    #    SendRcsMessage rejects them as empty. See channel_adapter.handle_push.
    #  • Not the plain trigger path either: that lets the flow mint a *second*
    #    token, so the member and the operator would join different meetings and
    #    each see an empty room — which looks like a WebRTC connection problem.
    _invoke_adapter({"phone": phone, "visit_token": token})
    return {"status": "started", "phone": phone, "visit": token}


def preview_video_visit(p):
    """Mint a visit token and send nothing.

    This is the video-visit half of "Device preview": it lets the operator open
    the member's own webview — the real page, in an iframe, with real camera
    permissions — without a handset and without spending a send. The token is an
    ordinary visit token with the ordinary TTL, so the preview exercises exactly
    the code path a member's tap does, rather than a mock of it.

    Labelled distinctly so a preview is recognisable in the table, and carrying no
    phone_hash: nobody is being messaged, and there is no conversation to tie it to.
    """
    token = video_visit.create_visit(label="Video visit (preview)")
    return {"visit": token}


def agent_reply(p):
    """Human agent reply from the dashboard console during live handover."""
    if not p.get("phone") or not p.get("message"):
        return {"error": "phone and message required"}
    _invoke_adapter({"phone": p["phone"], "agent_message": p["message"], "agent": p.get("agent", "Care Advocate")})
    return {"status": "sent", "phone": p["phone"]}


def set_mode(p):
    phone = p.get("phone", "")
    mode = p.get("mode", "bot")
    if not phone or mode not in ("bot", "live"):
        return {"error": "phone and mode (bot|live) required"}
    c.set_mode(c.hash_phone(phone), mode, agent=p.get("agent", ""))
    return {"status": "ok", "phone": phone, "mode": mode}


def get_mode(phone):
    """Lets the status bar (web/src/components/StatusBar.tsx) show whether the currently
    targeted device is in live-agent handover, without needing the full
    conversation list — a member/demo left in live mode has every
    deterministic-flow button silently dropped, so this needs to be visible
    wherever the operator is working, not just on the 2-way Conversations
    tab."""
    if not phone:
        return {"error": "phone required"}
    return {"phone": phone, "mode": c.get_mode(c.hash_phone(phone))}


# ── Media / reset ───────────────────────────────────────────────────────────
# GET /api/media is the one read route that cannot sit behind the API-key
# authorizer: its response is consumed directly as an <img src> (see
# web/src/api.ts mediaUrl, used by Conversations.tsx and PhonePreviewPopover.tsx)
# and a browser will not attach an x-api-key header to an image request. So the
# control here is the key itself: only objects this demo actually renders may be
# presigned. Without this, an anonymous caller could presign any object the
# function role can read, which includes secure-docs/ (get_secure_doc below
# presigns it with the same role).
#
# raw-uploads/ is deliberately excluded: the UI always renders the converted
# JPEG, so the pre-conversion originals a member uploaded should never be
# presignable over HTTP.
_MEDIA_ALLOWED_PREFIXES = (
    "media/",                              # card + product art (BucketDeployment)
    f"{c.S3_INBOUND_MEDIA_PREFIX}/rcs/",   # native inbound RCS photos
    "converted-inbound/",                  # converted native inbound photos
    f"{c.UPLOAD_CONVERTED_PREFIX}/",       # converted webview uploads
)


def get_media_url(key):
    if not key:
        return {"error": "key required"}
    # Reject traversal and anything outside the renderable prefixes. Checked
    # before the presign call so no signature is ever produced for a bad key.
    if ".." in key or not key.startswith(_MEDIA_ALLOWED_PREFIXES):
        print(f"get_media_url: refused key outside allow-list: {key[:120]!r}")
        return {"error": "forbidden"}
    s3 = boto3.client("s3", region_name=c.REGION)
    return s3.generate_presigned_url("get_object", Params={"Bucket": c.S3_BUCKET, "Key": key}, ExpiresIn=3600)


# ── Secure documents (the webview path, not the carrier path) ───────────────
# The documents a member may see but that must never be sent as an RCS
# FileMessage, because they identify an individual. Deliberately NOT added to
# _MEDIA_ALLOWED_PREFIXES above: that route presigns any key under an allowed
# prefix, so allow-listing `secure-docs/` there would make the patient record
# presignable by anyone who guessed its key. Here the caller may only name a
# document by id, and the id is mapped to a key by this table.
_SECURE_DOCS = {
    # id -> (S3 key, filename shown to the member)
    "patient-info": ("secure-docs/rx-patient-info.pdf", "prescription-record.pdf"),
}


def get_secure_doc(phone_hash, doc_id):
    """Hand the in-conversation webview a short-lived link to a member document.

    This is the other half of the pharmacy vignette's teaching point. The
    generic fact sheet goes out as a `FileMessage`, so AWS fetches it from S3,
    rehosts it, and it crosses the RCS/carrier network. The document below never
    does: the member taps a `WEBVIEW` suggestion, the page calls this route, and
    the bytes travel from S3 to that browser over HTTPS. Nothing about the
    member enters the message stream, and neither the bucket policy for the EUM
    service principal nor the channel adapter's role in
    cdk/lib/anyhealth-stack.ts grants read access to `secure-docs/`, and a file
    message naming this document was refused with RESOURCE_NOT_ACCESSIBLE on a
    test deployment. The dashboard's own role does hold that read, to presign it
    here, and shares the adapter's sms-voice:SendRcsMessage grant; nothing in
    this module sends a message.

    What this is not: authenticated. Like the other webview-backed routes, it
    carries no API key — a member's in-app browser session has none to give —
    and the `ph` it is scoped to is `common.hash_phone`, an unsalted SHA-256 of
    the E.164 number, so someone who knows the number can compute it. The check
    below (the hash must belong to a conversation this demo has actually had)
    stops a scan, not a targeted guess. A production system serving real PHI
    needs a real member session on this route, per-member object keys, and an
    access log of every fetch. What the demo does establish is the transport
    decision, which builders should make deliberately: sensitive documents
    leave the carrier path entirely.
    """
    entry = _SECURE_DOCS.get(doc_id or "")
    if not phone_hash or not entry:
        return {"error": "phone_hash and a known doc are required"}
    if not c.conversation_history(phone_hash, limit=1):
        # No conversation under this hash, so nothing here belongs to it.
        print(f"get_secure_doc: no conversation for {phone_hash[:12]!r}")
        return {"error": "forbidden"}
    key, filename = entry
    s3 = boto3.client("s3", region_name=c.REGION)
    return {
        "filename": filename,
        # 300s: long enough to tap through, short enough that a link copied out
        # of the browser is dead before it can be shared.
        "url": s3.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": c.S3_BUCKET,
                "Key": key,
                # Name the download rather than letting the browser derive
                # "rx-patient-info.pdf" from the key.
                "ResponseContentDisposition": f'inline; filename="{filename}"',
            },
            ExpiresIn=300,
        ),
    }


def get_latest_media_for_demo(phone):
    """Backs the Demo tab's "latest photo received" preview on the two
    rich-media vignette cards (photo_submission = native RCS inbound,
    insurance_upload = webview upload). The two paths store their state
    completely differently — native media lives in the conversation log
    (common.set/get_latest_media), webview uploads live in their own
    UPLOAD# records (common.get_latest_upload) — so this reads both and
    returns a preview_url + one-sentence classification for whichever
    exist, letting the frontend render each vignette card independently."""
    if not phone:
        return {"error": "phone required"}
    ph = c.hash_phone(phone)
    s3 = boto3.client("s3", region_name=c.REGION)
    result = {}

    native = c.get_latest_media(ph)
    if native.get("media"):
        media = native["media"]
        # Prefer the browser/RCS-safe JPEG made by media_convert. The raw
        # source key stays in metadata for audit/debugging, but may be HEIC.
        s3_key = media.get("convertedS3Key") or media.get("s3Key", "")
        # Conversion is asynchronous, so the receipt lands here seconds before
        # the JPEG exists (common.set_latest_media is called twice). Presigning
        # the raw key during that window hands the browser a HEIC it renders as
        # a broken image; withhold the URL until there's something renderable,
        # and report `converting` so the card can show a pending state rather
        # than a permanent-looking failure. A JPEG/PNG needs no conversion to
        # preview, so it still renders immediately — `converting` only tells the
        # card its GenAI description is still coming.
        renderable = c.media_browser_renderable(media)
        result["photo_submission"] = {
            "preview_url": s3.generate_presigned_url(
                "get_object", Params={"Bucket": c.S3_BUCKET, "Key": s3_key}, ExpiresIn=3600,
            ) if s3_key and renderable else None,
            "converting": c.media_conversion_pending(media),
            "classification": native.get("classification", ""),
            "file_name": media.get("fileName", ""),
            "updated": native.get("updated", ""),
        }

    upload = c.get_latest_upload(ph)
    if upload.get("converted_key"):
        result["insurance_upload"] = {
            "preview_url": s3.generate_presigned_url(
                "get_object", Params={"Bucket": c.S3_BUCKET, "Key": upload["converted_key"]}, ExpiresIn=3600,
            ),
            "classification": upload.get("classification", ""),
            "file_name": "",
            "updated": upload.get("created_at", ""),
        }

    return result


# ── Webview uploads (secure document upload) ─────────────────────────────────
_UPLOAD_ACCEPTED_CONTENT_TYPES = {
    "image/heic", "image/heif", "image/jpeg", "image/jpg", "image/png",
}


# What common.hash_phone produces: "anon-" plus 24 lowercase hex characters.
# Matched with fullmatch, never `$`, which also accepts a trailing newline.
_PHONE_HASH_RE = re.compile(r"anon-[0-9a-f]{24}")


def create_upload_url(p):
    """Called from lambda/webviews/upload-insurance-card.html. Returns a
    presigned S3 PUT URL scoped to a fresh object key under
    common.UPLOAD_RAW_PREFIX/{phone_hash}/ — the browser PUTs the file bytes
    directly to S3 with this URL; they never pass through this Lambda or any
    other AWS API surface, matching the compliance-forward design described
    in insurance_upload.py.

    This route is unauthenticated (the caller is a member's in-app browser, which
    holds no API key), so the hash it is handed is validated rather than trusted.
    It becomes part of an S3 key, selects whose "latest upload" the upload lands
    in, and starts a Lambda and Bedrock calls. It must therefore be exactly what
    common.hash_phone produces, and the conversation must exist — the same check
    get_secure_doc applies. Every link this demo sends carries such a hash for a
    conversation it just wrote to. As in get_secure_doc, the hash is computable
    from a phone number, so the check stops arbitrary input and scans, not a
    caller who knows a member's number.
    """
    if not isinstance(p, dict):
        p = {}
    phone_hash = p.get("phone_hash")
    content_type = p.get("content_type")
    if (not isinstance(phone_hash, str) or not _PHONE_HASH_RE.fullmatch(phone_hash)
            or not isinstance(content_type, str)
            or content_type not in _UPLOAD_ACCEPTED_CONTENT_TYPES):
        raise ApiError(400, "INVALID_UPLOAD_REQUEST",
                       "A valid upload link and a supported image type are required.")
    if not c.conversation_history(phone_hash, limit=1):
        # No conversation under this hash, so no link this demo sent produced it.
        print(f"create_upload_url: no conversation for {phone_hash[:12]!r}")
        raise ApiError(404, "UPLOAD_LINK_INVALID",
                       "This upload link is not valid. Reopen it from your message thread.")
    upload = c.new_upload(phone_hash, content_type)
    s3 = boto3.client("s3", region_name=c.REGION)
    put_url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": c.S3_BUCKET, "Key": upload["raw_key"], "ContentType": content_type},
        ExpiresIn=600,
    )
    return {"upload_id": upload["upload_id"], "put_url": put_url}


def get_upload_status(phone_hash, upload_id):
    """Polled by the webview after the browser's S3 PUT completes, until
    media_convert.py (triggered by the S3 object-created event) finishes
    normalizing the file to a displayable JPEG and flips status to READY."""
    if not phone_hash or not upload_id:
        return {"error": "phone_hash and upload_id required"}
    upload = c.get_upload(phone_hash, upload_id)
    if not upload:
        return {"status": "NOT_FOUND"}
    result = {"status": upload.get("status", "PENDING")}
    if upload.get("classification"):
        result["classification"] = upload["classification"]
    if upload.get("error"):
        result["error"] = upload["error"]
    if upload.get("converted_key"):
        s3 = boto3.client("s3", region_name=c.REGION)
        result["preview_url"] = s3.generate_presigned_url(
            "get_object", Params={"Bucket": c.S3_BUCKET, "Key": upload["converted_key"]}, ExpiresIn=3600,
        )
    return result


def _delete_resettable_media() -> int:
    """Delete every version and delete marker for member/demo-generated media.

    The media bucket is versioned. A plain DeleteObject would only add a
    delete marker while leaving prior copies (and their cost/privacy footprint)
    behind, so Reset intentionally deletes all versions. Static content under
    media/ and secure-docs/ is deliberately excluded: those are committed
    brand/product/document assets a BucketDeployment put there, and the demo
    needs them after a reset.
    """
    prefixes = (
        f"{c.S3_INBOUND_MEDIA_PREFIX}/rcs/",
        f"{c.UPLOAD_RAW_PREFIX}/",
        f"{c.UPLOAD_CONVERTED_PREFIX}/",
        "converted-inbound/",
    )
    s3 = boto3.client("s3", region_name=c.REGION)
    deleted = 0
    paginator = s3.get_paginator("list_object_versions")

    for prefix in prefixes:
        for page in paginator.paginate(Bucket=c.S3_BUCKET, Prefix=prefix):
            identifiers = [
                {"Key": item["Key"], "VersionId": item["VersionId"]}
                for item in page.get("Versions", []) + page.get("DeleteMarkers", [])
            ]
            # S3 DeleteObjects accepts up to 1,000 object versions at once.
            for start in range(0, len(identifiers), 1000):
                response = s3.delete_objects(
                    Bucket=c.S3_BUCKET,
                    Delete={"Objects": identifiers[start:start + 1000], "Quiet": True},
                )
                errors = response.get("Errors", [])
                if errors:
                    raise RuntimeError(f"Unable to delete resettable media: {errors}")
                deleted += len(response.get("Deleted", []))
    return deleted


def reset_data():
    # Delete media first. If S3 cleanup fails, leave the DynamoDB state intact
    # rather than making the dashboard forget objects that still exist.
    deleted_media_objects = _delete_resettable_media()

    # UPLOAD#/NATIVE_MEDIA# rows are media-state indexes; CONV# includes
    # messages and LATEST_MEDIA. Scan every page so reset is complete even
    # after a long demo session.
    scan_args = {
        "FilterExpression": (
            "begins_with(pk, :c) OR begins_with(pk, :f) OR begins_with(pk, :cart) "
            "OR begins_with(pk, :o) OR begins_with(pk, :u) OR begins_with(pk, :n)"
        ),
        "ExpressionAttributeValues": {
            ":c": "CONV#", ":f": "FLOW#", ":cart": "CART#", ":o": "OTP#",
            ":u": "UPLOAD#", ":n": "NATIVE_MEDIA#",
        },
        "ProjectionExpression": "pk, sk",
    }
    items = []
    while True:
        response = c.table.scan(**scan_args)
        items.extend(response.get("Items", []))
        if not response.get("LastEvaluatedKey"):
            break
        scan_args["ExclusiveStartKey"] = response["LastEvaluatedKey"]

    with c.table.batch_writer() as batch:
        for item in items:
            batch.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
    return {
        "status": "reset",
        "deleted": len(items),
        "deleted_media_objects": deleted_media_objects,
    }
