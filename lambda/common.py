"""
Shared helpers for the AnyHealth Lambdas.

Everything the channel adapter, dashboard, and flows share lives here:
brand/content loading (from bundled content/*.md), the RCS send path
(SendRcsMessage with ConfigurationSetName — no SigV4 fallback), media/webview
URL resolution, and all DynamoDB state (conversations, active flow, handover
mode, and cart). Nothing is hardcoded; every environment-specific value comes
from environment variables set by the CDK stack.
"""

import os
import re
import json
import time
import uuid
import hashlib
import numbers
import urllib.parse
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

# ── Environment (all injected by the CDK stack) ─────────────────────────────
REGION = os.environ.get("AWS_REGION", "us-east-1")
RCS_AGENT_ID = os.environ.get("RCS_AGENT_ID", "")
# The AWS account this stack is deployed in, from the CDK stack. Display only
# (Settings tab); empty on a deployment that predates the variable.
DEPLOY_ACCOUNT_ID = os.environ.get("DEPLOY_ACCOUNT_ID", "")
DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "")
S3_BUCKET = os.environ.get("S3_BUCKET", "")
S3_INBOUND_MEDIA_PREFIX = os.environ.get("S3_INBOUND_MEDIA_PREFIX", "inbound")
CONFIG_SET_NAME = os.environ.get("CONFIG_SET_NAME", "")
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6")
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", REGION)
API_BASE_URL = os.environ.get("API_BASE_URL", "").rstrip("/")
# SMS-capable origination identity for per-message fallback. Empty unless the
# stack was deployed with `-c smsFallbackNumber=+1…`; when empty, send_rcs omits
# FallbackConfiguration entirely rather than sending a half-built one.
SMS_FALLBACK_NUMBER = os.environ.get("SMS_FALLBACK_NUMBER", "")

_CONTENT_DIR = os.path.join(os.path.dirname(__file__), "_content")

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(DYNAMODB_TABLE) if DYNAMODB_TABLE else None
sms_voice = boto3.client("pinpoint-sms-voice-v2", region_name=REGION)

TTL_CONVERSATION_DAYS = 30
TTL_FLOW_MINUTES = 30

# ── Content (bundled content/*.md) ──────────────────────────────────────────
_cache: dict = {}


def _read(name: str) -> str:
    with open(os.path.join(_CONTENT_DIR, name), "r", encoding="utf-8") as fh:
        return fh.read()


def content_frontmatter(name: str) -> dict:
    key = name + "#fm"
    if key not in _cache:
        import yaml  # provided by the dependency layer

        raw = _read(name)
        m = re.match(r"^---\n(.*?)\n---", raw, re.S)
        _cache[key] = (yaml.safe_load(m.group(1)) if m else {}) or {}
    return _cache[key]


def content_body(name: str) -> str:
    key = name + "#body"
    if key not in _cache:
        raw = _read(name)
        _cache[key] = re.sub(r"^---\n.*?\n---\n?", "", raw, count=1, flags=re.S).strip()
    return _cache[key]


# ── RCS feature registry (content/rcs-features.json) ────────────────────────
# Every documented RCS limit and every feature explanation this project shows a
# builder lives in that one file, so a limit change from AWS is a one-line edit
# there rather than a hunt through prose, validators and dashboard copy.
# scripts/check-rcs-registry.py checks nothing has drifted apart from the code.
# Do not hardcode a limit anywhere else.
def rcs_registry() -> dict:
    if "rcs#registry" not in _cache:
        try:
            _cache["rcs#registry"] = json.loads(_read("rcs-features.json"))
        except FileNotFoundError as e:
            # Staged by stageContentForLambda() at synth. Missing means the
            # staging filter dropped it — fail loudly rather than silently
            # validating against nothing.
            raise RuntimeError(
                "content/rcs-features.json was not staged into the Lambda bundle; "
                "check stageContentForLambda() in cdk/lib/config.ts"
            ) from e
    return _cache["rcs#registry"]


def rcs_limit(key: str) -> int:
    """The documented AWS value for one RCS limit. KeyError on an unknown key is
    deliberate: a typo must break loudly, not silently validate against None."""
    return int(rcs_registry()["limits"][key]["value"])


def rcs_feature(key: str) -> dict:
    """One feature entry, or {} if the key is unknown. Callers that must not
    tolerate an unknown key (the /api/vignettes resolver) check for {}."""
    for f in rcs_registry().get("features", []):
        if f.get("key") == key:
            return f
    return {}


def rcs_doc_url(path: str) -> str:
    """Absolute AWS docs URL from a registry-relative `doc` value."""
    if not path:
        return ""
    if path.startswith("http"):
        return path
    return rcs_registry().get("docBaseUrl", "") + path


# ── Brand accessors ─────────────────────────────────────────────────────────
def brand() -> dict:
    return content_frontmatter("brand.md")


def brand_name() -> str:
    return brand().get("brandName", "AnyHealth")


def deep_link_keyword() -> str:
    """The message body the agent's inbound deep link pre-populates, which the
    channel adapter treats as "open the welcome message". Generated in the
    console under your RCS agent → Testing → Inbound deep link; the dashboard's
    Recipients tab shows the QR code for it."""
    return brand().get("deepLinkKeyword", "Get started")


def member_name() -> str:
    """The sample member in brand.md. Only a fallback for the real recipient —
    member-facing flows should prefer tester_name(phone_hash, member_name())
    so the handset hears the name assigned on the Recipients tab."""
    return brand().get("memberName", "a member")


def accent_color() -> str:
    return brand().get("accentColor", "#0B6E6F")


def member_services_phone() -> str:
    return brand().get("memberServicesPhone") or brand().get(
        "contactPhoneNumber", "+18005550100"
    )


def sms_fallback_active() -> bool:
    """Whether per-message SMS fallback is actually live in this deployment.

    True only when the stack was deployed with `-c smsFallbackNumber=+1…`, which
    populates SMS_FALLBACK_NUMBER. When False, send_rcs attaches no
    FallbackConfiguration at all (see send_rcs), so any copy that promises SMS
    fallback would be describing behavior this deployment does not have. The
    welcome education card reads this so it can say "on" vs "off in this demo"
    truthfully rather than guessing."""
    return bool(SMS_FALLBACK_NUMBER)


def store_products() -> list:
    return content_frontmatter("store.md").get("products", []) or []


def store_meta() -> dict:
    fm = content_frontmatter("store.md")
    return {
        "storeName": fm.get("storeName", "Store"),
        "currency": fm.get("currency", "USD"),
    }


def product_by_id(pid: str):
    for p in store_products():
        if p.get("id") == pid:
            return p
    return None


# ── Workplace accessors (internal staff vignettes) ──────────────────────────
def workplace() -> dict:
    return content_frontmatter("workplace.md")


def employee_name() -> str:
    return workplace().get("employeeName", "Employee")


def employee_role() -> str:
    return workplace().get("employeeRole", "Staff")


