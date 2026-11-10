"""
AnyHealth — Channel Adapter Lambda.

Receives inbound RCS via SNS, routes to deterministic flows / the Bedrock AI
assistant / the store / verification, manages live-agent handover, and sends
replies via SendRcsMessage (common.send_rcs). Conversations are logged to
DynamoDB for the dashboard.

Typed text is screened before any of that (see _screen_freetext): emergency
language gets a fixed 911/988 reply, a message the service already answered (the
built-in STOP and HELP, a keyword registered on the agent such as UNSTOP, or one
added in the Settings tab) gets no reply from this stack, and a few global
escape words work from any flow. A sender on the service's opt-out list gets no
reply of any kind, since the service would refuse it (see "Opt-out memory").

All brand/plan/provider/store knowledge comes from content/*.md — nothing is
hardcoded here, except the emergency numbers called out in the block below.
"""

import copy
import json
import re
import time
from datetime import datetime, timedelta, timezone

import boto3
from botocore.config import Config

import common as c
from flows import get_flow, FLOW_MAP, AI_DRIVEN_VIGNETTES, welcome, otp, handover, video_visit
from flows import site_evidence
from flows import room_booking_cards
from flows import room_booking_rooms
from flows import room_booking_quote


# ── Entry point ─────────────────────────────────────────────────────────────
def lambda_handler(event, context):
    # Async callback from media_convert after an inbound native RCS photo has
    # been normalized to JPEG and classified. This is distinct from the SNS
    # event path below: it has already been safely stored in S3/DynamoDB.
    if "native_media_ready" in event:
        handle_native_media_ready(event["native_media_ready"])
        return {"statusCode": 200}

    if "push" in event:
        handle_push(event["push"])
        return {"statusCode": 200}

    for record in event.get("Records", []):
        message = json.loads(record["Sns"]["Message"])
        # Outbound status events carry a top-level eventType. Inbound member
        # traffic on the two-way topic never does — it carries originationNumber
        # / messageBody / inboundMessageId, with the interaction kind inside the
        # messageBody JSON (see parse_inbound). So presence of eventType is the
        # reliable discriminator, and an allowlist of names is not: the RCS status set
        # includes more than the four names this used to list (RCS_QUEUED,
        # RCS_SENT, RCS_TTL_EXPIRED, RCS_PROTECT_BLOCKED and
        # RCS_FALLEN_BACK_TO_SMS all arrive here too, which is why RCS_ALL
        # exists as a subscription shorthand — see common._EVENT_EXPLANATIONS
        # for the enum).
        # Anything unnamed used to fall through to process_inbound and get
        # parsed as a member message, so a delivery receipt for one member
        # could be logged as inbound chat text against another.
        # https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-events.html
        if "eventType" in message:
            c.log_event(message)
            continue

        body = (message.get("messageBody") or "").strip()
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict) and parsed.get("type") in ("RCS_TYPING", "CONVERSATION_STARTED"):
                # Not a message, so it must not reach process_inbound — it would
                # be logged as member chat text and answered by the bot. But it
                # is real inbound signal, and dropping it silently meant the
                # dashboard could never show that a member was composing. Record
                # it as a transcript-only indicator instead; log_indicator keeps
                # it out of every Recipients count. SendRcsMessage has no
                # outbound typing indicator, so this inbound half is the whole
                # feature.
                phone = message.get("originationNumber", "")
                if phone:
                    c.log_indicator(c.hash_phone(phone), parsed["type"])
                continue
        except (json.JSONDecodeError, TypeError):
            pass

        process_inbound(message)

    return {"statusCode": 200}


# ── Inbound routing ─────────────────────────────────────────────────────────
def process_inbound(message):
    phone = message.get("originationNumber", "")
    raw = (message.get("messageBody") or "").strip()
    ph = c.hash_phone(phone)
    # messageKeyword names a keyword registered on the agent with put-keyword. The
    # built-in STOP and HELP arrive without it. _screen_freetext acts on
    # messageKeyword only when the message begins with that keyword, so a message
    # is routed by what the member typed. It is only ever a string; anything else
    # is ignored.
    keyword = message.get("messageKeyword")
    parsed = parse_inbound(raw, keyword.strip() if isinstance(keyword, str) else "")

    # Log the inbound message once, here — regardless of bot/live mode, so a
    # member-submitted photo always shows up for the Care Advocate even while
    # a human has taken over the thread. Media carries a distinct payload
    # shape (mediaStatus/s3Key/etc, not a rcs_content dict) that the
    # dashboard's JSON inspector needs to show accurately, so it's logged via
    # common.log_inbound_media rather than the generic log_message below.
    if parsed["type"] == "postback":
        c.log_message(ph, "inbound", f"[Tap] {parsed['postback_data']}")
    elif parsed["type"] == "trigger":
        c.log_message(ph, "inbound", f"Start: {parsed['vignette']}")
    elif parsed["type"] == "location":
        # Rounded to roughly a city block. The shared coordinates are precise
        # enough to identify a home, and this transcript is readable from the
        # dashboard; a provider search needs nothing finer.
        c.log_message(ph, "inbound", _location_label(parsed["latitude"], parsed["longitude"]))
    elif parsed["type"] == "media":
        c.log_inbound_media(ph, parsed["media"], phone)
        if parsed["media"].get("mediaStatus") == "SUCCESS":
            # Classification/conversion occurs asynchronously in media_convert
            # from the inbound/rcs S3 event. Record the raw source now so the
            # converter can replace it later on this exact message.
            c.set_latest_media(ph, parsed["media"])
    else:
        c.log_message(ph, "inbound", raw)

    # A sender on the service's opt-out list gets nothing back, whatever they sent:
    # every reply would be refused (see "Opt-out memory"). The inbound message
    # above is already in the transcript. Typed text is checked inside
    # _screen_freetext instead, because the service-keyword check there has to run
    # first: UNSTOP is how a member comes back.
    if parsed["type"] != "freetext" and _is_opted_out(phone, ph):
        _skip_opted_out(ph, _OPTED_OUT_SENT.get(parsed["type"], "a message"))
        return

    live = c.get_mode(ph) == "live"

    # Typed text is screened before live mode, sticky flows, the keyword router
    # and the AI, because each of those can swallow it: a member mid-verification
    # who types "I can't breathe" must not be told their code doesn't match.
    if parsed["type"] == "freetext" and _screen_freetext(phone, ph, parsed, live):
        return

    # Live-agent handover: while LIVE, a human replies via the dashboard. The bot
    # stays silent except to honor an explicit return to the assistant (a tapped
    # handover_end, a tapped Reset chip such as Start Over or the retired Main
    # Menu, or the typed reset words screened above). Media
    # is still logged above so it appears in the dashboard for the Care
    # Advocate. A successfully-received photo gets a one-line receipt, and
    # media_convert asynchronously replaces the raw file with a normalized
    # JPEG + classification in the dashboard.
    native_conversion_pending = _needs_native_conversion(parsed)
    if live:
        if parsed["type"] == "postback" and parsed["postback_data"] == "handover_end":
            c.set_mode(ph, "bot")
            _send(phone, ph, handover.resolved_card())
        elif parsed["type"] == "postback" and parsed["postback_data"] in RESET_POSTBACKS:
            # Start Over (reset_conversation) is on nearly every card, and
            # home_menu is the retired Main Menu id still on older cards, so
            # this is the member's most likely escape hatch if they're stuck in
            # a live conversation that isn't actually staffed (e.g. a demo
            # left in live mode). Reset the same way as in bot mode;
            # reset_session puts the thread back in bot mode. A member should
            # never have a dead button with no way back to the bot.
            reset_conversation(phone, ph)
        elif (parsed["type"] == "postback" and parsed["postback_data"] == "photo_secure_upload"
              and _allowed("insurance_upload")):
            # A secure-upload link is an explicit member action, not a bot
            # interruption. Honor it even during human handover so an iPhone
            # HEIC failure can immediately pivot to the compliance-forward
            # webview path. A brand that does not own the upload skips this arm
            # and gets the generic live-mode handling below.
            c.set_active_flow(ph, "insurance_upload")
            _send(phone, ph, get_flow("insurance_upload").on_start(phone, ph))
        elif parsed["type"] == "media" and parsed["media"].get("mediaStatus") == "SUCCESS":
            _send(phone, ph, _media_receipt_ack())
        elif parsed["type"] == "postback" and _is_action_only_postback(parsed["postback_data"]):
            # A chip that ran on the handset (dial, map, calendar, webview): the
            # member already has what they asked for, and the nudge below would
            # tell someone who just placed a call that the button "isn't active".
            # The emergency reply's call chip (c.call_label()) is one of these.
            print(f"ACTION POSTBACK {parsed['postback_data']} while live: the handset already ran the action; no reply sent")
        elif parsed["type"] == "postback":
            # Any other button tap while live (e.g. an old card's "Refill
            # Now" still on-screen from before handover started) is not
            # something a human agent can act on either — it's a dead flow
            # postback. Rather than silently dropping it (the member sees
            # nothing happen and has no idea why), nudge them toward the
            # one button that's guaranteed to work.
            _send(phone, ph, handover.stuck_nudge_card())
        return

    # Native images are converted/classified by the S3-triggered converter,
    # which calls back handle_native_media_ready below. Send a short receipt
    # now rather than attempting to render/classify raw HEIC bytes here.
    if native_conversion_pending:
        _send(phone, ph, _media_processing_ack())
        return

    if parsed["type"] == "trigger":
        handle_trigger(phone, ph, parsed["vignette"])
    elif parsed["type"] == "postback":
        handle_postback(phone, ph, parsed["postback_data"])
    elif parsed["type"] == "media":
        handle_media(phone, ph, parsed["media"])
    elif parsed["type"] == "location":
        handle_location(phone, ph, parsed["latitude"], parsed["longitude"])
    else:
        handle_freetext(phone, ph, raw)


def parse_inbound(body, keyword=""):
    """Classify one inbound messageBody. `keyword` is the payload's
    messageKeyword; it is carried on free-text turns only, because a tap, a
    shared location or media never starts with a registered keyword."""
    if body.lower().startswith("start:"):
        return {"type": "trigger", "vignette": body[6:].strip()}
    try:
        data = json.loads(body)
        if isinstance(data, dict):
            if data.get("type") == "SUGGESTION":
                return {"type": "postback", "postback_data": data.get("postbackData", "")}
            if data.get("type") == "LOCATION":
                return {"type": "location", "latitude": data.get("latitude"), "longitude": data.get("longitude")}
            # Inbound media (photo/video/audio/PDF) arrives as a JSON envelope
            # in messageBody: a bare object carrying mediaStatus (SUCCESS,
            # UPLOAD_FAILED, or ROLE_ASSUME_FAILED) plus
            # mimeType/fileName/fileSizeBytes, and on success s3Bucket/s3Key.
            # This sample detects it by that mediaStatus field. See:
            # https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-inbound-media.html
            if "mediaStatus" in data:
                return {"type": "media", "media": data}
    except (json.JSONDecodeError, TypeError):
        pass
    return {"type": "freetext", "text": body, "keyword": keyword}


def _allowed(vkey):
    """Whether the selected brand opens vignette `vkey` (common.vignette_allowed)."""
    return c.vignette_allowed(vkey)


def _fallback_flows():
    """Every distinct flow module the selected brand may open, in FLOW_MAP order.

    A module that serves several vignette keys (appointment serves appt_reminder
    and appt_reschedule) appears once, at its first allowed key, so a brand that
    owns only the second key still reaches it. A flow the brand does not own is
    never offered a postback. Derived from FLOW_MAP, not listed by hand, so a new
    flow is reachable without editing the postback fallback."""
    seen, flows = set(), []
    for vkey, flow in FLOW_MAP.items():
        if id(flow) in seen or not _allowed(vkey):
            continue
        seen.add(id(flow))
        flows.append(flow)
    return flows


def _foreign_to_menu(phone, ph, what, vkey):
    """A trigger, tile or typed intent named a vignette this brand does not own:
    log it (the log line names the brand, never the member's words) and answer
    with the brand's short Home_Menu, opening no flow. `what` is "TRIGGER",
    "TILE", "INTENT" or "LOCATION"."""
    print(f"FOREIGN {what} vignette={vkey!r} brand={c.brand_name()!r}")
    _send(phone, ph, welcome.home_menu(phone, ph))


def handle_trigger(phone, ph, vignette):
    vkey = vignette.lower().replace(" ", "_")
    flow = get_flow(vkey)
    # A known vignette that belongs to another brand never opens: the member
    # lands on this brand's Home_Menu. Unknown ids keep the TRIGGER_UNKNOWN path.
    if (flow or vkey in AI_DRIVEN_VIGNETTES) and not _allowed(vkey):
        _foreign_to_menu(phone, ph, "TRIGGER", vkey)
        return
    if flow:
        c.set_active_flow(ph, vkey)
        # Triggering handover has to flip the conversation into LIVE mode, the
        # same as the handover_start postback does. Without this the member gets
        # a card saying a care advocate is joining and then the AI answers them
        # anyway, which makes the operator console look broken when the vignette
        # is launched from the dashboard rather than by tapping a chip.
        if vkey == "handover":
            c.set_mode(ph, "live")
        _send(phone, ph, flow.on_trigger(phone, ph, vkey))
    elif vkey == "room_booking":
        # Room Booking session start: clear the carded property so the first
        # property the assistant presents gets its Property_Card (R15.9).
        c.set_active_flow(ph, vkey)
        c.set_booking_carded_property(ph, "")
        c.set_booking_context(ph, "")
        c.set_booking_quote(ph, {})
        c.set_booking_offer(ph, "")
        _booking_reply(phone, ph,
            f"The guest wants to book a hotel room. Greet them briefly as {c.brand_name()} and ask "
            "which city or property, their dates, and how many guests.")
    elif vkey in AI_DRIVEN_VIGNETTES:
        c.set_active_flow(ph, vkey)
        send_ai_response(phone, ph, invoke_ai(ph, _ai_start(vkey), vkey))
    else:
        # Falling back to the welcome is right for a member who typed something
        # we don't recognise, but it silently hides an operator-side mistake: a
        # dashboard vignette whose `trigger` string doesn't round-trip to a
        # FLOW_MAP key sends the welcome message instead, and the handset gets
        # the wrong vignette with nothing marked as failed. Name it in the log.
        print(f"TRIGGER_UNKNOWN vignette={vignette!r} key={vkey!r} -- sending welcome message")
        _send(phone, ph, welcome.on_start(phone, ph))


