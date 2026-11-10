"""Site Evidence — photo or video proof from the field, deterministic (AnyBuild).

A superintendent, trade or driver documents something with a photo or a short
video sent straight into the RCS thread: an inspection record, proof that work
is ready for the next trade, or a delivery that arrived damaged. The person
first says what they are documenting (so the evidence lands in the right place),
then sends the media. A damaged-delivery report is routed to the supplier.

The media takes the native inbound path, the same as AnyHealth's Classify a
Photo: AWS End User Messaging drops the file in S3 and tells the two-way topic.
Images are normalized to JPEG and described by Bedrock in general terms
(media_convert.py), then channel_adapter.handle_native_media_ready calls
media_messages() below. Video is accepted by the service (video/mp4, webm and
others) but this stack's converter only handles images, so a video is logged and
receipted without a preview or a description. channel_adapter.handle_media calls
media_messages() for that case.

Each item is also added to the "evidence_log" state: the latest ticket, its
evidence type and every item logged on it (the preview key for an image, the
description, the file name, the time). Unlike the open-ticket state, it is kept
when the sender taps Done, so the dashboard's Site Evidence card can show the
latest ticket's photos (dashboard_handler.get_latest_media_for_demo). Reset
clears it.

Why the native path is acceptable here: a photo of framing or a cracked pallet is
not personal data. The prompt still tells the sender to keep people and anything
personal out of the shot, because these bytes cross the carrier network. For an
identity document use Identity Capture instead, which uses a webview upload.

Triggers: `Start: Site_Evidence`, or the `home_evidence` postback.
Postback prefix: ev_
"""

import random
from datetime import datetime, timezone

import common as c

_KIND = "evidence"
_KIND_PREFIX = "ev_kind_"
# The dashboard's record of the latest ticket's items (see the module docstring).
_LOG = "evidence_log"
_LOG_MAX_ITEMS = 10


def on_start(phone, phone_hash):
    return _prompt()


def on_trigger(phone, phone_hash, vignette):
    return _prompt()


def preview_message():
    return _prompt()


def _fill(text, site) -> str:
    return (text or "").replace("{supplier}", c.supplier().get("name", "the supplier")) \
                       .replace("{lot}", site.get("lot", "the lot"))


def _prompt():
    site = c.site()
    kinds = c.evidence_kinds()[:4]
    if not kinds:
        return [{"Content": {"TextMessage": {"Body": (
            "No evidence types are set up yet. Add `evidenceKinds` in content/construction.md."
        )}}}]
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "Site Evidence",
                    "Description": (
                        f"What are you documenting at {site.get('lot', 'the site')}, "
                        f"{site.get('community', '')}?\n\n"
                        "Pick one, then reply with a photo or a short video. Keep people "
                        "and anything personal out of the shot: media sent here travels "
                        "across the carrier network."
                    )[:2000],
                    "Media": {"FileUrl": c.resolve_media("media/anybuild/evidence.png"), "Height": "MEDIUM"},
                    "Suggestions": [
                        {"Reply": {"Text": k.get("chip", k.get("name", ""))[:25],
                                   "PostbackData": f"{_KIND_PREFIX}{k['id']}"}}
                        for k in kinds
                    ],
                },
            }
        },
        # SMS fallback for the entry message; inactive unless deployed with
        # -c smsFallbackNumber=+1… (see common.send_rcs). This stack does not
        # ingest inbound MMS, so the fallback routes to a person.
        "_fallback_body": (
            f"{c.brand_name()}: sending photo or video evidence needs rich messaging, "
            f"which isn't available on your device right now. Call {c.member_services_phone()} "
            "and we'll log it for you."
        ),
    }]


def _new_ticket() -> str:
    return f"EV-{random.randint(10000, 99999)}"