def work_location() -> str:
    return workplace().get("location", "your work site")


def manager_name() -> str:
    return workplace().get("managerName", "your manager")


def pto_balance_days() -> float:
    return float(workplace().get("ptoBalanceDays", 0))


def shifts() -> list:
    return workplace().get("shifts", []) or []


def shift_by_id(sid: str):
    for s in shifts():
        if s.get("id") == sid:
            return s
    return None


def coworkers() -> list:
    return workplace().get("coworkers", []) or []


def coworker_by_id(cid: str):
    for cw in coworkers():
        if cw.get("id") == cid:
            return cw
    return None


def tester_name(phone_hash: str, fallback: str = "") -> str:
    """Look up the display name assigned to a phone number on the dashboard's
    Recipients tab (TESTER#{phone_hash}/PROFILE, written by set_tester_name /
    add_tester in dashboard_handler.py). Falls back to `fallback` if there's
    no phone_hash (e.g. a dashboard preview), no tester record, or the tester
    has no name set yet."""
    if not phone_hash or not table:
        return fallback
    item = table.get_item(Key={"pk": f"TESTER#{phone_hash}", "sk": "PROFILE"}).get("Item")
    return (item or {}).get("name") or fallback


# ── RCS send ────────────────────────────────────────────────────────────────
_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")


def normalize_phone(raw: str) -> str | None:
    """Normalize user/API input to E.164. SendRcsMessage rejects anything else
    with ValidationException(INVALID_PARAMETER, destinationPhoneNumber), so
    this must run before any send — regardless of which client called the API."""
    trimmed = (raw or "").strip()
    if not trimmed:
        return None
    digits = re.sub(r"[^\d+]", "", trimmed)
    if digits.startswith("+"):
        candidate = digits
    elif len(digits) == 10:
        candidate = f"+1{digits}"
    elif len(digits) == 11 and digits.startswith("1"):
        candidate = f"+{digits}"
    else:
        candidate = f"+{digits}"
    return candidate if _E164_RE.match(candidate) else None


def validate_rcs_content(rcs_content: dict) -> str | None:
    """Return a human-readable reason this payload would be rejected, or None.

    Every bound checked here comes from content/rcs-features.json, which is the
    project's transcription of the AWS "RCS quotas and limits" tables. Nothing
    is hardcoded, so when AWS changes a number the validator, the docs and the
    dashboard tooltips all move together.

    Why validate at all: SendRcsMessage rejects an out-of-range payload with a
    ValidationException before the message leaves the account, and that failure
    used to be invisible twice over — send_rcs records every exception as a
    SEND_FAILED event, and the dashboard's device preview renders an over-long
    carousel perfectly happily. So an operator could watch a 12-card welcome
    "work" on screen while every real handset got nothing. Checked here, at the
    one point the send path and the preview path share, so content edits
    surface the problem in both places instead of neither.
    """
    if not isinstance(rcs_content, dict):
        return "RCS content must be a dict"
    content = rcs_content.get("Content") or {}

    body = (content.get("TextMessage") or {}).get("Body") or ""
    if len(body) > rcs_limit("textBodyChars"):
        return _too_long("RCS text body", len(body), "textBodyChars")

    cards = (content.get("Carousel") or {}).get("CardContents")
    if cards is not None:
        lo, hi = rcs_limit("carouselCardsMin"), rcs_limit("carouselCardsMax")
        if not lo <= len(cards) <= hi:
            return f"RCS carousel requires {lo}-{hi} cards, got {len(cards)}"
        for i, card in enumerate(cards):
            bad = _validate_card(card, f"carousel card {i + 1}")
            if bad:
                return bad

    # A file message is referenced by URL, so the only thing checkable before
    # the send is the URL length — the 100 MB file limit is a property of the
    # object in S3, which this process cannot see without a HEAD it would have
    # to pay for on every send.
    file_msg = content.get("FileMessage") or {}
    for field in ("FileUrl", "ThumbnailUrl"):
        url = file_msg.get(field) or ""
        if len(url) > rcs_limit("mediaUrlChars"):
            return _too_long(f"file message {field}", len(url), "mediaUrlChars")

    single = (content.get("RichCard") or {}).get("CardContent")
    if single is not None:
        bad = _validate_card(single, "rich card")
        if bad:
            return bad

    # Message-level suggestions allow 11 per message; card-level suggestions
    # allow 4.
    bad = _validate_suggestions(
        rcs_content.get("Suggestions"), "message", "suggestionsPerMessage"
    )
    if bad:
        return bad
    return None


def _too_long(what: str, actual: int, limit_key: str) -> str:
    limit = rcs_registry()["limits"][limit_key]
    return (
        f"{what} is {actual} characters; the documented RCS limit is "
        f"{limit['value']} ({limit['label']})"
    )


def _validate_card(card: dict, where: str) -> str | None:
    if not isinstance(card, dict):
        return f"{where} must be a dict"
    title = card.get("Title") or ""
    if len(title) > rcs_limit("richCardTitleChars"):
        return _too_long(f"{where} title", len(title), "richCardTitleChars")
    desc = card.get("Description") or ""
    if len(desc) > rcs_limit("richCardDescriptionChars"):
        return _too_long(f"{where} description", len(desc), "richCardDescriptionChars")
    return _validate_suggestions(card.get("Suggestions"), where, "suggestionsPerCard")


def _validate_suggestions(suggestions, where: str, count_key: str) -> str | None:
    if not suggestions:
        return None
    limit = rcs_limit(count_key)
    if len(suggestions) > limit:
        return (
            f"{where} has {len(suggestions)} suggestions; the documented RCS "
            f"limit is {limit}"
        )
    for s in suggestions:
        if not isinstance(s, dict):
            return f"{where} suggestion must be a dict"
        for body in s.values():
            if not isinstance(body, dict):
                continue
            text = body.get("Text") or ""
            if len(text) > rcs_limit("suggestionTextChars"):
                return _too_long(
                    f"{where} suggestion label {text!r}", len(text), "suggestionTextChars"
                )
            postback = body.get("PostbackData") or ""
            if len(postback) > rcs_limit("postbackDataChars"):
                return _too_long(
                    f"{where} suggestion postback data", len(postback), "postbackDataChars"
                )
    return None