def _flow_postback(flow, phone, ph, pd):
    """Call a flow's on_postback if it has one, else fall through.

    on_postback is optional in practice — a flow whose chips are all handled by
    the dispatcher doesn't need it — but calling it unconditionally turned that
    into an AttributeError, i.e. a 500 from the webhook and a member who gets no
    reply at all. Degrade to the prefix fallback instead of dropping the turn.
    """
    handler = getattr(flow, "on_postback", None)
    if handler is None:
        return None
    return handler(phone, ph, pd)


# Postbacks from chips that run a native action on the handset: show a map, add
# a calendar event, open a webview or the browser. The phone performs the action
# itself and then reports the tap to the two-way topic like any other suggestion
# tap, so these arrive after the member already has what they asked for. There is
# nothing left for the demo to say, and handing the tap to the AI assistant used
# to produce an unrelated "I can only help with benefits" reply. A flow that is
# active still gets the first look (the IVS and video experiments acknowledge
# their chips); only a tap nobody claims is dropped, in handle_postback below.
# scripts/check-rcs-registry.py keeps this list in step with the chips the flows
# build, so a new action chip cannot reintroduce the stray reply.
#
# The chips the AI builds are a second family: common.build_suggestions gives
# every native-action chip a reserved id (common.AI_ACTION_POSTBACKS), whatever
# id the model supplied, so those taps are recognized by a fixed table and not
# by a list that tracks the model. _is_action_only_postback below is the one
# test for both families; nothing else may read ACTION_ONLY_POSTBACKS directly.
ACTION_ONLY_POSTBACKS = frozenset({
    "appt_cal",
    "appt_checklist_wv",
    "appt_directions",
    "appt_reschedule_cal",
    "bag_call",
    "bag_share",
    "board_cal",
    "board_pass_wv",
    "checkin_directions",
    "checkin_key_wv",
    "clock_summary_wv",
    "arrive_directions",
    "delivery_share",
    "delivery_share_new",
    "delivery_show_spot",
    "emergency_call_member_services",
    "fit_browser",
    "fit_webview_full",
    "fraud_call",
    "fstatus_call",
    "fstatus_map",
    "idcap_open_license",
    "idcap_open_passport",
    "ivs_browser",
    "ivs_webview_full",
    "loan_open",
    "probe_browser",
    "probe_webview_full",
    "probe_webview_half",
    "plan_cal",
    "pto_cal",
    "ready_cal",
    "ready_directions",
    "rebook_cal",
    "rx_call_pharm",
    "rx_details_wv",
    "rx_directions",
    "rx_patient_info_wv",
    "rx_remind",
    "sched_wv",
    "swap_view_schedule",
    "upload_open",
    "visit_join_browser",
    "visit_join_webview",
    "waiver_open",
})
# Ids the model's action chips carried before the builder reserved them. A card
# sent earlier can still be in a member's thread with one of these on it, and a
# tap on it reaches this Lambda like any other. Any other id the model improvised
# on such a card is unknown, and a tap on it still goes to the assistant.
LEGACY_AI_ACTION_POSTBACKS = frozenset({"call", "find_care_location"})


def _is_action_only_postback(pd):
    """True for a tap on a chip that already ran its action on the handset."""
    return (
        pd in ACTION_ONLY_POSTBACKS
        or pd in c.AI_ACTION_POSTBACKS.values()
        or pd in LEGACY_AI_ACTION_POSTBACKS
    )


# Postback ids the booking assistant has been seen to invent for its Confirm
# chip despite prompt rule 11. Normalized to booking_confirm so the confirmation
# rich card still fires.
BOOKING_CONFIRM_ALIASES = frozenset({"confirm_booking", "booking_confirmed", "confirm"})


def _apply_booking_quote(ph, data):
    """Price the stay the assistant identified and replace its summary text with
    the deterministic one (design C14).

    The model only identifies the stay (`quote`: property, room, ISO dates,
    guests); every number comes from room_booking_quote.price_stay. The `quote`
    field is always removed from the reply. An accepted stay replaces the stored
    one (with no reference yet) and the reply's text becomes summary_text(stay)
    alone: the property name is never prepended to a body or description.
    Returns `(reply, property_id)`; `property_id` is the accepted stay's property
    (the hint for apply_property_card, which names the card from content when the
    reply's own text names no single property), or None when the quote was
    missing or rejected, in which case the reply and the stored stay are untouched.
    A rich_card reply with no title gets one from content ("<name> — <city>");
    a title the model wrote stays as it is."""
    if not isinstance(data, dict):
        return data, None
    quote = data.pop("quote", None)
    if not isinstance(quote, dict):
        return data, None
    stay = room_booking_quote.price_stay(
        quote, datetime.now(timezone.utc).date(), c.booking_offer(ph))
    if not stay:
        print("BOOKING QUOTE: rejected")
        return data, None
    c.set_booking_quote(ph, stay)
    summary = room_booking_quote.summary_text(stay)
    kind = data.get("type")
    if kind == "rich_card":
        if not str(data.get("title") or ""):
            data["title"] = (f"{stay['property_name']} — {stay['city']}"
                             if stay.get("city") else stay["property_name"])
        data["description"] = summary
    elif kind == "text":
        data["body"] = summary
    return data, stay["property_id"]


def _booking_reply(phone, ph, user_message, picked=None):
    """One conversational Room Booking turn (design C9, C15).

    Runs the assistant, then merges the property's photo and an Open Map action
    into its reply when that reply presents exactly one property not yet carded
    in this booking session (room_booking_cards.apply_property_card), and sends
    the result as ONE message. The property is resolved from the reply, not the
    guest's input, so taps (any chip id), typed text and the offer handoff
    behave the same, except that a quote accepted this turn names its property
    as the hint when the reply's own text names none. The booking_confirm turn does NOT come through here: the
    confirmation card keeps its own map and call actions.

    Room photos (design C15): `picked` is the id of the Room_Type the guest chose
    with a Choose chip; unless a Property_Card was sent this turn, the reply
    becomes that room's Room_Detail_Card. When the reply offers two or more room
    types as reply chips, those chips are replaced by a Room_Carousel sent right
    after the reply; with fewer, or when no carousel can be built, the reply is
    sent unchanged with its chips (R21.7)."""
    data = invoke_ai(ph, user_message, "room_booking")
    data, quoted_id = _apply_booking_quote(ph, data)
    carded = c.booking_carded_property(ph)

    # Room chips are taken out BEFORE the property card is merged in: the card
    # keeps at most four chips (Open Map plus three), so three room chips and one
    # other chip would otherwise be cut at random, and the carousel or the other
    # chip lost with them.
    stripped, room_ids = room_booking_rooms.strip_room_chips(data)
    carousel = None
    if len(room_ids) >= 2:
        reply, pid = room_booking_cards.apply_property_card(stripped, carded, hint_id=quoted_id)
        stay = c.booking_quote(ph)
        prop_id = (stay or {}).get("property_id") or carded or pid or None
        carousel = room_booking_rooms.room_carousel(prop_id)
    if carousel is None:
        reply, pid = room_booking_cards.apply_property_card(data, carded, hint_id=quoted_id)
    if picked and not pid:
        reply = room_booking_rooms.room_detail(reply, picked)

    # The carousel goes out last through _send, which gives it the one Start Over
    # chip, so the reply before it carries none (R21.11).
    send_ai_response(phone, ph, reply, reset_chip=carousel is None)
    if carousel is not None:
        _send(phone, ph, [carousel])
    if pid:
        c.set_booking_carded_property(ph, pid)


# ── Conversation Reset ──────────────────────────────────────────────────────
# One Reset for every entry point (design C4). reset_conversation is the chip
# id; home_menu (the retired Main Menu label) and the two per-flow Start Over
# ids (checkin_restart, offers_browse) are kept so older chips already on a
# handset still reset instead of reloading one flow.
RESET_POSTBACK = "reset_conversation"
RESET_POSTBACKS = frozenset({"reset_conversation", "home_menu", "checkin_restart", "offers_browse"})
RESET_CHIP_TEXT = "Start Over"

# Labels that read as a reset whatever their postback, so a model-invented
# "Main Menu" chip is replaced rather than shown beside Start Over (R2.7).
_RESET_CHIP_LABELS = frozenset({"main menu", "start over"})


def reset_conversation(phone, ph):
    """One Reset for every entry point (R3.4): forget the guest's session
    choices, write the marker that cuts the assistant's memory, then send the
    selected brand's Home_Menu. The Home_Menu is sent even when a clearing step
    or the marker fails (R4.7); the log carries step names and error codes only.

    A Reset lands on the short Home_Menu (one card: brand banner, name and the
    homeMenu tiles). The three-card Welcome_Intro is first contact only: the
    "Start: Welcome" deep-link keyword, a bare greeting and the unknown-trigger
    fallback still send it."""
    try:
        failed = c.reset_session(ph)
        if failed:
            print(f"RESET incomplete: {', '.join(failed)}")
    except Exception as e:  # noqa: BLE001
        print(f"RESET incomplete: reset_session raised {c.error_code(e)}")
    try:
        if not c.log_reset(ph):
            print("RESET marker not written; the assistant may still see earlier turns")
    except Exception as e:  # noqa: BLE001
        print(f"RESET marker not written ({c.error_code(e)}); the assistant may still see earlier turns")
    _send(phone, ph, welcome.home_menu(phone, ph))


def _is_reset_chip(chip):
    """True for a reply chip that performs a Reset, by postback or by label."""
    if not isinstance(chip, dict):
        return False
    reply = chip.get("Reply")
    if not isinstance(reply, dict):
        return False
    if reply.get("PostbackData") in RESET_POSTBACKS:
        return True
    return str(reply.get("Text") or "").strip().lower() in _RESET_CHIP_LABELS


def _attach_reset_chip(content):
    """Return a copy of an RCS message with exactly one Start Over chip, last at
    message level (R2.1, R2.2, R2.5). Any other reset-equivalent chip is removed
    from the message and from a rich card's own chips (R2.7); carousel card
    chips are left alone. A full message drops its last other chip to make room
    (R2.4). Anything that is not a {"Content": ...} dict is returned unchanged."""
    if not isinstance(content, dict) or "Content" not in content:
        return content
    out = copy.deepcopy(content)
    body = out["Content"]
    if not isinstance(body, dict):
        return content

    card = body.get("RichCard")
    if isinstance(card, dict):
        card_content = card.get("CardContent")
        if isinstance(card_content, dict) and isinstance(card_content.get("Suggestions"), list):
            kept = [s for s in card_content["Suggestions"] if not _is_reset_chip(s)]
            if kept:
                card_content["Suggestions"] = kept
            else:
                del card_content["Suggestions"]

    # Message-level chips sit beside "Content", not inside it (see
    # c.validate_rcs_content and send_ai_response).
    chips = [s for s in (out.get("Suggestions") or []) if not _is_reset_chip(s)]
    limit = c.rcs_limit("suggestionsPerMessage")
    while chips and len(chips) >= limit:
        chips.pop()
    chips.append({"Reply": {"Text": "Start Over", "PostbackData": "reset_conversation"}})
    out["Suggestions"] = chips
    return out


def _without_reset_chips(content):
    """Return a copy of an RCS message with no reset-equivalent chip, at message
    level or on a rich card's own chips. For a reply that a message carrying the
    one Start Over chip follows: a "Main Menu" or "Start Over" chip the model
    invented must not sit beside it (R21.11, R2.7). Carousel card chips are left
    alone. Anything that is not a {"Content": ...} dict is returned unchanged."""
    if not isinstance(content, dict) or "Content" not in content:
        return content
    out = copy.deepcopy(content)
    body = out["Content"]
    if not isinstance(body, dict):
        return content
    card = body.get("RichCard")
    if isinstance(card, dict):
        card_content = card.get("CardContent")
        if isinstance(card_content, dict) and isinstance(card_content.get("Suggestions"), list):
            kept = [s for s in card_content["Suggestions"] if not _is_reset_chip(s)]
            if kept:
                card_content["Suggestions"] = kept
            else:
                del card_content["Suggestions"]
    if isinstance(out.get("Suggestions"), list):
        kept = [s for s in out["Suggestions"] if not _is_reset_chip(s)]
        if kept:
            out["Suggestions"] = kept
        else:
            del out["Suggestions"]
    return out