def _send_media_prompt(phone_hash, kind):
    c.set_build_state(phone_hash, _KIND, kind=kind["id"], ticket=_new_ticket(), count=0)
    return [{
        "Content": {"TextMessage": {"Body": (
            f"{kind.get('name', '')}: {_fill(kind.get('prompt'), c.site())}\n\n"
            "A JPEG, PNG or short MP4 works best."
        )}},
    }]


def media_messages(phone_hash, media, classification=""):
    """The reply to a photo or video that arrives while this vignette is the
    active flow: one evidence card (with a preview for an image, none for a
    video) carrying the ticket, what the media is, and what happens next.
    Called by channel_adapter in place of the generic receipt card."""
    state = c.get_build_state(phone_hash, _KIND)
    kind = c.evidence_kind_by_id(state.get("kind")) if state else None
    if not kind:
        # Media arrived before the sender said what it is. Ask, rather than file
        # it under a guess.
        return [{"Content": {"TextMessage": {"Body": (
            "Got it. Tell me what this is first so it lands in the right place."
        )}}}] + _prompt()
    state = c.set_build_state(phone_hash, _KIND, count=int(state.get("count", 0)) + 1)
    site = c.site()
    mime = str(media.get("mimeType", "")).lower()
    is_video = mime.startswith("video/")
    _log_item(phone_hash, state, kind, media, mime, classification)
    size_kb = int(media.get("fileSizeBytes", 0) or 0) // 1024
    size = f"{size_kb / 1024:.1f} MB" if size_kb >= 1024 else f"{size_kb} KB"
    name = media.get("fileName") or ("your video" if is_video else "your photo")
    lines = [
        f"{kind.get('name', '')} \u00b7 {site.get('lot', '')}, {site.get('community', '')}",
        f"Ticket {state['ticket']} \u00b7 item {state['count']}",
        f"{name} ({size})",
    ]
    if is_video:
        lines.append("Video received. A description isn't generated for video in this demo.")
    elif classification:
        lines.append(f"What we see: {classification}")
    lines.append("")
    lines.append(_fill(kind.get("outcome"), site))
    card = {
        "Title": f"Evidence Logged: {state['ticket']}",
        "Description": "\n".join(lines)[:2000],
        "Suggestions": [
            {"Reply": {"Text": "Add More", "PostbackData": "ev_more"}},
            {"Reply": {"Text": "Done", "PostbackData": "ev_done"}},
        ],
    }
    key = media.get("convertedS3Key") or (media.get("s3Key", "") if mime.startswith("image/") else "")
    if key and not is_video:
        card["Media"] = {"FileUrl": c.inbound_media_url(key), "Height": "MEDIUM"}
    return [{"Content": {"RichCard": {"CardOrientation": "VERTICAL", "CardContent": card}}}]