def send_rcs(
    phone: str,
    rcs_content: dict,
    time_to_live: int | None = None,
    fallback_body: str | None = None,
) -> dict:
    """Send an RCS message. ConfigurationSetName routes delivery/read events to
    the demo's SNS topic. TimeToLive (seconds) sets an expiration window.

    `fallback_body` opts this message into per-message SMS fallback: if RCS
    fails outright or the TimeToLive expires, End User Messaging sends that
    plain-text body as an SMS instead. It is a separately written string, not a
    stringified card — the fallback body caps well below the RCS body limit (see
    `fallbackBodyChars` in content/rcs-features.json), so it is truncated to
    that limit here rather than being rejected at the API. The parameter is
    ignored unless the stack was deployed with an SMS origination identity,
    because a FallbackConfiguration without one is a ValidationException.

    Two independent signals feed the Recipients tab, and both are needed. The
    synchronous one is whether SendRcsMessage itself was accepted or rejected,
    logged here as SEND_ACCEPTED / SEND_FAILED — available immediately, and the
    only signal that exists when the API call is what failed. The asynchronous
    ones (RCS_DELIVERED / RCS_READ / RCS_FAILED) arrive minutes later on the
    configuration set's SNS event destination and describe what the platform and
    handset did. See log_send_event and _conversation_metrics in
    dashboard_handler.py.
    """
    if not RCS_AGENT_ID:
        print("ERROR: RCS_AGENT_ID not configured")
        return {"error": "agent not configured"}

    normalized = normalize_phone(phone)
    if not normalized:
        print(f"RCS SEND SKIPPED: invalid destination phone number ({_mask_phone(phone)})")
        return {"error": "invalid destination phone number"}
    phone = normalized
    ph = hash_phone(phone)

    invalid = validate_rcs_content(rcs_content)
    if invalid:
        print(f"RCS SEND SKIPPED: {invalid}")
        log_send_event(ph, "SEND_FAILED", error=invalid)
        return {"error": invalid}

    kwargs = {
        "DestinationPhoneNumber": phone,
        "OriginationIdentity": RCS_AGENT_ID,
        "RcsMessageContent": rcs_content,
    }
    if CONFIG_SET_NAME:
        kwargs["ConfigurationSetName"] = CONFIG_SET_NAME
    if time_to_live:
        kwargs["TimeToLive"] = int(time_to_live)
    if fallback_body and SMS_FALLBACK_NUMBER:
        kwargs["FallbackConfiguration"] = {
            "Channel": "SMS",
            "MessageBody": fallback_body[: rcs_limit("fallbackBodyChars")],
            "OriginationIdentity": SMS_FALLBACK_NUMBER,
        }
    elif fallback_body:
        # The flow asked for fallback and the deployment can't honour it. Say so
        # once per send rather than dropping it silently: with no SMS origination
        # identity there is no FallbackConfiguration, so RCS_FALLEN_BACK_TO_SMS
        # can never fire, and a Fell back to SMS column stuck at zero would
        # otherwise read as "RCS never failed" instead of "fallback was never
        # configured". A demo deployment often has no SMS-capable origination
        # identity, so this is the expected state, not an error — hence a
        # plain log line and no note_send_error.
        print(
            "RCS FALLBACK SKIPPED: this message requested an SMS fallback but no "
            "SMS origination identity is configured — redeploy with "
            "-c smsFallbackNumber=+1… to activate it. Sending RCS-only."
        )

    try:
        resp = sms_voice.send_rcs_message(**kwargs)
        print(f"RCS SEND OK: MessageId={resp.get('MessageId', '?')}")
        log_send_event(ph, "SEND_ACCEPTED", message_id=resp.get("MessageId", ""))
        clear_quota_alert()
        return resp
    except Exception as e:  # noqa: BLE001
        # Never log or persist the raw exception string: an AWS SDK error for a
        # send carries the request parameters, so str(e) can contain the
        # destination phone number (PII). _sanitize_send_error keeps the AWS
        # error code (e.g. ValidationException, ServiceQuotaExceededException) —
        # which is what note_send_error and the dashboard need — and drops the
        # message body that could echo the number back.
        safe = _sanitize_send_error(e)
        print(f"RCS SEND FAILED: {safe}")
        log_send_event(ph, "SEND_FAILED", error=safe)
        note_send_error(safe)
        return {"error": safe}


def resolve_media(url: str) -> str:
    if url.startswith("s3://") or url.startswith("http"):
        return url
    return f"s3://{S3_BUCKET}/{url.lstrip('/')}"


def webview_url(page: str, **params) -> str:
    """Build a webview link. Extra kwargs become query params — used to pass
    phone_hash (`ph`) to webviews that need to associate an upload/action
    with a conversation, e.g. lambda/webviews/upload-insurance-card.html."""
    base = f"{API_BASE_URL}/webview/{page}" if API_BASE_URL else f"/webview/{page}"
    query = {k: v for k, v in params.items() if v}
    return f"{base}?{urllib.parse.urlencode(query)}" if query else base


# ── Suggestion builder ──────────────────────────────────────────────────────
# Accepts a simple dict format and returns RCS suggestion objects. Used by the AI
# responses (model JSON) and the welcome message's navigation row; every other
# flow writes its chips as literal dicts.
#
# A chip that runs a native action on the handset (dial, map, calendar, webview,
# browser, share location) is reported back as a suggestion tap, and the phone
# has already done the work by then. For the chips a flow writes, the adapter
# keeps a list of their ids (channel_adapter.ACTION_ONLY_POSTBACKS). The model
# supplies its own id for each chip, so a fixed list cannot cover them: "call",
# "call_911" and "directions_main_clinic" all reached the assistant, and the
# reply to "call" announced "Connecting you to Member Services now" to a member
# who had just placed the call themselves. So the builder, not the model, chooses
# the id of every action chip it builds, from the table below, and the adapter
# stays silent for the table's values. A new action kind needs an entry here;
# scripts/check-rcs-registry.py builds every kind with a hostile id and fails if
# the chip does not come out with its reserved one.
AI_ACTION_POSTBACKS = {
    "open_url": "ai_open_url",
    "dial": "ai_dial",
    "calendar": "ai_calendar",
    "view_location": "ai_view_location",
    "share_location": "ai_share_location",
}


def build_suggestions(suggestions: list, max_count: int | None = None) -> list:
    """max_count defaults to the documented per-card limit, which is the tighter
    of the two (a card allows 4, a message allows 11). Pass
    rcs_limit("suggestionsPerMessage") explicitly for message-level chips.

    Native-action chips ignore any `postback` in the input and carry the reserved
    id from AI_ACTION_POSTBACKS. A `reply` chip keeps the id it was given, except
    that it cannot claim a reserved one: that tap would be silenced as an action
    the handset already ran, and the member would see a button that does nothing."""
    if max_count is None:
        max_count = rcs_limit("suggestionsPerCard")
    label_max = rcs_limit("suggestionTextChars")
    result = []
    for s in (suggestions or [])[:max_count]:
        kind = s.get("type", "reply")
        text = (s.get("text", "") or "")[:label_max]
        # `kind` comes from model JSON, so it may not even be hashable.
        reserved = AI_ACTION_POSTBACKS.get(kind) if isinstance(kind, str) else None
        postback = reserved or s.get("postback", s.get("text", ""))
        if kind == "reply":
            if postback in AI_ACTION_POSTBACKS.values():
                postback = s.get("text", "")
            result.append({"Reply": {"Text": text, "PostbackData": postback}})
        elif kind == "open_url":
            ou = {"Text": text, "PostbackData": postback, "Url": s["url"]}
            if s.get("webview"):
                ou["Application"] = "WEBVIEW"
                ou["WebviewViewMode"] = s.get("webview_mode", "TALL")
            result.append({"OpenUrl": ou})
        elif kind == "dial":
            result.append(
                {"DialPhone": {"Text": text, "PostbackData": postback, "PhoneNumber": s["phone_number"]}}
            )
        elif kind == "calendar":
            result.append(
                {"CreateCalendarEvent": {
                    "Text": text, "PostbackData": postback,
                    "StartTime": s.get("start_time", ""), "EndTime": s.get("end_time", ""),
                    "Title": s.get("title", ""), "Description": s.get("description", ""),
                }}
            )
        elif kind == "view_location":
            result.append(
                {"ShowLocation": {
                    "Text": text, "PostbackData": postback,
                    "Latitude": s.get("latitude", 0), "Longitude": s.get("longitude", 0),
                    "Label": s.get("label", ""),
                }}
            )
        elif kind == "share_location":
            result.append({"RequestLocation": {"Text": text, "PostbackData": postback}})
    return result