def handle_postback(phone, ph, pd):
    # Handover can be requested from anywhere.
    if pd == "handover_start":
        c.set_mode(ph, "live")
        _send(phone, ph, handover.escalate_card())
        return
    if pd == "handover_end":
        c.set_mode(ph, "bot")
        _send(phone, ph, handover.resolved_card())
        return

    # Every Reset entry point, checked before any flow or prefix fallback so a
    # per-flow id such as checkin_restart or offers_browse never reaches its flow.
    if pd in RESET_POSTBACKS:
        reset_conversation(phone, ph)
        return

    # The native-photo failure card links here. This must be an explicit flow
    # switch, not a generic free-text/AI fallback, so tapping "Secure Upload"
    # opens the HEIC-capable webview card again.
    if pd == "photo_secure_upload":
        # Only for a brand that owns the insurance upload; a stale chip from
        # another brand's card lands on this brand's Home_Menu instead.
        if not _allowed("insurance_upload"):
            _foreign_to_menu(phone, ph, "TILE", "insurance_upload")
            return
        c.set_active_flow(ph, "insurance_upload")
        _send(phone, ph, get_flow("insurance_upload").on_start(phone, ph))
        return

    home = {
        "home_rx": "rx_refill",
        "home_appt": "appt_reminder",
        "home_store": "store",
        "home_verify": "verification",
        # Internal staff vignettes (home-menu carousel tiles).
        "home_clock": "clock_in_out",
        "home_schedule": "my_schedule",
        "home_pto": "pto_request",
        "home_swap": "shift_swap",
        # Rich-media demos (home-menu carousel tiles).
        "home_photo": "photo_submission",
        "home_upload": "insurance_upload",
        # AnyTravel hotel vignettes (deterministic home-menu tiles).
        "home_checkin": "express_checkin",
        "home_offers": "travel_offers",
        # AnyTravel airline vignettes.
        "home_flight_checkin": "flight_checkin",
        "home_flight_status": "flight_status",
        "home_rebooking": "flight_rebooking",
        "home_bags": "bag_tracking",
        # AnyWealth home-menu tile.
        "home_fraud": "wealth_fraud_alert",
        "home_loan": "loan_agreement",
        # AnyBuild home-menu tiles.
        "home_hello_builder": "hello_builder",
        "home_hello_supplier": "hello_supplier",
        "home_evidence": "site_evidence",
        "home_idcap": "identity_capture",
        "home_arrival": "arrival_alert",
        "home_delivery": "delivery_location",
        "home_plan": "field_schedule",
        "home_ready": "job_readiness",
        "home_agreement": "agreement_waiver",
        # Brand assistants (AI): one tile each, see _ASSISTANTS.
        "home_ask_trip": "trip_assistant",
        "home_ask_account": "account_assistant",
        "home_ask_hr": "hr_assistant",
        "home_ask_site": "jobsite_assistant",
    }
    # A tile for a vignette this brand does not own opens nothing: the member
    # lands on the brand's Home_Menu, and no flow is set.
    if pd in home:
        vkey = home[pd]
        if not _allowed(vkey):
            _foreign_to_menu(phone, ph, "TILE", vkey)
            return
        c.set_active_flow(ph, vkey)
        if vkey in AI_DRIVEN_VIGNETTES:
            send_ai_response(phone, ph, invoke_ai(ph, _ai_start(vkey), vkey))
            return
        _send(phone, ph, get_flow(vkey).on_start(phone, ph))
        return
    tile_ai = {"home_benefits": "benefits_qa", "home_find_care": "find_care", "home_booking": "room_booking"}
    if pd in tile_ai and not _allowed(tile_ai[pd]):
        _foreign_to_menu(phone, ph, "TILE", tile_ai[pd])
        return
    if pd == "home_benefits":
        c.set_active_flow(ph, "benefits_qa")
        send_ai_response(phone, ph, invoke_ai(ph, "The member wants to ask about benefits and coverage. Greet briefly and ask how you can help.", "benefits_qa"))
        return
    if pd == "home_find_care":
        c.set_active_flow(ph, "find_care")
        send_ai_response(phone, ph, invoke_ai(ph, "The member wants to find an in-network provider. Ask what type of care they need.", "find_care"))
        return
    if pd == "home_booking":
        c.set_active_flow(ph, "room_booking")
        c.set_booking_carded_property(ph, "")
        c.set_booking_context(ph, "")
        c.set_booking_quote(ph, {})
        c.set_booking_offer(ph, "")
        _booking_reply(phone, ph,
            f"The guest wants to book a hotel room. Greet them briefly as {c.brand_name()} and ask "
            "which city or property, their dates, and how many guests.")
        return

    # Choose chip on a Room_Carousel card (design C15). Explicit, before the
    # active-flow routing, so the tap is neither handed to the assistant as an
    # opaque "Member tapped" line nor lost when the flow state has expired. An
    # unknown id or a brand without Room Booking lands on the Home_Menu.
    if pd.startswith(room_booking_rooms.PICK_PREFIX):
        room_id = pd[len(room_booking_rooms.PICK_PREFIX):]
        room = c.room_type_by_id(room_id)
        if not room or not _allowed("room_booking"):
            _foreign_to_menu(phone, ph, "TILE", "room_booking")
            return
        if c.get_active_flow(ph) != "room_booking":
            c.set_active_flow(ph, "room_booking")
        _booking_reply(phone, ph, f"I'd like the {room.get('name', '')}.", picked=room_id)
        return

    # Booking confirmation chip from the booking assistant — route back to the
    # model so it produces the confirmation turn, mirroring how other AI
    # postbacks are handled. Explicit (rather than relying on the active-flow
    # branch below) so it works even if flow state has expired. Re-branded to
    # read c.brand_name() / c.member_services_phone() rather than literals, so
    # the no-brand-literal scan stays green, and the four actions are described
    # by kind (not with literal postbacks on action chips) so build_suggestions
    # assigns their ids and the registry checker's action-chip scan stays green.
    if pd in BOOKING_CONFIRM_ALIASES:
        pd = "booking_confirm"
    if pd == "booking_confirm":
        # A stale Confirm Booking chip from a brand that has no Room Booking.
        if not _allowed("room_booking"):
            _foreign_to_menu(phone, ph, "TILE", "room_booking")
            return
        c.set_active_flow(ph, "room_booking")
        # Deterministic confirmation (design C14): when a priced stay is stored,
        # build the card from it with no model call, so the numbers equal the
        # summary's. The reference is minted once and stored, so a second tap
        # shows the same one. No stored stay (or any error) falls through to the
        # model-based instruction below.
        card = None
        try:
            stay = c.booking_quote(ph)
            if stay and stay.get("property_id"):
                ref = stay.get("reference") or room_booking_quote.new_reference()
                if not stay.get("reference"):
                    stay["reference"] = ref
                    c.set_booking_quote(ph, stay)
                names = (c.tester_name(ph, fallback=c.member_name()) or "").split()
                first = names[0] if names else ""
                card = room_booking_quote.confirmation_card(stay, first, ref)
        except Exception as e:
            print(f"BOOKING CONFIRM: deterministic card failed ({type(e).__name__}); using model path")
            card = None
        if card:
            send_ai_response(phone, ph, card)
            return
        send_ai_response(phone, ph, invoke_ai(
            ph,
            "The guest confirmed the booking (tapped Confirm Booking or typed a confirmation). Finalize the booking now using the "
            "property, dates, room type and guest count already gathered earlier in THIS "
            "conversation. Respond with a SINGLE rich_card:\n"
            '- title: "Booking Confirmed! 🎉"\n'
            "- description: a clean, line-by-line summary in this order, each on its own "
            "line — property name — city/state; check-in – check-out (N nights); room type "
            "· N guests; the member rate per night; estimated total; a blank line; then "
            f'"Reference: {room_booking_quote.new_reference()}", exactly as written. After another '
            "blank line, add ONE warm, personalized closing sentence addressing the guest "
            "by first name that invites them to save the stay to their calendar below, and "
            "if the stay is tied to an event, wish them well at it.\n"
            "Include exactly these three actions and no others (the app adds the Start "
            'Over chip itself): an Add to Calendar action {"type":"calendar","text":"Add to Calendar",'
            '"start_time":"<check-in ISO 8601>","end_time":"<check-out ISO 8601>",'
            '"title":"<property name> stay","description":"<short summary>"}; its '
            "start_time and end_time MUST be ISO 8601 with the same dates as the stay "
            "shown on the card and a year that is not in the past (resolve a missing "
            "year against TODAY); a View on "
            'Map action {"type":"view_location","text":"View on Map","latitude":<number>,'
            '"longitude":<number>,"label":"<property name>"} (the real dates and the '
            "property's real coordinates from the knowledge above), and a Call action "
            f'with the text "{c.call_label()}" (dial {c.member_services_phone()}). '
            "Do NOT include a Confirm Booking button. "
            "Do NOT send any second message. Do NOT ask again for anything already provided.",
            "room_booking",
        ))
        return

    # Travel Offers → Room Booking handoff. Selecting an offer from the
    # carousel ("Book This Stay") flows straight into the agentic booking
    # assistant with the offer's property AND its implied stay dates already
    # filled in, so the guest never re-enters what the offer implied — they
    # only confirm guest count and the booking. Intercepted here (not in the
    # travel_offers flow module, which deliberately does NOT handle
    # offers_book_*) because entering an AI-driven flow needs
    # send_ai_response/invoke_ai, which a deterministic flow module cannot call.
    # Placed before the generic active-flow / offers_ prefix fallback so the
    # offers_ prefix never reaches the travel_offers flow for this postback.
    if pd.startswith("offers_book_"):
        if not _allowed("room_booking"):
            _foreign_to_menu(phone, ph, "TILE", "room_booking")
            return
        oid = pd[len("offers_book_"):]
        offer = c.travel_offer_by_id(oid)
        if not offer:                                   # R10.5 "no longer available" guard
            _send(phone, ph, [{"Content": {"TextMessage": {"Body":
                "Sorry, that offer is no longer available."}}}])
            return
        prop = c.hotel_property_by_id(offer.get("propertyId", "")) or {}
        c.set_active_flow(ph, "room_booking")
        # The offer's fixed dates go stale; roll them forward so price_stay accepts
        # them and the member rate survives (R20.10). Raw content on failure.
        d_in, d_out = room_booking_quote.offer_dates(
            offer, datetime.now(timezone.utc).date()
        ) or (offer.get("checkIn", ""), offer.get("checkOut", ""))
        details = (
            f"- Property: {prop.get('name', '')} ({prop.get('city', '')})\n"
            f"- Event: {offer.get('event', '')}\n"
            f"- Check-in: {d_in} (YYYY-MM-DD)\n"
            f"- Check-out: {d_out} (YYYY-MM-DD)\n"
            f"- Member rate: ${float(offer.get('memberRate', 0) or 0):.0f}/night\n"
            f"- Included perk: {offer.get('perk', '')}"
        )
        seed = (
            "The guest selected a member travel offer and wants to book it. These details "
            "are ALREADY chosen from the offer — treat them as given and do NOT ask for "
            "the city, property, or dates again:\n"
            f"{details}\n"
            "Greet the guest, acknowledge the offer by name, and ask only for the number "
            "of guests (and room type if relevant). Then summarize the stay and offer the "
            "Confirm Booking suggestion as usual."
        )
        c.set_booking_carded_property(ph, "")
        c.set_booking_context(ph, details)
        # Clear any earlier priced stay and record the offer BEFORE the first
        # reply, so that reply can be priced at the offer's member rate (C14).
        c.set_booking_quote(ph, {})
        c.set_booking_offer(ph, oid)
        _booking_reply(phone, ph, seed)
        return

    # Book a Hotel Tonight on a Disruption Rebooking confirmation: the traveler's
    # new flight leaves tomorrow, so hand off to the Room Booking assistant with
    # the airport hotel and tonight's dates already chosen. Intercepted here for
    # the same reason as offers_book_* above (an AI flow needs invoke_ai), and
    # before the rebook_ prefix fallback, so the rebooking flow never sees it.
    if pd == "rebook_hotel":
        if not _allowed("room_booking"):
            _foreign_to_menu(phone, ph, "TILE", "room_booking")
            return
        dz = c.disruption()
        prop = c.hotel_property_by_id(dz.get("overnightPropertyId", "")) or {}
        if not prop:
            _send(phone, ph, [{"Content": {"TextMessage": {"Body":
                "Sorry, there's no partner hotel to offer for tonight."}}}])
            return
        tonight = (dz.get("cancelled") or {}).get("dateObj") or datetime.now(timezone.utc).date()
        details = (
            f"- Property: {prop.get('name', '')} ({prop.get('city', '')})\n"
            f"- Check-in: {tonight.isoformat()} (YYYY-MM-DD)\n"
            f"- Check-out: {(tonight + timedelta(days=1)).isoformat()} (YYYY-MM-DD)\n"
            "- Reason: an overnight stay after a cancelled flight"
        )
        seed = (
            "The traveler's flight was cancelled and they were rebooked onto a flight "
            "tomorrow, so they need a room tonight near the airport. These details are "
            "ALREADY chosen — treat them as given and do NOT ask for the city, property, "
            "or dates again:\n"
            f"{details}\n"
            "Greet them briefly, acknowledge the disrupted trip, and ask only for the "
            "number of guests (and room type if relevant). Then summarize the stay and "
            "offer the Confirm Booking suggestion as usual."
        )
        c.set_active_flow(ph, "room_booking")
        c.set_booking_carded_property(ph, "")
        c.set_booking_context(ph, details)
        c.set_booking_quote(ph, {})
        c.set_booking_offer(ph, "")
        _booking_reply(phone, ph, seed)
        return

    # Cross-flow jumps from My Schedule into PTO Request / Shift Swap. These
    # are explicit switches (mirroring the `home` dict above) rather than
    # relying on the prefix fallback below, so the active-flow state stays
    # correct for anything the target flow does next (e.g. free-text or a
    # second postback).
    internal_jumps = {"sched_pto": "pto_request", "sched_swap": "shift_swap"}
    if pd in internal_jumps:
        vkey = internal_jumps[pd]
        if not _allowed(vkey):
            _foreign_to_menu(phone, ph, "TILE", vkey)
            return
        c.set_active_flow(ph, vkey)
        _send(phone, ph, get_flow(vkey).on_start(phone, ph))
        return

    # Route to the active flow.
    active = c.get_active_flow(ph)
    # A stale active flow the brand does not own (state from before a brand
    # switch) is treated as no active flow: it gets no first look.
    if active and not _allowed(active):
        active = ""
    if active in AI_DRIVEN_VIGNETTES and not _is_action_only_postback(pd):
        if active == "room_booking":
            _booking_reply(phone, ph, f'Member tapped: "{pd}"')
            return
        send_ai_response(phone, ph, invoke_ai(ph, f'Member tapped: "{pd}"', active))
        return
    flow = get_flow(active) if active else None
    if flow:
        messages = _flow_postback(flow, phone, ph, pd)
        if messages:
            _send(phone, ph, messages)
            return

    # Fall back: offer the postback to every flow the brand owns (_fallback_flows),
    # so a chip is answered by its flow whether or not that flow is still active.
    for fallback_flow in _fallback_flows():
        messages = _flow_postback(fallback_flow, phone, ph, pd)
        if messages:
            _send(phone, ph, messages)
            return

    if _is_action_only_postback(pd):
        print(f"ACTION POSTBACK {pd}: the handset already ran the action; no reply sent")
        return

    # Last resort: let the assistant handle it.
    _last_resort(phone, ph, pd, active)