def _log_item(phone_hash, state, kind, media, mime, classification):
    """Add one logged item to the latest-ticket record the dashboard previews.
    A new ticket replaces the record; the newest _LOG_MAX_ITEMS items are kept.
    Only an image the browser can show gets a preview key: the converted JPEG,
    or the source file when it is already a JPEG or PNG. Strings only, so the
    record reads back without DynamoDB number types."""
    log = c.get_build_state(phone_hash, _LOG)
    items = list(log.get("items") or []) if log.get("ticket") == state["ticket"] else []
    is_image = mime.startswith("image/")
    key = media.get("convertedS3Key") or (media.get("s3Key", "") if c.media_browser_renderable(media) else "")
    items.append({
        "n": str(state["count"]),
        "type": "image" if is_image else ("video" if mime.startswith("video/") else "file"),
        "key": key if is_image else "",
        "file_name": str(media.get("fileName") or "")[:120],
        "classification": str(classification or "")[:500],
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    c.set_build_state(phone_hash, _LOG, ticket=state["ticket"], kind=kind["id"],
                      items=items[-_LOG_MAX_ITEMS:])


def on_postback(phone, phone_hash, postback_data):
    if postback_data.startswith(_KIND_PREFIX):
        kind = c.evidence_kind_by_id(postback_data[len(_KIND_PREFIX):])
        return _send_media_prompt(phone_hash, kind) if kind else _prompt()
    if postback_data == "ev_more":
        kind = c.evidence_kind_by_id(c.get_build_state(phone_hash, _KIND).get("kind"))
        if not kind:
            return _prompt()
        return [{"Content": {"TextMessage": {"Body": (
            f"Send the next photo or video for ticket "
            f"{c.get_build_state(phone_hash, _KIND).get('ticket', '')}."
        )}}}]
    if postback_data == "ev_done":
        state = c.get_build_state(phone_hash, _KIND)
        c.clear_build_state(phone_hash, _KIND)
        if not state:
            return _prompt()
        return [{"Content": {"TextMessage": {"Body": (
            f"Ticket {state.get('ticket', '')} closed with {state.get('count', 0)} item"
            f"{'' if state.get('count', 0) == 1 else 's'}. Thanks."
        )}}, "Suggestions": [{"Reply": {"Text": "Log Another", "PostbackData": "ev_again"}}]}]
    if postback_data == "ev_again":
        return _prompt()
    return None


_SEVERITIES = ("minor", "moderate", "severe")


def on_freetext(phone, phone_hash, text):
    """A typed note while a ticket is open. For a damaged delivery the model
    combines the note with the photo's description into a short claim (item,
    severity, summary) for the supplier; for other kinds it tidies the note.
    If the model is unavailable, the note is added as typed. Text with no
    open ticket, or that is not about the evidence, is left to the router."""
    state = c.get_build_state(phone_hash, _KIND)
    kind = c.evidence_kind_by_id(state.get("kind")) if state else None
    if not kind:
        return None
    ticket = state.get("ticket", "")
    items = c.get_build_state(phone_hash, _LOG).get("items") or []
    seen = next((i.get("classification") for i in reversed(items) if i.get("classification")), "")
    damaged = kind.get("id") == "damaged"
    task = (f"The user is documenting \"{kind.get('name', '')}\" on ticket {ticket}"
            + (f"; their latest photo was described as: {seen}" if seen else "")
            + ". They typed a note about it. ")
    if damaged:
        task += ('Return {"relevant": true|false, "item": "what is damaged, under 40 characters", '
                 '"severity": "minor"|"moderate"|"severe"|"", "summary": "one sentence for the '
                 'supplier combining the note and the photo description, under 160 characters"}.')
    else:
        task += 'Return {"relevant": true|false, "summary": "the note as one clear sentence, under 160 characters"}.'
    data = c.ai_extract(task, text)
    if data is not None and not data.get("relevant"):
        return None
    summary = c.extracted_text(data, "summary", 160) or (text or "").strip()[:160]
    c.set_build_state(phone_hash, _LOG, note=summary)
    chips = [
        {"Reply": {"Text": "Add More", "PostbackData": "ev_more"}},
        {"Reply": {"Text": "Done", "PostbackData": "ev_done"}},
    ]
    if not damaged:
        return [{"Content": {"TextMessage": {"Body": f"Note added to ticket {ticket}: {summary}"}},
                 "Suggestions": chips}]
    item = c.extracted_text(data, "item", 40)
    severity = (data or {}).get("severity")
    severity = severity if severity in _SEVERITIES else ""
    sup = c.supplier().get("name", "the supplier")
    lines = [f"Ticket {ticket}"]
    if item:
        lines.append(f"Item: {item}")
    if severity:
        lines.append(f"Severity: {severity}")
    lines += [f"Summary: {summary}", "", f"Sent to {sup} with the photos on this ticket."]
    return [{"Content": {"RichCard": {"CardOrientation": "VERTICAL", "CardContent": {
        "Title": f"Damage Claim Updated: {ticket}",
        "Description": "\n".join(lines)[:2000],
        "Suggestions": chips,
    }}}}]