# ── Utilities ───────────────────────────────────────────────────────────────
def hash_phone(phone: str) -> str:
    phone = (phone or "").strip()
    if phone and not phone.startswith("+"):
        phone = "+" + phone
    return "anon-" + hashlib.sha256(phone.encode()).hexdigest()[:24]


def strip_markdown(text: str) -> str:
    """Flatten markdown to plain text for RCS.

    RCS messages are plain text — the Messages app renders no markdown, so
    model-generated syntax like **bold**, *italic*, `code`, [links](url), and
    markdown bullets/headings show up literally on the handset. The prompt asks
    for plain text, and this also runs on every AI-generated body before it is
    sent, so any markdown in the output is flattened.

    Deliberately conservative: it removes emphasis/heading/link/code markers and
    normalizes list bullets to a bare "- ", but leaves ordinary punctuation
    (including lone asterisks that are not emphasis) alone.
    """
    if not text:
        return text
    out = text
    # Links/images: [label](url) -> label ; ![alt](url) -> alt
    out = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", out)
    # Bold/italic: **x**, __x__, *x*, _x_ -> x (bold before italic).
    out = re.sub(r"\*\*(.+?)\*\*", r"\1", out)
    out = re.sub(r"__(.+?)__", r"\1", out)
    out = re.sub(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"\1", out)
    out = re.sub(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)", r"\1", out)
    # Inline code / code fences.
    out = re.sub(r"```[a-zA-Z0-9]*\n?", "", out)
    out = re.sub(r"`([^`]*)`", r"\1", out)
    # ATX headings at line start: "## Title" -> "Title".
    out = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", out)
    # Blockquote markers at line start.
    out = re.sub(r"(?m)^\s{0,3}>\s?", "", out)
    # Markdown bullet markers (*, +) at line start -> "- ". "•" and "-" are
    # already plain-text bullets, so leave those as the member typed/expects.
    out = re.sub(r"(?m)^(\s*)[*+]\s+", r"\1- ", out)
    return out


def error_code(exc: BaseException) -> str:
    """The AWS error code of an exception, or its class name. Log this, never
    str(exc): an SDK error can echo the request, and the request carries member
    content (the phone number, the message text, a photo's description).

    Use it wherever a caught exception is printed and the failing call took
    member content as a parameter. Where the call carried none (a DynamoDB key
    built from a hash, an S3 key), the full message is the more useful log line."""
    response = getattr(exc, "response", None)
    err = response.get("Error") if isinstance(response, dict) else None
    return str((err.get("Code") if isinstance(err, dict) else None) or type(exc).__name__)


def _sanitize_send_error(exc: Exception) -> str:
    """Turn a SendRcsMessage exception into a log/store-safe string.

    An AWS SDK (botocore ClientError) exception echoes the request parameters in
    its message, so the raw str() can contain the destination phone number
    (PII). We keep only the structured, non-sensitive fields: the AWS error code
    and, when present, the quota reason — which is what note_send_error keys on
    (see _QUOTA_REASONS) and what the dashboard surfaces. The free-text message
    body, which is where a phone number would appear, is never included.
    """
    code = error_code(exc)
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        err = response.get("Error") if isinstance(response.get("Error"), dict) else {}
        # ServiceQuotaExceededException surfaces the specific limit in a Reason
        # field (e.g. MONTHLY_SPEND_LIMIT_REACHED_FOR_RCS); it's an enum, not PII.
        reason = response.get("reason") or response.get("Reason") or err.get("Reason")
        if reason:
            return f"{code} ({reason})"
    return code


def _mask_phone(value: str) -> str:
    """Mask a phone-shaped value for logging (PII). Non-phone values (agent ids,
    empty strings) pass through unchanged since they aren't sensitive."""
    if not value or value.startswith("rcs-") or value.endswith("_agent"):
        return value
    return value[:3] + "…" + value[-2:] if len(value) > 5 else "…"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ttl(days: int = 0, minutes: int = 0) -> int:
    return int(time.time()) + days * 86400 + minutes * 60


def unexpired(item):
    """Return `item`, or None when it is absent or its `ttl` has passed.

    DynamoDB TTL is garbage collection, not an expiry guarantee: an expired item
    is typically deleted within a few days and keeps coming back from reads until
    then. Any read that treats a TTL-backed row as currently valid (a one-time
    code, the active flow, a visit token) goes through this, so "expires in five
    minutes" holds whether or not the background deletion has run.

    An item is expired once `ttl <= now`, the same boundary the DynamoDB docs use
    when filtering expired items. An item with no `ttl` has no expiry and is
    returned unchanged (the handover STATE row, tester profiles), as is one whose
    `ttl` is not a number, which DynamoDB's own TTL process also ignores.
    """
    if not item:
        return None
    ttl = item.get("ttl")
    if isinstance(ttl, numbers.Number) and ttl <= time.time():
        return None
    return item


# ── DynamoDB: conversations ─────────────────────────────────────────────────
def log_message(phone_hash: str, direction: str, body: str, rcs_content=None, actor: str = ""):
    now = _now_iso()
    item = {
        "pk": f"CONV#{phone_hash}",
        "sk": f"MSG#{now}#{uuid.uuid4().hex[:8]}",
        "direction": direction,
        "body": (body or "")[:2000],
        "timestamp": now,
        "ttl": _ttl(days=TTL_CONVERSATION_DAYS),
    }
    if actor:
        item["actor"] = actor
    if rcs_content:
        item["rcs_content"] = json.dumps(rcs_content, default=str)
    table.put_item(Item=item)
    table.put_item(Item={
        "pk": f"CONV#{phone_hash}", "sk": "META",
        "last_message": now, "last_direction": direction,
    })
    if direction == "inbound":
        # The reply landed, so they have stopped typing. Without this the status
        # bar would keep claiming they're composing until the presence row goes
        # stale on its own, which reads as a stuck indicator next to the message
        # it was predicting.
        clear_typing(phone_hash)