def _last_resort(phone, ph, pd, active):
    """A tap no flow claimed and that is not an action chip. `active` is already
    cleared when this brand does not own it. An AI flow the brand owns keeps the
    tap; otherwise the brand's own default route answers (its `defaultVignette`
    when that is an AI vignette it owns, else its Home_Menu). No vignette is
    hard-coded, so a brand never gets another brand's assistant."""
    message = f'Member tapped: "{pd}"'
    if active in AI_DRIVEN_VIGNETTES and _allowed(active):
        if active == "room_booking":
            _booking_reply(phone, ph, message)
        else:
            send_ai_response(phone, ph, invoke_ai(ph, message, active))
        return
    _default_route(phone, ph, message)


# Entry-point keywords, matched *exactly* (after normalization) rather than by
# the intent matching further down. Two reasons that distinction matters:
#
#   1. brand.md's deepLinkKeyword is the message body the agent's inbound deep
#      link pre-populates (console → RCS agent → Testing → Inbound deep link).
#      Scanning that QR code is how a member starts a conversation with the
#      agent from a poster, a web page, or an email — the phone sends first and
#      there is no prior state, so this is the demo's front door.
#   2. A keyword registered with pinpoint-sms-voice-v2 put-keyword is answered
#      by AWS End User Messaging itself, which can only send the fixed
#      KeywordMessage string — no carousel, no cards, no flow state. The service
#      also publishes the inbound message to the two-way topic (with
#      messageKeyword set), and _screen_freetext treats a message that begins
#      with that keyword as already answered. So registering the deep-link keyword
#      would leave the member with the fixed string and no welcome. Handling it
#      here instead buys the full rich-card vocabulary. STOP, HELP and UNSTOP are
#      the opposite case — see the notes above _SERVICE_KEYWORD_FAMILIES. See
#      docs/architecture.md section 2.1.
#
# "menu" and "main menu" are not here: they are global escape words, handled by
# _screen_freetext in every mode and from every flow.
_GREETING_KEYWORDS = {"hi", "hello", "hey", "start", "demo", "get started"}


def _normalize_keyword(text):
    """Lowercase, strip surrounding punctuation/emoji, collapse whitespace — so
    "Get started", "get started!" and "  GET  STARTED " all match."""
    cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in (text or "").lower())
    return " ".join(cleaned.split())


def _match_text(text):
    """_normalize_keyword with apostrophes dropped rather than spaced, so
    "can't" is "cant" and not "can t". The screens and the keyword router
    below run word-boundary regexes over this form."""
    return _normalize_keyword((text or "").replace("'", "").replace("’", "").replace("`", "").replace("´", ""))


# ── Typed-text screens ──────────────────────────────────────────────────────
# _screen_freetext runs these on every typed message, in this order, before
# live mode, any sticky flow, the keyword router or the AI can see it:
#   1. emergency language   → a fixed 911 / 988 reply
#   2. service keywords     → no reply from this stack (the built-in STOP and
#                             HELP, and any keyword registered on the agent)
#   3. opt-out list         → no reply to a sender the service has opted out
#   4. global escape words  → "menu" and "human" work from anywhere
#
# Emergency numbers. These are US numbers: 911 for a medical emergency and 988
# for the Suicide & Crisis Lifeline. A deployment outside the US MUST change all
# three constants (and re-read the wording in _emergency_reply) before it talks
# to a real member.
EMERGENCY_NUMBER = "911"
CRISIS_LINE_NUMBER = "988"
CRISIS_LINE_NAME = "Suicide & Crisis Lifeline"

# Shown above the reply bubble in the dashboard transcript, so an operator
# reading a live thread can tell the bot, not a colleague, sent it.
_SAFETY_ACTOR = "Automatic safety reply"

# A small, reviewed list, matched as whole words against _match_text() output.
# A false positive costs one extra message with a Start Over chip; a miss can cost
# far more, so this leans toward matching. The exception is words that also turn
# up in ordinary plan and pharmacy questions ("refill my seizure medication",
# "is stroke rehab covered", an order or room number 911): those match only as
# "having a ..." or as the entire message (_EMERGENCY_WHOLE_MESSAGE).
#
# This is a safety net for common phrasings, NOT a triage or classification
# system. It reads no context, understands no negation or tense, and will miss
# anything phrased in a way nobody has listed. It stands in for neither clinical
# judgment nor a real screening service, and a deployment that talks to real
# members needs more than a regex list. When adding a phrase, think of the
# ordinary sentence it would also match ("I'm dying to know", "I can't go on
# Tuesday") and guard against it, as the patterns below do.
_EMERGENCY_PHRASES = (
    # Heart, breathing, bleeding, consciousness
    r"chest (?:pain|pains|tightness|pressure)",
    r"(?:cant|cannot|can not|couldnt|unable to|hard to|struggling to) breathe?",
    r"(?:trouble|difficulty|struggling with) breathing",
    r"(?:not|isnt|arent|stopped) breathing",
    r"(?:cant|cannot|can not|couldnt) catch (?:my |a |the )?breath",
    r"short of breath",
    r"(?:my )?chest (?:hurts|is hurting)",
    r"pain in (?:my|the) chest",
    r"chok(?:e|ing|ed)(?! hazards?)",
    r"(?:need|call|get) (?:an |the )?ambulance",
    r"bleeding (?:heavily|badly|profusely|a lot|out)",
    r"(?:wont|cant|cannot|can not) stop (?:the )?bleeding",
    r"bleeding (?:wont|will not|doesnt|isnt) stop",
    r"unconscious",
    r"passed out",
    r"having (?:a |an )?(?:heart attack|stroke|seizures?)",
    # "I am dying" and "I think I'm dying", but not "dying to know", "dying for a
    # coffee", "dying of laughter" or a phone that is dying (no "I" before it).
    r"(?:i am|im) dying(?! (?:to|for|laughing|inside|here|of (?:laughter|laughing|boredom|embarrassment|curiosity|thirst|hunger))\b)",
    # A number typed instead of a description. Inside a sentence 911 and 988 are
    # also order, room and invoice numbers, so only the request form matches here
    # and the bare number matches only as the whole message.
    r"(?:call|calling|dial|dialing|text|texting) (?:911|988)",
    # Overdose and allergic reaction
    r"overdos(?:e|es|ed|ing)",
    r"took too many (?:of )?(?:my |the )?(?:pills|tablets|capsules|meds|medications?)",
    r"anaphyla(?:xis|ctic)",
    r"severe allergic reaction",
    r"throat (?:is )?(?:closing|swelling)",
    # Self-harm, including on someone else's behalf
    r"suicid(?:e|es|al)",
    r"kill(?:ing)? (?:myself|my self|himself|herself|themselves)",
    r"(?:hurt|hurting|harm|harming) (?:myself|my self|himself|herself|themselves)",
    r"self harm",
    r"want(?:s|ed)? to die",
    r"wanna die",
    r"(?:end|ending|take|taking) (?:my|his|her|their) own life",
    r"(?:end|ending) (?:my|his|her|their) life(?! insurance| policy| coverage)",
    r"(?:end|ending) it all",
    r"better off dead",
    r"wish (?:i|he|she|they) (?:was|were) dead",
    r"feel(?:s|ing)? like dying",
    r"dont want to be here (?:anymore|any more)",
    r"dont want to (?:live|be alive)(?! (?:in|at|on|near|far|by|here|there)\b)",
    # "I can't go on" is also "I can't go on Tuesday" or "on a date", so a
    # preposition, article, day, month or number straight after it is not a match.
    r"(?:cant|cannot|can not) go on(?! (?:a|an|the|my|our|your|to|in|for|at|from|until|till|by|tomorrow|today|tonight|next|this|that|vacation|holiday|trip|date|(?:mon|tues|wednes|thurs|fri|satur|sun)day|(?:jan|febr)uary|march|april|may|june|july|august|(?:sept|nov|dec)ember|october)\b)(?! \d)",
    r"(?:i am|im|hes|shes|he is|she is) done with (?:life|living)(?! (?:insurance|policy|coverage|in|at|here|there|with|near|on|off|alone)\b)",
    r"no (?:reason|point) (?:to|in) (?:live|living|be alive|being alive|go on|going on)(?! (?:in|at|on|near|far|by|here|there)\b)",
    r"nothing (?:left )?to live for",
    r"cut myself (?:on purpose|deliberately|intentionally)",
    r"cutting (?:myself|my self|himself|herself|themselves)(?! (?:some|a|an|off|loose|short|out|free|slack|while|when|shaving)\b)",
    # Harm to others
    r"kill(?:ing)? (?:someone|somebody)",
    r"(?:i am|im|ill|i will|i want to|i wanna|i need to|i have to|i feel like)(?: going to| gonna| about to)? (?:hurt|hurting|harm|harming|kill|killing|attack|attacking|stab|stabbing|shoot|shooting) (?:someone|somebody|him|her|them|people|everyone|everybody)(?! (?:feelings?|pride|chances)\b)",
)
_EMERGENCY_RE = re.compile(r"\b(?:" + "|".join(_EMERGENCY_PHRASES) + r")\b")
_EMERGENCY_WHOLE_MESSAGE = frozenset({
    "heart attack", "a heart attack", "stroke", "a stroke", "seizure", "a seizure",
    "911", "988", "911 please", "988 please", "please 911", "please 988",
})


def _is_emergency(norm):
    return norm in _EMERGENCY_WHOLE_MESSAGE or bool(_EMERGENCY_RE.search(norm))


def _emergency_reply():
    body = (
        f"This is an automated message. If this is a medical emergency, call {EMERGENCY_NUMBER} now. "
        f"If you are thinking about harming yourself, call or text {CRISIS_LINE_NUMBER} "
        f"({CRISIS_LINE_NAME}) any time. For anything else, member services can help."
    )
    return [{
        "Content": {"TextMessage": {"Body": body}},
        "Suggestions": [
            {"DialPhone": {
                "Text": c.call_label(), "PostbackData": "emergency_call_member_services",
                "PhoneNumber": c.member_services_phone(),
            }},
        ],
        # The plain-text twin goes out as SMS if RCS fails, when SMS fallback is
        # configured (common.send_rcs). It is the same words: this is the one
        # message that must arrive.
        "_fallback_body": body,
    }]


def _handle_emergency(phone, ph, live):
    # The log line never carries the member's words. In live mode the bot is
    # otherwise silent, so the line and the labeled reply in the transcript are
    # how an operator learns the thread needs attention now.
    print(
        f"EMERGENCY LANGUAGE in a member message: sent the fixed {EMERGENCY_NUMBER}/{CRISIS_LINE_NUMBER} reply"
        + (" while the thread is LIVE; a care advocate should look at it now" if live else "")
    )
    _send(phone, ph, _emergency_reply(), actor=_SAFETY_ACTOR)


# ── Opt-out memory ──────────────────────────────────────────────────────────
# A member who texts STOP lands on the account's Default opt-out list, and from
# then on the service refuses every send to them with
# DESTINATION_PHONE_NUMBER_OPTED_OUT: flow cards and AI replies alike. A bot that
# does not notice still makes a Bedrock call for each message and writes outbound
# transcript rows next to SEND_FAILED events for replies that can never arrive.
#
# So before it answers anything, the adapter asks the service whether the sender
# is on the list (DescribeOptedOutNumbers). The service's list stays the only
# source of truth. This stack stores no opt-out flag of its own, because a stored
# flag drifts: an admin's delete-opted-out-number, or an OPT_IN keyword the member
# texts, clears the service's entry, and a stale local flag would go on silencing
# a member who had re-subscribed. What is kept is each answer for
# OPT_OUT_CACHE_TTL_SECONDS, so a burst of messages costs one call (most
# control-plane calls are limited to about one request per second per account and
# Region).
#
# The check stops this Lambda, not the whole stack: a photo is converted and
# classified by media_convert, which the S3 upload starts independently of this
# Lambda and which has no opt-out check, so a photo from an opted-out member still
# costs its vision calls (a description, plus up to two orientation checks). Only
# the reply is skipped here (handle_native_media_ready).
#
# It fails open. A throttled, denied or timed-out lookup counts as "not opted
# out": a lookup error or throttle must never silence a member, and the worst case is
# the behavior this stack had before the check existed. A production sender should
# still keep its own record of opt-outs, as AWS's RCS best practices advise.
#
# The list name is "Default", which is the RCS agent's list (the same name the
# Recipients tab reads in dashboard_handler.opted_out_numbers).
OPT_OUT_LIST_NAME = "Default"
OPT_OUT_CACHE_TTL_SECONDS = 30
_OPT_OUT_CACHE_MAX_ENTRIES = 256