def log_send_event(phone_hash: str, event_type: str, message_id: str = "", error: str = ""):
    """Log the synchronous outcome of a SendRcsMessage call (accepted or
    rejected by the API itself). This is distinct from log_event, which
    records the async carrier-side delivery/read events received via SNS. On a
    testing agent those events appear once the agent is launched in a country.
    See send_rcs."""
    now = _now_iso()
    item = {
        "pk": f"CONV#{phone_hash}", "sk": f"MSG#{now}#{uuid.uuid4().hex[:8]}",
        "direction": "event", "body": event_type, "timestamp": now,
        "event_type": event_type, "ttl": _ttl(days=7),
    }
    if message_id:
        item["message_id"] = message_id
    if error:
        item["error"] = error[:500]
    table.put_item(Item=item)


# ── DynamoDB: account-wide quota alert ──────────────────────────────────────
# SendRcsMessage failures for spend/quota reasons aren't per-recipient — the
# limit is account-wide (see AWS's ServiceQuotaExceededException with reason
# MONTHLY_SPEND_LIMIT_REACHED_FOR_RCS), so this is one singleton item rather
# than something logged per phone_hash. The dashboard's status bar polls
# GET /api/health (see dashboard_handler.get_health) to warn the operator
# that sends are failing for a reason that has nothing to do with the
# targeted device.
_QUOTA_REASONS = ("MONTHLY_SPEND_LIMIT_REACHED", "SERVICE_QUOTA_EXCEEDED")


def note_send_error(error: str):
    """Called from send_rcs on every failed SendRcsMessage. If the error looks
    like an account-level quota/spend-limit rejection (as opposed to e.g. an
    invalid destination or agent misconfiguration), record it so the
    dashboard can surface a warning independent of which recipient we were
    trying to reach."""
    if any(r in (error or "") for r in _QUOTA_REASONS):
        table.put_item(Item={
            "pk": "SYSTEM", "sk": "RCS_QUOTA_ALERT",
            "error": (error or "")[:500], "last_seen": _now_iso(),
        })


def clear_quota_alert():
    """Called from send_rcs on every successful SendRcsMessage — a send going
    through again is the simplest signal that the quota issue has resolved
    (limit increase applied, or the monthly spend counter reset)."""
    table.delete_item(Key={"pk": "SYSTEM", "sk": "RCS_QUOTA_ALERT"})


def get_quota_alert() -> dict:
    item = table.get_item(Key={"pk": "SYSTEM", "sk": "RCS_QUOTA_ALERT"}).get("Item")
    return dict(item) if item else {}


# What each outbound status event actually means, for the CloudWatch line and
# nothing else.
#
# The keys below are the RCS members of the service model's `EventType` enum
# (see the RCS events guide linked below):
#
#   RCS_ALL RCS_QUEUED RCS_SENT RCS_DELIVERED RCS_READ RCS_FAILED
#   RCS_TTL_EXPIRED RCS_PROTECT_BLOCKED RCS_FALLEN_BACK_TO_SMS
#
# plus this demo's own two synchronous SEND_* pseudo-events, which are not AWS
# event types at all — they record the outcome of the SendRcsMessage call.
# RCS_ALL is a subscription shorthand only and never arrives as an event.
#
# The inbound entries at the end (RCS_TYPING, CONVERSATION_STARTED, KEYWORD_* and
# OPTED_OUT_SKIPPED) are the transcript markers log_indicator writes, so its
# CloudWatch line can say what each one means.
#
# TTL expiry is the single RCS_TTL_EXPIRED event, and opt-outs surface through
# the opt-out list rather than as an event here. To list the enum from the
# installed SDK:
#   python -c "import boto3,json; m=boto3.client('pinpoint-sms-voice-v2') \
#     .meta.service_model.operation_model('CreateEventDestination').input_shape; \
#     print(m.members['MatchingEventTypes'].member.enum)"
# https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-events.html
_EVENT_EXPLANATIONS = {
    "SEND_ACCEPTED": "SendRcsMessage returned a MessageId; the platform has not confirmed delivery yet",
    "SEND_FAILED": "the SendRcsMessage call itself failed — nothing was handed to the platform",
    "RCS_QUEUED": "accepted and waiting at the platform; not yet handed to the network",
    "RCS_SENT": "handed to the RCS network; no device confirmation yet",
    "RCS_DELIVERED": "delivery lifecycle event; messageStatus carries the actual outcome",
    "RCS_READ": "the recipient's client reported the message as read",
    "RCS_FAILED": "RCS delivery failed outright",
    "RCS_TTL_EXPIRED": "TimeToLive elapsed without a delivery confirmation — the message never reached the device",
    "RCS_PROTECT_BLOCKED": "blocked by a Protect configuration before it left the account",
    "RCS_FALLEN_BACK_TO_SMS": "the RCS leg did not succeed, so the FallbackConfiguration body went out as SMS instead — the member was still reached",
    "RCS_TYPING": "the member's client reported that they are composing (inbound signal, not an outbound status)",
    "CONVERSATION_STARTED": "the member opened the conversation with the agent (inbound signal, not an outbound status)",
    "KEYWORD_STOP": "the member sent an opt-out keyword such as STOP; the service answers it and, for an OPT_OUT keyword, adds the number to the opt-out list; this stack sends no reply",
    "KEYWORD_HELP": "the member sent HELP; the service answers it, and this stack sends no reply",
    "KEYWORD_START": "the member sent an opt-in keyword such as UNSTOP; the service answers it, and a keyword whose action is OPT_IN also removes the number from the opt-out list; this stack sends no reply",
    "KEYWORD_CUSTOM": "the member sent a keyword registered on the agent; the service answers it with the keyword's message, and this stack sends no reply",
    "OPTED_OUT_SKIPPED": "the sender is on the service's opt-out list, so this stack skipped its reply; the service refuses every send to that number",
}


def log_event(message: dict):
    dest = message.get("destinationPhoneNumber", "")
    orig = message.get("originationNumber", "")
    event_type = message.get("eventType", "UNKNOWN")
    phone = ""
    for cand in (dest, orig):
        if cand and not cand.startswith("rcs-") and not cand.endswith("_agent"):
            phone = cand
            break
    if not phone:
        # Never log raw phone numbers (PII) — mask whichever candidates exist.
        print(f"EVENT SKIP: no phone dest={_mask_phone(dest)} orig={_mask_phone(orig)}")
        return
    ph = hash_phone(phone)
    now = _now_iso()
    # Legible in CloudWatch as well as in the transcript. Display only — the
    # stored event_type is always AWS's own string, and an unrecognized type is
    # still stored and still shown, so any event type appears in the transcript
    # without a code change.
    print(
        f"RCS EVENT {event_type}"
        f"{' status=' + message['messageStatus'] if message.get('messageStatus') else ''}: "
        f"{_EVENT_EXPLANATIONS.get(event_type, 'see the RCS events documentation for this type')}"
    )
    # messageStatus is the part that actually says what happened: a single
    # RCS_DELIVERED event carries DELIVERED, PENDING, UNDELIVERABLE or REJECTED,
    # so counting the event type alone would report an undeliverable message as
    # delivered. RCS_READ carries READ. Stored alongside the type so
    # _conversation_metrics can distinguish them.
    table.put_item(Item={
        "pk": f"CONV#{ph}", "sk": f"MSG#{now}#{uuid.uuid4().hex[:8]}",
        "direction": "event", "body": event_type, "timestamp": now,
        "event_type": event_type, "message_id": message.get("messageId", ""),
        "message_status": message.get("messageStatus", ""),
        "ttl": _ttl(days=7),
    })


def log_indicator(phone_hash: str, indicator: str):
    """Record an ephemeral *inbound* interaction signal — RCS_TYPING (the member
    is composing) or CONVERSATION_STARTED (they opened the chat) — or one of the
    channel adapter's own markers for a message it deliberately left unanswered
    (KEYWORD_* when the service answered it, OPTED_OUT_SKIPPED when the sender is
    on the opt-out list).

    These arrive on the two-way topic as a stringified JSON messageBody with no
    top-level eventType, so they are not outbound status events, but they are
    stored in the same `direction: "event"` shape for two deliberate reasons:
    the dashboard already renders those rows as small centered transcript lines
    behind its include_events toggle, and _conversation_metrics counts event
    rows by name, so an unnamed type falls through every branch and inflates no
    column. A typing signal is not a message and must not be counted as one.

    Written with log_message would be wrong: that also updates the CONV META
    row, so a typing signal would overwrite last_message/last_direction and the
    Conversations list would report "indicator" as the thread's last activity.

    A typing signal also refreshes a separate presence row (note_typing below),
    which is what the dashboard's status bar reads — the transcript row is the
    history, the presence row is "right now".

    TTL is short. These are high-frequency by nature (a client may re-send
    IS_TYPING throughout one reply) and carry no value once the reply lands.
    No typing signal was received during this sample's testing on a testing
    agent. The handler records them whenever they arrive, with no code change.
    """
    now = _now_iso()
    print(f"RCS INDICATOR {indicator}: "
          f"{_EVENT_EXPLANATIONS.get(indicator, 'unrecognized inbound signal')}")
    table.put_item(Item={
        "pk": f"CONV#{phone_hash}", "sk": f"MSG#{now}#{uuid.uuid4().hex[:8]}",
        "direction": "event", "body": indicator, "timestamp": now,
        "event_type": indicator, "message_id": "", "message_status": "",
        "ttl": _ttl(days=1),
    })
    if indicator == "RCS_TYPING":
        note_typing(phone_hash)


# ── DynamoDB: live typing presence ──────────────────────────────────────────
# Deliberately separate from the transcript row above. The transcript is history
# ("they were typing at 14:02"); this is presence ("they are typing *now*"), and
# the status bar needs to answer that for every recipient at once. A single
# fixed-partition query does it — scanning every CONV# partition for a recent
# indicator row would cost a table scan on every poll.
TYPING_STALE_SECONDS = 12


def note_typing(phone_hash: str):
    """Mark a recipient as currently composing. One row per recipient, so a
    client that re-sends IS_TYPING throughout a long reply just refreshes it."""
    table.put_item(Item={
        "pk": "SYSTEM", "sk": f"TYPING#{phone_hash}",
        "phone_hash": phone_hash, "at": int(time.time()),
        # Belt to the freshness filter's braces: DynamoDB deletes TTL items
        # within ~48 hours, not on the second, so readers must still check `at`.
        # This only keeps the partition from growing without bound.
        "ttl": _ttl(minutes=5),
    })


def clear_typing(phone_hash: str):
    table.delete_item(Key={"pk": "SYSTEM", "sk": f"TYPING#{phone_hash}"})


def typing_now() -> list:
    """Recipients whose last typing signal is recent enough to still mean
    "typing", newest first. Hashes only — resolving them to names is the
    dashboard's job, which already holds the tester list."""
    resp = table.query(
        KeyConditionExpression=Key("pk").eq("SYSTEM") & Key("sk").begins_with("TYPING#"),
    )
    cutoff = int(time.time()) - TYPING_STALE_SECONDS
    fresh = [
        {"phone_hash": i.get("phone_hash", ""), "at": int(i.get("at", 0))}
        for i in resp.get("Items", [])
        if int(i.get("at", 0)) >= cutoff
    ]
    fresh.sort(key=lambda r: r["at"], reverse=True)
    return fresh


def conversation_history(phone_hash: str, limit: int = 10) -> list:
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(f"CONV#{phone_hash}") & Key("sk").begins_with("MSG#"),
        ScanIndexForward=False,
        Limit=limit,
    )
    items = resp.get("Items", [])
    items.reverse()
    return items


# ── DynamoDB: active flow ───────────────────────────────────────────────────
def set_active_flow(phone_hash: str, vignette: str):
    table.put_item(Item={
        "pk": f"FLOW#{phone_hash}", "sk": "ACTIVE",
        "vignette": vignette, "ttl": _ttl(minutes=TTL_FLOW_MINUTES),
    })


def get_active_flow(phone_hash: str):
    item = unexpired(table.get_item(Key={"pk": f"FLOW#{phone_hash}", "sk": "ACTIVE"}).get("Item"))
    return item.get("vignette") if item else None


def clear_active_flow(phone_hash: str):
    table.delete_item(Key={"pk": f"FLOW#{phone_hash}", "sk": "ACTIVE"})


# ── DynamoDB: handover mode (bot | live) ────────────────────────────────────
def get_mode(phone_hash: str) -> str:
    item = table.get_item(Key={"pk": f"CONV#{phone_hash}", "sk": "STATE"}).get("Item")
    return (item or {}).get("mode", "bot")


def set_mode(phone_hash: str, mode: str, agent: str = ""):
    table.put_item(Item={
        "pk": f"CONV#{phone_hash}", "sk": "STATE",
        "mode": mode, "agent": agent, "updated": _now_iso(),
    })


# ── DynamoDB: shopping cart ─────────────────────────────────────────────────
def get_cart(phone_hash: str) -> dict:
    item = unexpired(table.get_item(Key={"pk": f"CART#{phone_hash}", "sk": "ITEMS"}).get("Item"))
    return (item or {}).get("items", {}) or {}


def cart_add(phone_hash: str, product_id: str, qty: int = 1) -> dict:
    items = get_cart(phone_hash)
    items[product_id] = int(items.get(product_id, 0)) + qty
    _put_cart(phone_hash, items)
    return items


def cart_remove(phone_hash: str, product_id: str) -> dict:
    items = get_cart(phone_hash)
    items.pop(product_id, None)
    _put_cart(phone_hash, items)
    return items