# Phone hash -> (time the answer was taken, opted out?). Per container, so a burst
# on one container costs one lookup and a new container starts empty.
_opt_out_cache = {}
# Error classes already reported by this container, so a throttled burst logs one line.
_opt_out_errors_logged = set()

# A lookup that hangs would hold up the reply it was meant to protect, so this
# client gives up quickly (and retries once) instead of using the shared one's
# defaults. The failure is the "not opted out" answer above.
_opt_out_client = boto3.client(
    "pinpoint-sms-voice-v2",
    region_name=c.REGION,
    config=Config(connect_timeout=2, read_timeout=3, retries={"max_attempts": 1, "mode": "standard"}),
)

# What process_inbound says it skipped, by parsed message type.
_OPTED_OUT_SENT = {
    "freetext": "a typed message",
    "postback": "a button tap",
    "trigger": "a Start: message",
    "location": "a shared location",
    "media": "a photo or file",
}


def _lookup_opt_out(phone):
    """Ask the service whether this number is on the opt-out list. False on any
    failure (see "Opt-out memory"), so callers cannot tell "no" from "unknown"."""
    number = c.normalize_phone(phone)
    if not number:
        return False
    try:
        resp = _opt_out_client.describe_opted_out_numbers(
            OptOutListName=OPT_OUT_LIST_NAME, OptedOutNumbers=[number]
        )
    except Exception as e:  # noqa: BLE001
        code = c.error_code(e)
        # A number that is not on the list can come back as an empty result or as
        # ResourceNotFoundException. Either way the answer is "not opted out", and
        # it is the common one, so it is not logged.
        if code != "ResourceNotFoundException" and code not in _opt_out_errors_logged:
            _opt_out_errors_logged.add(code)
            print(
                f"OPT-OUT LOOKUP FAILED ({code}): treating the sender as not opted out; "
                "further failures of this kind from this container are not logged"
            )
        return False
    return any(
        isinstance(n, dict) and c.normalize_phone(n.get("OptedOutNumber")) == number
        for n in resp.get("OptedOutNumbers") or []
    )


def _remember_opt_out(ph, opted_out):
    """Store an answer. Insertion order is recency order (the key is re-inserted),
    so a full cache drops what it heard from longest ago."""
    now = time.time()
    _opt_out_cache.pop(ph, None)
    if len(_opt_out_cache) >= _OPT_OUT_CACHE_MAX_ENTRIES:
        for key in [k for k, (at, _) in _opt_out_cache.items() if not 0 <= now - at < OPT_OUT_CACHE_TTL_SECONDS]:
            del _opt_out_cache[key]
        if len(_opt_out_cache) >= _OPT_OUT_CACHE_MAX_ENTRIES:
            del _opt_out_cache[next(iter(_opt_out_cache))]
    _opt_out_cache[ph] = (now, opted_out)


def _is_opted_out(phone, ph, fresh=False):
    """True if the service's list names this sender, from a recent answer when
    there is one. `fresh` skips the stored answer and asks again. The age is the
    wall clock, which also covers the time a frozen container sat idle; an entry
    stamped in the future (the clock stepped back) is treated as expired."""
    hit = _opt_out_cache.get(ph)
    if hit and not fresh and 0 <= time.time() - hit[0] < OPT_OUT_CACHE_TTL_SECONDS:
        return hit[1]
    opted_out = _lookup_opt_out(phone)
    _remember_opt_out(ph, opted_out)
    return opted_out


def _skip_opted_out(ph, sent):
    """Say the reply to `sent` was not attempted, and leave a transcript marker."""
    print(f"OPTED OUT: skipping the reply to {sent} - the service refuses sends to this number")
    c.log_indicator(ph, "OPTED_OUT_SKIPPED")


# Messages the service has already answered. The service replies to the built-in
# STOP and HELP, and to a message that begins with a keyword registered on the
# agent (UNSTOP, anything an operator adds in the Settings tab), and also
# publishes that inbound message to the two-way topic. So the message does reach
# this Lambda, but anything sent from here would be a second answer. This stack
# therefore says nothing for such a message, calls no model, claims no account
# action, and records only a transcript marker.
#
# What a real Android handset and a TESTING agent showed (STOP, HELP and UNSTOP,
# 2026-10):
#   * the built-in STOP and HELP arrive with NO messageKeyword at all, so the
#     typed-text check below (_SERVICE_KEYWORD_TEXT) is what recognizes them;
#   * a keyword registered with put-keyword (UNSTOP) arrives with messageKeyword
#     set, and _keyword_matches_text acts on it only when the message text begins
#     with it.
#
# The same session showed the service enforcing the opt-out: STOP put the number
# on the account's Default opt-out list, and every later send to it was refused
# with DESTINATION_PHONE_NUMBER_OPTED_OUT. "Opt-out memory" above is what stops
# this stack answering such a member. A member can opt back in by text only if an
# OPT_IN keyword such as UNSTOP is registered (see "Register the keyword
# replies" in AGENTS.md); START was not tested as a keyword. None of this was
# checked on a country-launched agent.
#
# The family below only names the marker, not an action: the payload carries the
# keyword that matched, not what it is configured to do. The opt-out names are
# the ones AWS documents as required opt-out keywords; UNSTOP and START are the
# documented opt-in names; any other keyword is CUSTOM.
_SERVICE_KEYWORD_FAMILIES = {
    **dict.fromkeys(
        ("STOP", "UNSUBSCRIBE", "CANCEL", "END", "QUIT", "OPTOUT", "REMOVE", "ARRET", "TD"), "STOP"
    ),
    "HELP": "HELP",
    "UNSTOP": "START",
    "START": "START",
}
# Typed text with no (usable) messageKeyword: this is what recognizes the built-in
# STOP and HELP. Deliberately shorter than the table above: "cancel", "end",
# "quit" and "remove" are ordinary words inside the flows, and "start" is the
# welcome greeting (_GREETING_KEYWORDS). They count as service keywords only when
# the service says it matched them.
_SERVICE_KEYWORD_TEXT = {"stop": "STOP", "unsubscribe": "STOP", "help": "HELP", "unstop": "START"}


def _keyword_matches_text(message_keyword, norm):
    """True if the typed text begins with the keyword the service reported.

    Compared with punctuation and spaces removed on both sides, so "OPT-OUT"
    matches "opt out please". A message that does not begin with the keyword
    carries a marker it does not begin with (see the notes above) and is routed
    as ordinary text."""
    wanted = re.sub(r"[^a-z0-9]", "", (message_keyword or "").lower())
    typed = re.sub(r"[^a-z0-9]", "", norm or "")
    return bool(wanted) and typed.startswith(wanted)


def _service_keyword_family(message_keyword, norm):
    """STOP, HELP, START or CUSTOM when the service has answered this message,
    else None. Any messageKeyword counts, the family only names the marker;
    callers drop a marker the message does not begin with first
    (_keyword_matches_text)."""
    if message_keyword:
        # "OPT-OUT" and "OPTOUT" are the same keyword.
        return _SERVICE_KEYWORD_FAMILIES.get(re.sub(r"[^A-Z]", "", message_keyword.upper()), "CUSTOM")
    return _SERVICE_KEYWORD_TEXT.get(norm)


def _handle_service_keyword(ph, family, keyword):
    # log_indicator writes the dashboard's transcript marker (KEYWORD_STOP,
    # KEYWORD_HELP, KEYWORD_START, KEYWORD_CUSTOM); the inbound text itself was
    # already logged. `keyword` is the payload's messageKeyword, empty when the
    # match was on the message text alone. A registered keyword is at most 30
    # characters, so the slice only bounds a malformed payload.
    source = f"messageKeyword {keyword[:30]!r}" if keyword else "message text"
    print(
        f"SERVICE KEYWORD {family} (from {source}): matched as a service keyword, "
        "so this stack sends no reply and makes no AI call"
    )
    c.log_indicator(ph, f"KEYWORD_{family}")
    # The service updates its opt-out list in the same second as it answers, so
    # waiting out the cache would answer the member's very next message. A STOP
    # marks them opted out now. A START only drops the stored answer: whether the
    # keyword was an OPT_IN is not in the payload, so the next message asks the
    # service, which knows.
    if family == "STOP":
        _remember_opt_out(ph, True)
    elif family == "START":
        _opt_out_cache.pop(ph, None)


# Typed escapes that work from any sticky flow and from live mode. Exact matches
# after normalization (a trailing "please" is ignored), never substrings, so a
# sentence that merely contains "home" or "agent" is left to the router.
_MENU_ESCAPES = frozenset({"menu", "main menu", "home", "start over", "reset", "restart"})
_HUMAN_ESCAPES = frozenset({
    "human", "agent", "representative", "a human", "an agent", "live agent", "real person",
    "talk to a human", "talk to a person", "talk to an agent", "talk to a representative",
    "speak to a human", "speak to a person", "speak to an agent", "speak to a representative",
})


def _screen_freetext(phone, ph, parsed, live):
    """Handle typed text that must not reach live mode, a sticky flow, the
    keyword router or the AI. Returns True when the message is fully dealt with."""
    norm = _match_text(parsed["text"])

    if _is_emergency(norm):
        # The one message that must arrive, so it asks the service afresh rather
        # than trusting an answer up to 30 seconds old: a stale "opted out" must
        # not swallow it. A member who really is opted out cannot be answered
        # from this number, which is worth a loud line because a person may want
        # to reach them another way.
        if _is_opted_out(phone, ph, fresh=True):
            print(
                "OPTED OUT: EMERGENCY LANGUAGE in a message from a member on the opt-out list; "
                "the service refuses sends to this number, so the fixed reply was not sent. "
                "A care advocate should look at this thread now"
            )
            c.log_indicator(ph, "OPTED_OUT_SKIPPED")
        else:
            _handle_emergency(phone, ph, live)
        return True

    keyword = parsed.get("keyword", "")
    if keyword and not _keyword_matches_text(keyword, norm):
        print(f"IGNORED messageKeyword {keyword[:30]!r}: the message does not begin with it, so it is routed as ordinary text")
        keyword = ""
    family = _service_keyword_family(keyword, norm)
    if family:
        _handle_service_keyword(ph, family, keyword)
        return True

    if _is_opted_out(phone, ph):
        _skip_opted_out(ph, _OPTED_OUT_SENT["freetext"])
        return True

    word = norm[: -len(" please")] if norm.endswith(" please") else norm
    if word in _MENU_ESCAPES:
        # Same effect as tapping Start Over, including leaving live mode: a
        # member stuck in a thread nobody is staffing has no chip to tap if the
        # card that held it has scrolled away.
        print(f"TYPED RESET {word!r}{' (was live)' if live else ''}")
        reset_conversation(phone, ph)
        return True
    if word in _HUMAN_ESCAPES and not live:
        # While live a human already has the thread, and the bot stays quiet.
        c.set_mode(ph, "live")
        _send(phone, ph, handover.escalate_card())
        return True
    return False


# The keyword router's intents, tried in this order by handle_freetext.
_ROUTE_HANDOVER = re.compile(r"\b(?:agents?|humans?|persons?|representatives?|advocates?|someones?)\b")
_ROUTE_RX = re.compile(r"\b(?:refill(?:s|ed|ing)?|prescriptions?|rx|medications?|pharmacy)\b")
_ROUTE_APPT = re.compile(r"\b(?:appointments?|(?:re)?schedule[sd]?|doctors?|visit(?:s|ed|ing)?)\b")
_ROUTE_STORE = re.compile(r"\b(?:shop(?:s|ped|ping)?|stores?|buy(?:s|ing)?|carts?|order(?:s|ed|ing)?|products?)\b")
_ROUTE_VERIFY = re.compile(r"\b(?:verify|verifying|codes?|logins?|log in(?:to)?|sign in|otp)\b")
_ROUTE_FIND = re.compile(r"\b(?:find(?:s|ing)?|providers?|specialists?|urgent care|near|nearby|nearest)\b")

# (pattern, vignette) in match order. Handover is universal; the rest open only
# for a brand that owns the vignette (common.vignette_allowed).
_INTENTS = [
    (_ROUTE_HANDOVER, "handover"),
    (_ROUTE_RX, "rx_refill"),
    (_ROUTE_APPT, "appt_reminder"),
    (_ROUTE_STORE, "store"),
    (_ROUTE_VERIFY, "verification"),
    (_ROUTE_FIND, "find_care"),
]