def clear_cart(phone_hash: str):
    table.delete_item(Key={"pk": f"CART#{phone_hash}", "sk": "ITEMS"})


def _put_cart(phone_hash: str, items: dict):
    table.put_item(Item={
        "pk": f"CART#{phone_hash}", "sk": "ITEMS",
        "items": items, "ttl": _ttl(days=7),
    })


# ── DynamoDB: shift status (clock in/out) ───────────────────────────────────
def get_shift_status(phone_hash: str) -> dict:
    """Returns {} when not clocked in, else {"clocked_in_at": iso, "notes": str}."""
    item = unexpired(table.get_item(Key={"pk": f"SHIFT#{phone_hash}", "sk": "STATUS"}).get("Item"))
    return dict(item) if item else {}


def clock_in(phone_hash: str, notes: str = "") -> dict:
    status = {
        "pk": f"SHIFT#{phone_hash}", "sk": "STATUS",
        "clocked_in_at": _now_iso(), "notes": (notes or "")[:500],
        "ttl": _ttl(days=1),
    }
    table.put_item(Item=status)
    return status


def clock_out(phone_hash: str):
    table.delete_item(Key={"pk": f"SHIFT#{phone_hash}", "sk": "STATUS"})


# ── DynamoDB: PTO (paid time off) requests ──────────────────────────────────
def get_pending_pto(phone_hash: str) -> dict:
    item = unexpired(table.get_item(Key={"pk": f"PTO#{phone_hash}", "sk": "PENDING"}).get("Item"))
    return dict(item) if item else {}


def set_pending_pto(phone_hash: str, start_label: str, end_label: str, days: int):
    table.put_item(Item={
        "pk": f"PTO#{phone_hash}", "sk": "PENDING",
        "start_label": start_label, "end_label": end_label, "days": days,
        "requested_at": _now_iso(), "ttl": _ttl(days=1),
    })


def clear_pending_pto(phone_hash: str):
    table.delete_item(Key={"pk": f"PTO#{phone_hash}", "sk": "PENDING"})


# ── DynamoDB: shift-swap requests ───────────────────────────────────────────
def get_pending_swap(phone_hash: str) -> dict:
    item = unexpired(table.get_item(Key={"pk": f"SWAP#{phone_hash}", "sk": "PENDING"}).get("Item"))
    return dict(item) if item else {}


def set_pending_swap(phone_hash: str, my_shift_id: str, coworker_id: str):
    table.put_item(Item={
        "pk": f"SWAP#{phone_hash}", "sk": "PENDING",
        "my_shift_id": my_shift_id, "coworker_id": coworker_id,
        "requested_at": _now_iso(), "ttl": _ttl(days=1),
    })


def clear_pending_swap(phone_hash: str):
    table.delete_item(Key={"pk": f"SWAP#{phone_hash}", "sk": "PENDING"})


# ── DynamoDB: inbound media (member -> agent photos/files) ─────────────────
# Native RCS media, uploaded by AWS End User Messaging directly into
# S3_BUCKET under S3_INBOUND_MEDIA_PREFIX once TwoWayMediaS3BucketName/
# TwoWayMediaS3Role are configured on the agent (see cdk/lib/anyhealth-
# stack.ts and lambda/custom_resources/eum_wiring.py). This is distinct from
# the webview-upload path (lambda/media_convert.py + UPLOAD# items), which
# never touches this prefix — see that module's docstring for why.
def _native_media_reference_id(source_key: str) -> str:
    """A safe, fixed-size DDB partition-key suffix for an EUM-uploaded S3
    source key. The opaque key itself can contain URL-sensitive characters
    (notably '#'), so don't use it directly as a DynamoDB key."""
    return hashlib.sha256(source_key.encode("utf-8")).hexdigest()


# Formats a browser can decode in a plain <img> — notably not HEIC/HEIF, the
# format iPhones default to. media_convert normalizes the wider set below into
# JPEG, so anything in CONVERTIBLE_IMAGE_MIME_TYPES eventually becomes
# renderable; until then the raw key must not be handed to a browser.
BROWSER_IMAGE_MIME_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/gif"}
CONVERTIBLE_IMAGE_MIME_TYPES = BROWSER_IMAGE_MIME_TYPES | {"image/heic", "image/heif"}


def media_browser_renderable(media: dict) -> bool:
    """Whether the best key currently on this media record (converted if it
    exists, else the raw source) is something an <img> can display."""
    mime = (media.get("convertedMimeType") or media.get("mimeType") or "").lower()
    return mime in BROWSER_IMAGE_MIME_TYPES


def media_conversion_pending(media: dict) -> bool:
    """Whether media_convert still owes this record a converted JPEG and a
    classification. Conversion is asynchronous — the inbound SNS notification
    logs the message first and record_native_media_conversion updates it a
    second or two later — so dashboard surfaces need to tell "still working"
    apart from "this format is never going to render", and keying on
    convertedS3Key means a photo whose classification came back empty settles
    rather than looking permanently in-progress."""
    return not media.get("convertedS3Key") and (media.get("mimeType") or "").lower() in CONVERTIBLE_IMAGE_MIME_TYPES


def log_inbound_media(phone_hash: str, media: dict, phone: str = ""):
    """Record a received-media event and, for successful native RCS files,
    persist a lookup from its raw S3 key to the conversation message.

    That reference joins two asynchronous events: EUM's SNS inbound-message
    notification (this call) and S3's ObjectCreated event (media_convert).
    It lets the converter replace a raw HEIC/JPEG/PNG with its normalized JPEG
    and classification in the exact chat message the dashboard is polling."""
    now = _now_iso()
    ok = media.get("mediaStatus") == "SUCCESS"
    message_sk = f"MSG#{now}#{uuid.uuid4().hex[:8]}"
    label = f"[Photo: {media.get('fileName', 'file')}]" if ok else f"[Media failed: {media.get('mediaStatus', 'UNKNOWN')}]"
    table.put_item(Item={
        "pk": f"CONV#{phone_hash}", "sk": message_sk,
        "direction": "inbound", "body": label, "timestamp": now,
        "media_content": json.dumps(media, default=str),
        "ttl": _ttl(days=TTL_CONVERSATION_DAYS),
    })
    table.put_item(Item={
        "pk": f"CONV#{phone_hash}", "sk": "META",
        "last_message": now, "last_direction": "inbound",
    })

    source_key = media.get("s3Key", "")
    if ok and source_key:
        # EUM's S3 event can arrive before its SNS notification. The converter
        # retries if it cannot find this row yet; once present, the row tells it
        # precisely which conversation message and phone it should update.
        table.put_item(Item={
            "pk": f"NATIVE_MEDIA#{_native_media_reference_id(source_key)}", "sk": "SOURCE",
            "source_key": source_key, "phone_hash": phone_hash, "phone": phone,
            "message_sk": message_sk, "ttl": _ttl(days=TTL_CONVERSATION_DAYS),
        })


def get_native_media_reference(source_key: str) -> dict:
    item = table.get_item(Key={
        "pk": f"NATIVE_MEDIA#{_native_media_reference_id(source_key)}", "sk": "SOURCE",
    }).get("Item")
    return dict(item) if item else {}


def record_native_media_conversion(source_key: str, converted_key: str, classification: str) -> dict:
    """Attach a converted JPEG + its Bedrock description to the original
    native RCS message and latest-media pointer. Returns callback data for the
    channel adapter once, or {} for an already-processed/unknown object."""
    ref = get_native_media_reference(source_key)
    if not ref or ref.get("converted_key"):
        return {}

    phone_hash = ref["phone_hash"]
    message = table.get_item(Key={"pk": f"CONV#{phone_hash}", "sk": ref["message_sk"]}).get("Item")
    if not message:
        return {}
    try:
        media = json.loads(message.get("media_content", "{}"))
    except (json.JSONDecodeError, TypeError):
        return {}

    media["convertedS3Key"] = converted_key
    media["convertedMimeType"] = "image/jpeg"
    if classification:
        # The 2-way conversation fetches media_content from this exact row,
        # so keep the Bedrock result beside the preview key rather than only
        # on the separate latest-media pointer used by the Demo cards.
        media["classification"] = classification[:500]
    table.update_item(
        Key={"pk": f"CONV#{phone_hash}", "sk": ref["message_sk"]},
        UpdateExpression="SET media_content = :m",
        ExpressionAttributeValues={":m": json.dumps(media, default=str)},
    )
    table.update_item(
        Key={"pk": ref["pk"], "sk": "SOURCE"},
        UpdateExpression="SET converted_key = :c, classification = :cl",
        ExpressionAttributeValues={":c": converted_key, ":cl": classification[:500]},
    )

    latest = get_latest_media(phone_hash)
    if latest.get("media", {}).get("s3Key") == source_key:
        set_latest_media(phone_hash, media, classification)

    return {
        "phone": ref.get("phone", ""), "phone_hash": phone_hash,
        "media": media, "classification": classification,
    }


def set_latest_media(phone_hash: str, media: dict, classification: str = ""):
    """Upsert a single 'latest native photo' pointer per conversation, so the
    Demo tab can show the most recent inbound photo + its GenAI description
    without scanning the whole message log. Called twice per photo: once on
    receipt (classification unknown yet), and again from handle_media once
    classification finishes (bot mode only) — a plain overwrite, since there's
    only ever one row per phone_hash."""
    table.put_item(Item={
        "pk": f"CONV#{phone_hash}", "sk": "LATEST_MEDIA",
        "media": json.dumps(media, default=str), "classification": classification,
        "updated": _now_iso(),
    })


def get_latest_media(phone_hash: str) -> dict:
    item = table.get_item(Key={"pk": f"CONV#{phone_hash}", "sk": "LATEST_MEDIA"}).get("Item")
    if not item:
        return {}
    try:
        media = json.loads(item.get("media", "{}"))
    except (json.JSONDecodeError, TypeError):
        media = {}
    return {"media": media, "classification": item.get("classification", ""), "updated": item.get("updated", "")}


def inbound_media_url(s3_key: str) -> str:
    """s3:// URI for an object AWS End User Messaging uploaded under
    S3_INBOUND_MEDIA_PREFIX. Passed to send_rcs (e.g. as a FileMessage/
    RichCard Media.FileUrl) to echo the photo back in a confirmation card —
    resolve_media() is for outbound content/*.md-referenced assets and
    doesn't apply here since inbound keys already include the full path."""
    return f"s3://{S3_BUCKET}/{s3_key.lstrip('/')}"


# ── DynamoDB: webview uploads (secure document upload, see insurance_upload) ─
# Distinct from inbound RCS media above: the file bytes here never touch the
# RCS/carrier network at all. The webview PUTs directly to S3 via a
# presigned URL (see dashboard_handler.create_upload_url), a
# media_convert.py Lambda (S3-event-triggered) normalizes the result to a
# displayable JPEG, and this state tracks that pipeline's progress so the
# webview can poll for completion.
UPLOAD_RAW_PREFIX = "raw-uploads"
UPLOAD_CONVERTED_PREFIX = "converted-uploads"


def new_upload(phone_hash: str, content_type: str) -> dict:
    upload_id = uuid.uuid4().hex
    ext = {"image/heic": "heic", "image/heif": "heic", "image/jpeg": "jpg",
           "image/jpg": "jpg", "image/png": "png"}.get(content_type, "bin")
    raw_key = f"{UPLOAD_RAW_PREFIX}/{phone_hash}/{upload_id}.{ext}"
    item = {
        "pk": f"UPLOAD#{phone_hash}", "sk": upload_id,
        "upload_id": upload_id, "raw_key": raw_key, "content_type": content_type,
        "status": "PENDING", "created_at": _now_iso(), "ttl": _ttl(days=1),
    }
    table.put_item(Item=item)
    return item


def get_upload(phone_hash: str, upload_id: str) -> dict:
    item = unexpired(table.get_item(Key={"pk": f"UPLOAD#{phone_hash}", "sk": upload_id}).get("Item"))
    return dict(item) if item else {}


def get_latest_upload(phone_hash: str) -> dict:
    """Most recent webview upload for this conversation, READY (converted +
    classified) preferred over any other status — used by the Demo tab to
    show the latest secure-upload photo + its GenAI description. sk here is
    upload_id (not time-ordered), so this queries the whole small per-phone
    partition and sorts client-side rather than relying on key order."""
    resp = table.query(KeyConditionExpression=Key("pk").eq(f"UPLOAD#{phone_hash}"))
    items = [i for i in resp.get("Items", []) if unexpired(i)]
    if not items:
        return {}
    ready = [i for i in items if i.get("status") == "READY"]
    pool = ready or items
    return dict(max(pool, key=lambda i: i.get("created_at", "")))


def set_upload_status(phone_hash: str, upload_id: str, status: str, converted_key: str = "", error: str = "", classification: str = ""):
    """status: PENDING (presigned, not yet uploaded) -> PROCESSING (S3 object
    landed, media_convert.py running) -> READY (converted JPEG available) or
    FAILED (conversion error, e.g. unsupported format)."""
    expr_names = {"#s": "status"}
    expr_values = {":s": status}
    sets = ["#s = :s"]
    if converted_key:
        sets.append("converted_key = :c")
        expr_values[":c"] = converted_key
    if error:
        sets.append("#e = :e")
        expr_names["#e"] = "error"
        expr_values[":e"] = error[:500]
    if classification:
        sets.append("classification = :cl")
        expr_values[":cl"] = classification[:500]
    table.update_item(
        Key={"pk": f"UPLOAD#{phone_hash}", "sk": upload_id},
        UpdateExpression="SET " + ", ".join(sets),
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
    )