def handle_freetext(phone, ph, text):
    active = c.get_active_flow(ph)
    keyword = _normalize_keyword(text)

    # The configured deep-link keyword always resets to the carousel: it's a
    # deliberate "start here" scan, so honouring it mid-flow is the point. A
    # generic greeting only does so when no flow is active, otherwise typing
    # "hi" at the AI assistant would silently abandon the conversation.
    if keyword == _normalize_keyword(c.deep_link_keyword()) or (keyword in _GREETING_KEYWORDS and not active):
        c.set_active_flow(ph, "welcome")
        _send(phone, ph, welcome.on_start(phone, ph))
        return

    if active == "verification":
        _send(phone, ph, otp.verify(phone, ph, text))
        return
    if active in AI_DRIVEN_VIGNETTES:
        # Room Booking turns go through _booking_reply, which merges the
        # property's photo and Open Map into the assistant's reply (design C9).
        # The other AI vignettes keep the plain path.
        if active == "room_booking":
            # A plain "yes" / "confirm it" while the latest message offers
            # Confirm Booking is the same as tapping it (design C11).
            if _is_typed_confirmation(text) and _offers_confirm(ph):
                print("TYPED CONFIRM: handled as booking_confirm")
                handle_postback(phone, ph, "booking_confirm")
                return
            _booking_reply(phone, ph, text)
            return
        send_ai_response(phone, ph, invoke_ai(ph, text, active))
        return
    if active == "store":
        _send(phone, ph, get_flow("store").on_start(phone, ph))
        return
    # A deterministic flow that asked a question can read a typed answer
    # (on_freetext, which uses common.ai_extract and checks the result in code).
    # It returns messages when the text answered its question, else None, and
    # then the text goes on to the intents and the brand assistant as before.
    flow = get_flow(active) if active and _allowed(active) else None
    on_freetext = getattr(flow, "on_freetext", None) if flow else None
    if on_freetext:
        try:
            messages = on_freetext(phone, ph, text)
        except Exception as e:  # noqa: BLE001 - a hook bug must not drop the turn
            print(f"FREETEXT HOOK {active} failed ({c.error_code(e)}); routing as ordinary text")
            messages = None
        if messages:
            _send(phone, ph, messages)
            return

    # Intent keywords, matched as whole words (with the inflections a member
    # would plausibly type) rather than as substrings: "order" must not fire
    # inside "disorder", nor "person" inside "personal".
    words = _match_text(text)
    # An intent whose vignette the selected brand does not own is skipped, not
    # an error: the next intent is tried, then the brand's default route.
    for pattern, vkey in _INTENTS:
        if not pattern.search(words) or not _allowed(vkey):
            continue
        if vkey == "handover":
            c.set_mode(ph, "live")
            _send(phone, ph, handover.escalate_card())
        elif vkey == "find_care":
            c.set_active_flow(ph, "find_care")
            send_ai_response(phone, ph, invoke_ai(ph, text, "find_care"))
        else:
            c.set_active_flow(ph, vkey)
            _send(phone, ph, get_flow(vkey).on_start(phone, ph))
        return

    _default_route(phone, ph, text)


def _default_route(phone, ph, message):
    """An inbound turn nothing else claimed (`message` is the typed text, or the
    tap description for an unclaimed tap): the selected brand's `defaultVignette`
    when it is an AI vignette the brand owns, else the brand's Home_Menu."""
    dv = c.default_vignette()
    if dv in AI_DRIVEN_VIGNETTES and _allowed(dv):
        c.set_active_flow(ph, dv)
        if dv == "room_booking":
            # A new booking session starts clean, as the Room Booking tile does.
            c.set_booking_carded_property(ph, "")
            c.set_booking_context(ph, "")
            c.set_booking_quote(ph, {})
            c.set_booking_offer(ph, "")
            _booking_reply(phone, ph, message)
        else:
            send_ai_response(phone, ph, invoke_ai(ph, message, dv))
        return
    _send(phone, ph, welcome.home_menu(phone, ph))


# ── Dashboard push (triggers, direct sends, live-agent replies) ─────────────
def handle_push(p):
    phone = p.get("phone", "")
    ph = c.hash_phone(phone)
    if p.get("vignette"):
        handle_trigger(phone, ph, p["vignette"])
    elif p.get("agent_message") is not None:
        text = str(p["agent_message"])[: c.rcs_limit("textBodyChars")]
        # Default the live-agent label to the brand's own role (title-cased),
        # e.g. "Booking Concierge" for AnyTravel, when the dashboard sends no explicit name.
        agent = p.get("agent") or c.live_agent_role().title()
        c.set_mode(ph, "live")
        msg = {"Content": {"TextMessage": {"Body": text}}}
        c.send_rcs(phone, msg)
        c.log_message(ph, "outbound", text, rcs_content=msg, actor=agent)
    elif p.get("visit_token"):
        # The video visit is the one flow whose card the dashboard cannot build
        # itself, even though it owns the token. Every webview link comes from
        # c.webview_url(), which needs API_BASE_URL — injected on *this* function
        # only, because setting it on the dashboard would close a CloudFormation
        # cycle (the dashboard is the HTTP API's integration target). In the
        # dashboard the same call yields a relative "/webview/…", and RcsOpenUrl
        # requires an absolute https:// URL, so the send fails validation with an
        # empty url and nothing reaches the handset.
        #
        # So the split is: the dashboard mints the token (it has to — the operator
        # console needs it to join the same Chime meeting), and the card is built
        # here, where the public base URL is known.
        _send(phone, ph, video_visit.invite(p["visit_token"]))
    elif p.get("rcs_content"):
        c.send_rcs(phone, p["rcs_content"])
        c.log_message(ph, "outbound", _summarize(p["rcs_content"]), rcs_content=p["rcs_content"])


# ── Shared location (RequestLocation round trip) ────────────────────────────
# The other half of a RequestLocation suggestion. A member tapping "Share My
# Location" sends back a messageBody of {"type":"LOCATION","latitude":...,
# "longitude":...} — coordinates only, no street address and no place name, so
# any human-readable location is your own reverse geocode. There is no
# guarantee the member ever taps it, which is why the find-care prompt keeps
# asking for a city in words as well.
#
# https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-suggestions.html#rcs-suggestions-requestlocation
def _location_label(latitude, longitude):
    try:
        return f"[Location shared: {float(latitude):.3f}, {float(longitude):.3f}]"
    except (TypeError, ValueError):
        return "[Shared location]"


def handle_location(phone, ph, latitude, longitude):
    try:
        lat, lon = float(latitude), float(longitude)
    except (TypeError, ValueError):
        # Do not log the coordinate values themselves — shared GPS coordinates
        # are location PII (precise enough to identify a home). The values aren't
        # needed to debug this parse failure; that they were unparseable is.
        print("inbound LOCATION with unusable coordinates — skipping")
        return
    # Already logged by process_inbound, which logs every inbound message once
    # before routing anything — including while a human has the conversation,
    # in which case process_inbound returns before reaching here and the
    # coordinates simply appear in the Care Advocate's transcript.
    # A location shared during Delivery Location is the answer to its "where did
    # you leave it?" prompt: it becomes the load's new drop spot.
    if c.get_active_flow(ph) == "delivery_location" and _allowed("delivery_location"):
        _send(phone, ph, get_flow("delivery_location").location_update(ph, lat, lon))
        return
    # The same for Bag Tracking's Share Delivery Spot: the location is where to
    # deliver the delayed bag.
    if c.get_active_flow(ph) == "bag_tracking" and _allowed("bag_tracking"):
        _send(phone, ph, get_flow("bag_tracking").location_update(ph, lat, lon))
        return
    # Finding care is a Provider-directory flow: a brand that does not own it
    # answers a shared location with its own Home_Menu and opens nothing.
    if not _allowed("find_care"):
        _foreign_to_menu(phone, ph, "LOCATION", "find_care")
        return
    c.set_active_flow(ph, "find_care")
    send_ai_response(phone, ph, invoke_ai(
        ph,
        f"The member shared their location: latitude {lat:.3f}, longitude {lon:.3f}. "
        "Use it only to say which of the directory's locations is likely nearest, and ask them "
        "to confirm the city if the directory has nothing close.",
        "find_care",
    ))


# ── Inbound media (native RCS photo/file submission) ────────────────────────
# Demonstrates receiving member-submitted media directly in the RCS thread.
# Deliberately paired with a generic, non-sensitive use case (classify any
# photo) rather than a document likely to carry PII/PHI — this path sends the
# raw bytes across the public carrier/RCS network, which is why the
# compliance-forward alternative (webview upload, see lambda/media_convert.py)
# exists for anything that could carry PII/PHI. See the dashboard's PII/PHI
# guidance tooltip for the full explanation shown to demo viewers.
# Native RCS media is first written by EUM to inbound/rcs/. Every browser-
# renderable photo and iPhone HEIC/HEIF is normalized asynchronously by
# media_convert before the dashboard or bot confirmation renders it.
# Shared with the dashboard's pending-state logic (common.media_conversion_
# pending), so "the converter will handle this" means one thing in both places.
_NATIVE_CONVERTIBLE_IMAGE_MIME_TYPES = c.CONVERTIBLE_IMAGE_MIME_TYPES


def _needs_native_conversion(parsed):
    media = parsed.get("media", {}) if parsed.get("type") == "media" else {}
    return (
        media.get("mediaStatus") == "SUCCESS"
        and bool(media.get("s3Key"))
        and media.get("mimeType", "").lower() in _NATIVE_CONVERTIBLE_IMAGE_MIME_TYPES
    )


def handle_native_media_ready(payload):
    """Receive media_convert's asynchronous native-photo completion callback.
    Conversion has already replaced the raw media metadata in DynamoDB; in
    bot mode this sends the ordinary rich confirmation card using the new JPEG.
    In live mode the one-line receipt was already sent, so only the dashboard
    changes — the bot must not interrupt the care advocate."""
    phone = payload.get("phone", "")
    phone_hash = payload.get("phone_hash", "")
    media = payload.get("media") or {}
    if not phone or not phone_hash or not media:
        print("native media callback missing phone, phone_hash, or media")
        return
    if c.get_mode(phone_hash) == "live":
        return
    # The photo was logged when it arrived, and the member may have texted STOP
    # while it converted: the confirmation card would be refused.
    if _is_opted_out(phone, phone_hash):
        _skip_opted_out(phone_hash, "a converted photo")
        return
    classification = payload.get("classification", "")
    # A photo sent during Site Evidence is logged against the ticket the sender
    # opened, and the evidence card replaces the generic receipt. Any other photo
    # just gets the receipt card.
    if c.get_active_flow(phone_hash) == "site_evidence" and _allowed("site_evidence"):
        _send(phone, phone_hash, site_evidence.media_messages(phone_hash, media, classification))
        return
    _send(phone, phone_hash, _media_received_card(media, classification))


def _media_processing_ack():
    return [{"Content": {"TextMessage": {"Body": "✅ Picture received — preparing your preview."}}}]


def handle_media(phone, ph, media):
    """Bot reply for native inbound media that does NOT enter the JPEG
    conversion pipeline — a failed upload, or a non-image file (PDF, audio,
    video). The inbound media itself is already logged by process_inbound,
    before the live-mode check, so this only builds the reply card.

    Nothing is classified here. Every mime type that could be classified is a
    convertible image, and process_inbound routes those to media_convert (which
    classifies from the normalized JPEG and calls back into
    handle_native_media_ready). This function used to hold a second copy of the
    classification call for image/jpeg|jpg|gif|png — a strict subset of
    _NATIVE_CONVERTIBLE_IMAGE_MIME_TYPES — so that branch was unreachable, and
    its prompt had already drifted from the live one in media_convert._classify.
    Do not reintroduce it: put prompt changes in media_convert only.
    """
    if media.get("mediaStatus") != "SUCCESS":
        _send(phone, ph, _media_failure_card(media, ph))
        return
    # A video sent during Site Evidence is logged against the open ticket. The
    # service accepts video, but the converter only handles images, so there is
    # no preview and no description to add.
    if c.get_active_flow(ph) == "site_evidence" and _allowed("site_evidence"):
        _send(phone, ph, site_evidence.media_messages(ph, media))
        return
    _send(phone, ph, _media_received_card(media, classification=""))


def _media_failure_card(media, phone_hash):
    mime_type = media.get("mimeType", "")
    status = media.get("mediaStatus", "UNKNOWN")
    heic_hint = ""
    if "heic" in mime_type.lower() or "heif" in mime_type.lower():
        heic_hint = (
            "\n\nLooks like that came from an iPhone in HEIC format, which this "
            "channel doesn't accept directly. Turn on Settings > Camera > "
            "Formats > \"Most Compatible\" to send JPEG next time — "
            "or use the secure upload link below, which converts it for you."
        )
    body = (
        f"We couldn't process that file ({status}).{heic_hint}"
        if heic_hint else
        f"We couldn't process that file: {media.get('mediaStatusMessage', status)}. "
        "Try a JPEG or PNG under 50 MB, or use the secure upload link below."
    )
    return [{
        "Content": {"TextMessage": {"Body": body}},
        "Suggestions": [
            {"OpenUrl": {
                "Text": "Secure Upload", "PostbackData": "photo_secure_upload",
                "Url": c.webview_url("upload-insurance-card", ph=phone_hash),
                "Application": "WEBVIEW", "WebviewViewMode": "TALL",
            }},
        ],
    }]


def _media_receipt_ack():
    """Minimal one-line receipt for a photo received while a human has the
    thread (live mode) — just enough to confirm it arrived, without the
    bot's full confirmation card/classification, which would look like the
    bot butting into a live conversation."""
    return [{"Content": {"TextMessage": {"Body": "✅ Picture received."}}}]


def _media_received_card(media, classification=""):
    file_name = media.get("fileName", "your file")
    size_kb = int(media.get("fileSizeBytes", 0)) // 1024
    description = f"{file_name} ({size_kb} KB)"
    if classification:
        description += f"\n\nWhat we see: {classification}"
    # Prefer the normalized JPEG created by media_convert. Raw HEIC remains
    # stored for audit/debugging, but it is not generally renderable by RCS
    # clients or browsers.
    media_key = media.get("convertedS3Key") or media.get("s3Key", "")
    mime_type = str(media.get("mimeType", "")).lower()
    # Only an image is shown as the card's picture. A video, audio file or PDF
    # is receipted as text: the converter does not process them, and the card
    # media field is for images.
    is_image = bool(media.get("convertedS3Key")) or mime_type.startswith("image/")
    card = {
        "Title": "Photo Received" if is_image else "File Received",
        "Description": description,
    }
    if media_key and is_image:
        card["Media"] = {"FileUrl": c.inbound_media_url(media_key), "Height": "MEDIUM"}
    return [{
        "Content": {"RichCard": {"CardOrientation": "VERTICAL", "CardContent": card}},
    }]


# ── Bedrock AI assistant ────────────────────────────────────────────────────
def _member_ctx(phone_hash):
    """Member facts injected into the AI system prompt. The name comes from the
    Recipients tab so the assistant greets the person actually holding the
    phone; brand.md's memberName is only the fallback (dashboard previews, or a
    recipient with no name set). The plan, masked id and city are the selected
    brand's own sample profile in brand.md; a field the brand leaves empty is
    skipped, so the line never carries an empty "Plan: ," entry."""
    b = c.brand()
    parts = [f"Member: {c.tester_name(phone_hash, fallback=c.member_name())}"]
    for label, key in (("Plan", "memberPlan"), ("Member ID", "memberIdMasked"),
                       ("Location", "memberCity")):
        value = b.get(key)
        value = str(value).strip() if value is not None else ""
        if value:
            parts.append(f"{label}: {value}")
    return ", ".join(parts) + "."


def _json_contract():
    # The model has no clock: without today's date it wrote a past year into a
    # calendar event. Evaluated per call (never at import) so a warm Lambda
    # container does not carry a stale date across midnight.
    today = datetime.now(timezone.utc).date().isoformat()
    return (
        f'TODAY: {today} (UTC).\n'
        'Resolve a date the guest gives without a year to its next occurrence on or '
        'after today. Never write a date before today into a stay summary, appointment '
        'or calendar event; if the guest asks for a date in the past, ask for a date '
        'from today on.\n'
        'RULES:\n'
        '1. Return EXACTLY ONE valid JSON object. No markdown, no preamble.\n'
        '2. text: {"type":"text","body":"...","suggestions":[...]}; '
        'rich card: {"type":"rich_card","title":"...","description":"...","suggestions":[...]}.\n'
        '3. EVERY response includes suggestions. Max 4, each text under 25 chars.\n'
        f'4. Always include {{"type":"dial","text":"{c.call_label()}","phone_number":"{c.member_services_phone()}"}}. '
        'The app adds a Start Over chip itself, so do NOT add any menu, home or '
        'start-over chip of your own.\n'
        '5. If the member wants a human, include '
        '{"type":"reply","text":"Talk to a Person","postback":"handover_start"}.\n'
        '6. Prefer text; use rich_card only for structured info. Use everyday language.\n'
        '7. body/title/description are shown as PLAIN TEXT on the phone. Never use '
        'markdown: no **bold**, *italic*, `code`, # headings, or [links](url). '
        'For a list, put each item on its own line starting with "- ".'
    )


def _brand_grounding():
    """The selected brand's grounding bundle for the AI system prompt: who the
    assistant is (brand display name + line of business, read from the source of
    truth — never a literal) and the brand's own grounding content (the bodies
    of its groundingFiles). There is one deployed agent, so the brand is simply
    the selected one; no per-conversation brand attribute and no inbound
    agent→brand mapping are needed (design §2). The brand name the model sees
    comes straight from common's accessors, so swapping BRAND swaps the whole
    bundle with no code change (R7.1, R7.3, R7.4)."""
    lob = c.line_of_business()
    who = f"You are {c.brand_display_name()}, a virtual assistant over RCS."
    if lob:
        who += f"\nLine of business: {lob}"
    return f"{who}\n\nUse ONLY this knowledge about {c.brand_display_name()}:\n{c.grounding_content()}"


def _benefits_prompt(phone_hash):
    return (f"{_brand_grounding()}\n{_member_ctx(phone_hash)}\n\n{_json_contract()}")


def _find_care_prompt(phone_hash):
    # The extra rule is what makes RequestLocation reachable: finding a provider
    # is the one vignette where the member's own position is the missing input,
    # and RCS can ask the handset for it instead of asking the member to type a
    # postcode. handle_location receives the answer. Both prompts share the one
    # brand grounding bundle (the selected brand's identity + its grounding
    # files); this one adds the share-location rule on top.
    return (f"{_brand_grounding()}\n{_member_ctx(phone_hash)}\n\n{_json_contract()}\n"
            '7. When you do not yet know where the member is, include exactly one '
            '{"type":"share_location","text":"Share My Location"} '
            "suggestion so their phone can offer to send it. Drop it once you know their location, "
            "and never ask twice in a row.")


# ── Brand assistants ────────────────────────────────────────────────────────
# One grounded assistant per brand (other than AnyHealth, whose Benefits Q&A
# plays this part) answers typed text that no flow claims. Each sees the brand's
# grounding prose plus its FACTS block (common.assistant_facts: the frontmatter
# data with every date resolved), and offers the brand's own Home_Menu tiles as
# reply chips when the user wants to DO something. Actions stay in the
# deterministic flows; the assistant explains and hands off.
#
# `start` is the instruction for the first turn (a tile tap or a dashboard
# trigger); `tile` is the assistant's own Home_Menu postback, left out of the
# chips it may offer; `rules` are the brand's own limits.
_ASSISTANTS = {
    "trip_assistant": {
        "tile": "home_ask_trip",
        "start": "The traveler opened the trip assistant. Greet them in one short sentence and "
                 "say you can answer questions about their flights, bags and hotel stays.",
        "rules": "You cannot check in, change seats, rebook, book rooms or arrange bag delivery "
                 "yourself: offer the matching feature chip. For a hotel booking request, offer "
                 '"Book a Room". Never state a flight time, gate, seat or price that is not in the FACTS.',
    },
    "account_assistant": {
        "tile": "home_ask_account",
        "start": "The member opened the account assistant. Greet them in one short sentence and "
                 "say you can explain their account, recent charges and loan documents.",
        "rules": "You can only explain. You cannot move money, freeze or unfreeze a card, dispute a "
                 "charge or change anything: for the flagged charge offer the Fraud Alert chip, and "
                 "offer Talk to a Person for anything else that needs action. Never ask for or repeat "
                 "a full card or account number, a PIN, a password or a one-time code, and never say "
                 "a charge is or is not fraud: say what the alert says and who can help.",
    },
    "hr_assistant": {
        "tile": "home_ask_hr",
        "start": "The employee opened the HR assistant. Greet them in one short sentence and say "
                 "you can answer questions about their shifts, time off and coworkers' open shifts.",
        "rules": "You cannot approve or submit time off, swap shifts or clock anyone in: offer the "
                 "matching feature chip. Do not give legal, payroll or benefits advice that is not in "
                 "the FACTS; offer Talk to a Person instead.",
    },
    "jobsite_assistant": {
        "tile": "home_ask_site",
        "start": "The user opened the jobsite assistant. Greet them in one short sentence and say "
                 "you can answer questions about the crew plan, deliveries and what's ready on the lot.",
        "rules": "You cannot confirm crew, mark work done, schedule trades or log evidence yourself: "
                 "offer the matching feature chip. If someone reports an injury or an unsafe "
                 "condition, tell them to stop work and call 911 for an injury, then offer Talk to a "
                 "Person.",
    },
}


def _assistant_prompt(phone_hash, vignette):
    a = _ASSISTANTS[vignette]
    tiles = [t for t in c.home_menu() if t["postback"] != a["tile"]]
    tile_lines = "\n".join(
        f'- {{"type":"reply","text":"{t["label"]}","postback":"{t["postback"]}"}}' for t in tiles
    )
    facts = c.assistant_facts()
    return (
        f"{_brand_grounding()}\n\n{facts}\n\n{_member_ctx(phone_hash)}\n\n{_json_contract()}\n"
        "8. FACTS: answer only from the FACTS and the knowledge above. Quote names, dates, times, "
        "gates and amounts exactly as written. If the answer is not there, say you don't have it and "
        "offer Talk to a Person. Never guess or estimate.\n"
        "9. You answer questions; you do not carry out actions. Never say or imply that you have "
        "recorded, scheduled, proposed, sent or changed anything. When the user wants to do something "
        "one of the app's features does, say so in one sentence and offer that feature as a chip, "
        "copied exactly from this list:\n"
        f"{tile_lines}\n"
        f"10. {a['rules']}\n"
        "11. Keep a reply under 450 characters unless the user asks for detail."
    )


def _ai_start(vignette):
    """The first-turn instruction for an AI vignette opened by a tile or trigger."""
    a = _ASSISTANTS.get(vignette)
    if a:
        return a["start"]
    return f"The member just started the {vignette} flow. Greet them briefly and offer help."


def _room_booking_prompt(phone_hash):
    # Room Booking shares the brand grounding + member context + JSON contract,
    # then overrides/extends it with booking-specific rules:
    #  - Rule 8 overrides contract rule 4: Room Booking does NOT force the brand's
    #    call chip (c.call_label()). On a property reply the guest wanted the
    #    map to be the primary action, not competing with a greyed-out Call chip
    #    in an overflow menu. Call stays available only if the guest asks for a
    #    human (contract rule 5 / handover).
    #  - Rule 9 keeps the map off conversational replies: _booking_reply merges
    #    the Property_Card's own "Open Map" action into the reply, so a second AI
    #    map chip would duplicate it. The map appears again only on the final
    #    confirmation card (booking_confirm turn).
    #  - Rules 8 and 9 are guidance only: room_booking_cards.apply_property_card
    #    drops every dial and view_location chip from conversational replies in
    #    code (R15.10), so a model that ignores them leaks neither.
    #  - Rule 11 pins the Confirm Booking postback to the exact id
    #    `booking_confirm`; the model otherwise invents ids (confirm_booking),
    #    which skipped the confirmation rich card. BOOKING_CONFIRM_ALIASES also
    #    catches stray variants in handle_postback.
    #  - Rule 10 is memory: the earlier turns already contain what the guest has
    #    given (city, dates, guests); reuse them and never re-ask.
    prompt = (f"{_brand_grounding()}\n{_member_ctx(phone_hash)}\n\n{_json_contract()}\n"
            f'8. OVERRIDE of rule 4 for booking: do NOT add a "{c.call_label()}" dial '
            'chip to booking replies. Add "Talk to a Person" only if the guest asks for a '
            'human (rule 5).\n'
            '9. Do NOT add a map or view_location chip to conversational booking replies: '
            'the guest already receives a property card with its own Open Map button. Only '
            'the final confirmation card includes a map action.\n'
            '10. MEMORY: the earlier turns in THIS conversation already contain the details '
            "the guest has given — city or property, dates, and number of guests. Reuse them "
            "and NEVER ask again for a detail the guest has already provided. Ask only for "
            "what is still missing, then summarize and offer Confirm Booking.\n"
            '11. To offer confirmation, use EXACTLY this suggestion: '
            '{"type":"reply","text":"Confirm Booking","postback":"booking_confirm"}. '
            "Never invent another postback for confirming.\n"
            "12. RATES: quote a nightly rate ONLY from the RATE TABLE below. Never write a "
            "total, or a rate you computed yourself, that is not in the table. Whenever the "
            "property, room, check-in and check-out dates and guest count are ALL known and "
            "you present or re-present the stay for confirmation, add a top-level field "
            '"quote" to the JSON reply: {"property_id":"<id from the table>",'
            '"room_id":"<king|double|suite id>","check_in":"YYYY-MM-DD",'
            '"check_out":"YYYY-MM-DD","guests":<number>}. Use the ids exactly as they '
            "appear in the table and ISO dates (use TODAY to resolve a missing year). Keep "
            'including "quote" in every reply while that stay is pending, and omit it when '
            "no complete stay is known. The app replaces your summary text with the exact "
            "numbers, so keep your own wording short and do not repeat rates or totals.\n"
            "13. ROOM TYPES: when you ask which room the guest wants, offer the room types as "
            "reply chips named EXACTLY as the room names in the ROOMS line of the rate table below, one "
            "chip per room type; the app turns those chips into a photo carousel. Do not describe room "
            "photos or say that photos are attached.")
    # Offer details chosen by the Travel Offers handoff, kept for the whole
    # booking so they stay in the prompt after the handoff turn falls out of
    # the history window.
    chosen = c.booking_context(phone_hash)
    if chosen:
        prompt += ("\nDETAILS ALREADY CHOSEN FOR THIS BOOKING (from the travel offer the guest "
                   "selected; treat them as given and do NOT ask for them again):\n" + chosen)
    # Rate table generated from content/hotels.md, so the model sees exactly the
    # ids and rates the code will charge (design C14).
    table_text = room_booking_quote.rate_table_text()
    if table_text:
        prompt += "\n\n" + table_text
    return prompt


# An outbound row's `body` is only a short summary such as "[Card: <title>]".
# The assistant needs what the guest actually saw (dates, room, price, chips),
# so each earlier turn is rebuilt from the stored `rcs_content`, capped here.
_TURN_TEXT_CHARS = 1500
_TAP_PREFIX = "[Tap] "
_CHIP_KINDS = ("Reply", "DialPhone", "ShowLocation", "OpenUrl",
               "CreateCalendarEvent", "RequestLocation")


def _load_rcs_content(row):
    """The row's rcs_content as a dict, or None when missing or unreadable."""
    raw = (row or {}).get("rcs_content")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
    return raw if isinstance(raw, dict) and raw else None


def _chips_of(holder):
    """(label, postback) for each chip in holder['Suggestions'], in order."""
    out = []
    suggestions = holder.get("Suggestions") if isinstance(holder, dict) else None
    for chip in suggestions if isinstance(suggestions, list) else []:
        if not isinstance(chip, dict):
            continue
        for kind in _CHIP_KINDS:
            inner = chip.get(kind)
            if isinstance(inner, dict):
                label = str(inner.get("Text") or "").strip()
                if label:
                    out.append((label, str(inner.get("PostbackData") or "")))
                break
    return out


def _content_parts(rcs):
    """(texts, chips) of a sent RCS message: message, rich card and carousel level."""
    content = rcs.get("Content")
    content = content if isinstance(content, dict) else {}
    texts, chips = [], []

    def card(cc):
        if not isinstance(cc, dict):
            return
        for key in ("Title", "Description"):
            if cc.get(key):
                texts.append(str(cc[key]))
        chips.extend(_chips_of(cc))

    text = content.get("TextMessage")
    if isinstance(text, dict) and text.get("Body"):
        texts.append(str(text["Body"]))
    rich = content.get("RichCard")
    if isinstance(rich, dict):
        card(rich.get("CardContent"))
    carousel = content.get("Carousel")
    if isinstance(carousel, dict):
        for cc in carousel.get("CardContents") or []:
            card(cc)
    chips.extend(_chips_of(rcs))
    return texts, chips


def _row_chips(row):
    """postback -> label for every chip on an outbound row (all chip levels)."""
    rcs = _load_rcs_content(row)
    if not rcs:
        return {}
    return {pb: label for label, pb in _content_parts(rcs)[1] if pb}


def _turn_text(row, previous_chips):
    """The text the assistant sees for one earlier turn (R16.1-R16.4)."""
    row = row or {}
    body = row.get("body", "") or ""
    text = body
    if row.get("direction") == "outbound":
        rcs = _load_rcs_content(row)
        if rcs:
            texts, chips = _content_parts(rcs)
            labels = list(dict.fromkeys(label for label, _ in chips))
            if texts or labels:
                main = "\n".join(texts)
                options = f"Options offered: {', '.join(labels)}" if labels else ""
                if len(main) + len(options) + 1 > _TURN_TEXT_CHARS and options \
                        and len(options) < _TURN_TEXT_CHARS:
                    # Over the cap: shorten the prose, keep the chips visible.
                    main = main[:max(0, _TURN_TEXT_CHARS - len(options) - 1)]
                text = "\n".join(p for p in (main, options) if p)
    elif body.startswith(_TAP_PREFIX):
        tapped = body[len(_TAP_PREFIX):].strip()
        label = (previous_chips or {}).get(tapped)
        if tapped.startswith(room_booking_rooms.PICK_PREFIX):
            # Every Room_Carousel card carries the same "Choose" label, so name
            # the room: later turns must still show which one the guest picked.
            room = c.room_type_by_id(tapped[len(room_booking_rooms.PICK_PREFIX):])
            if room and room.get("name"):
                label = f"Choose {room['name']}"
        if label:
            text = f'Tapped "{label}"'
    return text[:_TURN_TEXT_CHARS]


# Whole-message affirmatives that count as a tap on Confirm Booking when the
# latest message offers that chip (design C11, R17). _match_text drops
# apostrophes, so "that's right" normalises to "thats right"; both are listed.
_CONFIRM_PHRASES = frozenset({
    "yes", "yep", "yeah", "y", "sure", "ok", "okay", "confirm", "confirm it",
    "confirm booking", "confirm the booking", "yes confirm", "yes confirm it",
    "yes please confirm", "book it", "yes book it", "go ahead", "do it",
    "sounds good", "looks good", "perfect", "that's right", "thats right",
    "correct",
})


def _is_typed_confirmation(text):
    """True when the whole message is a plain affirmative (R17.1). Anything
    extra ("yes but make it three nights", "no", "change the dates") is not."""
    norm = _match_text(text)
    if norm.endswith(" please"):
        norm = norm[:-len(" please")].strip()
    return norm in _CONFIRM_PHRASES


def _offers_confirm(ph):
    """True when the newest outbound message carries a Confirm Booking chip,
    under its real id or one of BOOKING_CONFIRM_ALIASES (R17.3)."""
    rows = c.history_since_reset(c.conversation_history(ph, limit=10))
    for row in reversed(rows):
        if isinstance(row, dict) and row.get("direction") == "outbound":
            chips = _row_chips(row)
            return "booking_confirm" in chips or any(pb in BOOKING_CONFIRM_ALIASES for pb in chips)
    return False


def invoke_ai(ph, user_message, vignette):
    if vignette == "find_care":
        system = _find_care_prompt(ph)
    elif vignette == "room_booking":
        system = _room_booking_prompt(ph)
    elif vignette in _ASSISTANTS:
        system = _assistant_prompt(ph, vignette)
    else:
        system = _benefits_prompt(ph)

    # A Reset writes a CONVERSATION_RESET marker row; history_since_reset keeps
    # only the rows after the newest one, so a Reset gives the assistant an empty
    # memory (R4.3) without deleting anything from the stored transcript.
    #
    # Keep the last N real *turns*, not the last N rows. conversation_history
    # returns the most recent MSG# rows of any direction, which in a live thread
    # includes `event` rows (RCS_TYPING, delivery/read receipts). Those are not
    # conversation turns, so counting rows let typing/delivery events crowd the
    # genuine turns out of a small window — the model stopped seeing the message
    # where the guest named their city and re-asked for it. So pull a wider slice,
    # drop event rows, then keep the most recent real turns. This gives the model
    # the actual back-and-forth (city, dates, guests) regardless of how many
    # ephemeral events interleaved.
    _MAX_TURNS = 12
    turns = [
        m for m in c.history_since_reset(c.conversation_history(ph, limit=40))
        if m.get("direction") in ("inbound", "outbound")
    ][-_MAX_TURNS:]
    # Each turn is rebuilt from what was actually sent (_turn_text), not the
    # stored one-line summary, so the model sees the dates, room, price and chips
    # it offered earlier; previous_chips resolves "[Tap] <postback>" to its label.
    messages = []
    previous_chips = {}
    for m in turns:
        role = "user" if m.get("direction") == "inbound" else "assistant"
        messages.append({"role": role, "content": [{"text": _turn_text(m, previous_chips)}]})
        if role == "assistant":
            previous_chips = _row_chips(m)
    messages.append({"role": "user", "content": [{"text": user_message}]})

    # Bedrock Converse requires alternating roles starting with user.
    merged = []
    for m in messages:
        if merged and merged[-1]["role"] == m["role"]:
            merged[-1]["content"][0]["text"] += "\n" + m["content"][0]["text"]
        else:
            merged.append(m)
    while merged and merged[0]["role"] != "user":
        merged.pop(0)

    try:
        bedrock = boto3.client("bedrock-runtime", region_name=c.BEDROCK_REGION)
        resp = bedrock.converse(
            modelId=c.BEDROCK_MODEL_ID,
            system=[{"text": system}],
            messages=merged,
            inferenceConfig={"maxTokens": 500, "temperature": 0.3},
        )
        return parse_ai_response(resp["output"]["message"]["content"][0]["text"])
    except Exception as e:  # noqa: BLE001
        # The error code and the model, not the exception text: a Bedrock SDK
        # error can echo the request, which holds the member's message and the
        # conversation so far. The code with the model and Region is enough to
        # tell an access problem from a model this Region does not offer.
        print(f"AI invocation failed ({c.error_code(e)}) for model {c.BEDROCK_MODEL_ID} in {c.BEDROCK_REGION}")
        return {
            "type": "text",
            "body": "I'm having trouble right now — let me connect you with a team member.",
            "suggestions": [
                {"type": "reply", "text": "Talk to a Person", "postback": "handover_start"},
            ],
        }


def parse_ai_response(raw):
    for candidate in (raw, raw[raw.find("{"): raw.rfind("}") + 1] if "{" in raw else ""):
        try:
            data = json.loads(candidate)
            if isinstance(data, dict) and "type" in data:
                return data
        except (json.JSONDecodeError, TypeError):
            continue
    return {
        "type": "text",
        "body": c.strip_markdown(raw)[: c.rcs_limit("textBodyChars")],
        "suggestions": [],
    }


def send_ai_response(phone, ph, data, reset_chip=True):
    """Send the assistant's reply. `reset_chip=False` leaves the Start Over chip
    off, for a reply that a message carrying its own chip follows (R21.11)."""
    msg_type = data.get("type", "text")
    if msg_type == "rich_card":
        card = {}
        if data.get("title"):
            card["Title"] = c.strip_markdown(data["title"])[: c.rcs_limit("richCardTitleChars")]
        if data.get("description"):
            card["Description"] = c.strip_markdown(data["description"])[: c.rcs_limit("richCardDescriptionChars")]
        if data.get("image"):
            card["Media"] = {"FileUrl": c.resolve_media(data["image"]), "Height": data.get("media_height", "MEDIUM")}
        card_sugg = c.build_suggestions(data.get("suggestions", []), max_count=4)
        if card_sugg:
            card["Suggestions"] = card_sugg
        content = {"Content": {"RichCard": {"CardOrientation": "VERTICAL", "CardContent": card}}}
        msg_sugg = c.build_suggestions(data.get("message_suggestions", []), max_count=4)
        if msg_sugg:
            content["Suggestions"] = msg_sugg
    else:
        # Flatten markdown before truncating: RCS renders none, so any markdown
        # in the model's output is stripped. Truncated to the documented
        # RCS text-body limit from content/rcs-features.json, because this body
        # is model-generated and nothing upstream bounds its length.
        body = c.strip_markdown(data.get("body", "") or "")[: c.rcs_limit("textBodyChars")]
        content = {"Content": {"TextMessage": {"Body": body}}}
        sugg = c.build_suggestions(data.get("suggestions", []), max_count=4)
        if sugg:
            content["Suggestions"] = sugg

    # Start Over is added here in code, not by the model (R2.1); it replaces any
    # Main Menu / Start Over chip the model added (R2.7).
    if reset_chip:
        content = _attach_reset_chip(content)
    else:
        content = _without_reset_chips(content)
    c.send_rcs(phone, content)
    c.log_message(ph, "outbound", _summarize_ai(data), rcs_content=content)


# ── Send loop ───────────────────────────────────────────────────────────────
def _send(phone, ph, messages, actor=""):
    """Send each message and log it as an outbound turn. `actor` labels the turn
    in the dashboard transcript; the usual bot reply leaves it empty."""
    if not messages:
        return
    multi = len(messages) > 1
    last = len(messages) - 1
    for i, msg in enumerate(messages):
        ttl = msg.pop("_ttl", None) if isinstance(msg, dict) else None
        # "_no_reset" opts a message out of the Start Over chip (the Home_Menu,
        # the live-agent handover cards). Popped from every message so it never
        # reaches send_rcs, like "_ttl".
        no_reset = msg.pop("_no_reset", None) if isinstance(msg, dict) else None
        # A flow can set "_redact_log" to keep a live secret out of the stored
        # transcript (see flows/otp.py). The message still goes to the handset in
        # full; only what we persist to DynamoDB — and therefore what
        # GET /api/conversations/{hash} can return — is replaced. Popped before
        # send_rcs so it never reaches the API, same as "_ttl".
        redact = msg.pop("_redact_log", None) if isinstance(msg, dict) else None
        # "_fallback_body" opts a single message into per-message SMS fallback
        # (see flows/otp.py). Like "_ttl" and "_redact_log" it is this app's own
        # key, not part of RcsMessageContent, so it is popped before the send.
        fallback = msg.pop("_fallback_body", None) if isinstance(msg, dict) else None
        # The Start Over chip goes on the last message of the batch only (R2.8),
        # so what is logged is what was sent. Human-agent replies never come
        # through here (the dashboard push calls c.send_rcs directly), and the
        # only labelled bot send is the fixed safety reply, which keeps the chip.
        if (i == last and not no_reset and isinstance(msg, dict) and "Content" in msg
                and actor in ("", _SAFETY_ACTOR)):
            msg = _attach_reset_chip(msg)
        c.send_rcs(phone, msg, ttl, fallback)
        if redact:
            c.log_message(ph, "outbound", redact)
        else:
            c.log_message(ph, "outbound", _summarize(msg), rcs_content=msg, actor=actor)
        if multi:
            time.sleep(1)


def _summarize(msg):
    content = (msg or {}).get("Content", {})
    if "Carousel" in content:
        return f"[Carousel: {len(content['Carousel'].get('CardContents', []))} cards]"
    if "RichCard" in content:
        return f"[Card: {content['RichCard'].get('CardContent', {}).get('Title', '')}]"
    if "TextMessage" in content:
        return content["TextMessage"].get("Body", "")[:200]
    if "FileMessage" in content:
        url = content["FileMessage"].get("FileUrl", "")
        return f"[File: {url.rsplit('/', 1)[-1] or 'attachment'}]"
    return "[Message]"


def _summarize_ai(data):
    if data.get("type") == "rich_card":
        return f"[Card: {data.get('title', '')}]"
    return (data.get("body", "") or "")[:200]
