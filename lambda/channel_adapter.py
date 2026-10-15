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

import json
import re
import time

import boto3
from botocore.config import Config

import common as c
from flows import get_flow, AI_DRIVEN_VIGNETTES, welcome, otp, handover, video_visit


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
    # home_menu / handover_end, or the typed menu words screened above). Media
    # is still logged above so it appears in the dashboard for the Care
    # Advocate. A successfully-received photo gets a one-line receipt, and
    # media_convert asynchronously replaces the raw file with a normalized
    # JPEG + classification in the dashboard.
    native_conversion_pending = _needs_native_conversion(parsed)
    if live:
        if parsed["type"] == "postback" and parsed["postback_data"] in ("handover_end", "home_menu"):
            # home_menu is the one button present on nearly every card, so
            # it's the member's most likely escape hatch if they're stuck in
            # a live conversation that isn't actually staffed (e.g. a demo
            # left in live mode). Treat it the same as "Back to Assistant"
            # rather than silently swallowing it like every other postback
            # below — a member should never have a dead button with no way
            # back to the bot.
            c.set_mode(ph, "bot")
            _send(phone, ph, handover.resolved_card())
        elif parsed["type"] == "postback" and parsed["postback_data"] == "photo_secure_upload":
            # A secure-upload link is an explicit member action, not a bot
            # interruption. Honor it even during human handover so an iPhone
            # HEIC failure can immediately pivot to the compliance-forward
            # webview path.
            c.set_active_flow(ph, "insurance_upload")
            _send(phone, ph, get_flow("insurance_upload").on_start(phone, ph))
        elif parsed["type"] == "media" and parsed["media"].get("mediaStatus") == "SUCCESS":
            _send(phone, ph, _media_receipt_ack())
        elif parsed["type"] == "postback" and _is_action_only_postback(parsed["postback_data"]):
            # A chip that ran on the handset (dial, map, calendar, webview): the
            # member already has what they asked for, and the nudge below would
            # tell someone who just placed a call that the button "isn't active".
            # The emergency reply's Call Member Services chip is one of these.
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


def handle_trigger(phone, ph, vignette):
    vkey = vignette.lower().replace(" ", "_")
    flow = get_flow(vkey)
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
    elif vkey in AI_DRIVEN_VIGNETTES:
        c.set_active_flow(ph, vkey)
        send_ai_response(phone, ph, invoke_ai(ph, f"The member just started the {vkey} flow. Greet them briefly and offer help.", vkey))
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
    "clock_summary_wv",
    "emergency_call_member_services",
    "fit_browser",
    "fit_webview_full",
    "ivs_browser",
    "ivs_webview_full",
    "loan_open",
    "probe_browser",
    "probe_webview_full",
    "probe_webview_half",
    "pto_cal",
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

    if pd == "home_menu":
        c.clear_active_flow(ph)
        _send(phone, ph, welcome.on_start(phone, ph))
        return

    # The native-photo failure card links here. This must be an explicit flow
    # switch, not a generic free-text/AI fallback, so tapping "Secure Upload"
    # opens the HEIC-capable webview card again.
    if pd == "photo_secure_upload":
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
    }
    if pd in home:
        vkey = home[pd]
        c.set_active_flow(ph, vkey)
        _send(phone, ph, get_flow(vkey).on_start(phone, ph))
        return
    if pd == "home_benefits":
        c.set_active_flow(ph, "benefits_qa")
        send_ai_response(phone, ph, invoke_ai(ph, "The member wants to ask about benefits and coverage. Greet briefly and ask how you can help.", "benefits_qa"))
        return
    if pd == "home_find_care":
        c.set_active_flow(ph, "find_care")
        send_ai_response(phone, ph, invoke_ai(ph, "The member wants to find an in-network provider. Ask what type of care they need.", "find_care"))
        return

    # Cross-flow jumps from My Schedule into PTO Request / Shift Swap. These
    # are explicit switches (mirroring the `home` dict above) rather than
    # relying on the prefix fallback below, so the active-flow state stays
    # correct for anything the target flow does next (e.g. free-text or a
    # second postback).
    internal_jumps = {"sched_pto": "pto_request", "sched_swap": "shift_swap"}
    if pd in internal_jumps:
        vkey = internal_jumps[pd]
        c.set_active_flow(ph, vkey)
        _send(phone, ph, get_flow(vkey).on_start(phone, ph))
        return

    # Route to the active flow.
    active = c.get_active_flow(ph)
    if active in AI_DRIVEN_VIGNETTES and not _is_action_only_postback(pd):
        send_ai_response(phone, ph, invoke_ai(ph, f'Member tapped: "{pd}"', active))
        return
    flow = get_flow(active) if active else None
    if flow:
        messages = _flow_postback(flow, phone, ph, pd)
        if messages:
            _send(phone, ph, messages)
            return

    # Fall back: try any flow that owns this postback by prefix.
    for vkey in ("rx_refill", "appt_reminder", "store", "verification", "welcome",
                 "clock_in_out", "my_schedule", "pto_request", "shift_swap",
                 "photo_submission", "insurance_upload"):
        messages = _flow_postback(get_flow(vkey), phone, ph, pd)
        if messages:
            _send(phone, ph, messages)
            return

    if _is_action_only_postback(pd):
        print(f"ACTION POSTBACK {pd}: the handset already ran the action; no reply sent")
        return

    # Last resort: let the assistant handle it.
    send_ai_response(phone, ph, invoke_ai(ph, f'Member tapped: "{pd}"', active or "benefits_qa"))


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
# A false positive costs one extra message with a Main Menu chip; a miss can cost
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
                "Text": "Call Member Services", "PostbackData": "emergency_call_member_services",
                "PhoneNumber": c.member_services_phone(),
            }},
            {"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}},
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
_MENU_ESCAPES = frozenset({"menu", "main menu", "home", "start over"})
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
        # Same effect as tapping Main Menu, plus leaving live mode: a member
        # stuck in a thread nobody is staffing has no chip to tap if the card
        # that held it has scrolled away.
        c.clear_active_flow(ph)
        if live:
            c.set_mode(ph, "bot")
        print(f"TYPED ESCAPE {word!r}: cleared the active flow{', left live mode' if live else ''}, sent the welcome")
        _send(phone, ph, welcome.on_start(phone, ph))
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
        send_ai_response(phone, ph, invoke_ai(ph, text, active))
        return
    if active == "store":
        _send(phone, ph, get_flow("store").on_start(phone, ph))
        return

    # Intent keywords, matched as whole words (with the inflections a member
    # would plausibly type) rather than as substrings: "order" must not fire
    # inside "disorder", nor "person" inside "personal".
    words = _match_text(text)
    if _ROUTE_HANDOVER.search(words):
        c.set_mode(ph, "live")
        _send(phone, ph, handover.escalate_card())
        return
    if _ROUTE_RX.search(words):
        c.set_active_flow(ph, "rx_refill")
        _send(phone, ph, get_flow("rx_refill").on_start(phone, ph))
        return
    if _ROUTE_APPT.search(words):
        c.set_active_flow(ph, "appt_reminder")
        _send(phone, ph, get_flow("appt_reminder").on_start(phone, ph))
        return
    if _ROUTE_STORE.search(words):
        c.set_active_flow(ph, "store")
        _send(phone, ph, get_flow("store").on_start(phone, ph))
        return
    if _ROUTE_VERIFY.search(words):
        c.set_active_flow(ph, "verification")
        _send(phone, ph, get_flow("verification").on_start(phone, ph))
        return
    if _ROUTE_FIND.search(words):
        c.set_active_flow(ph, "find_care")
        send_ai_response(phone, ph, invoke_ai(ph, text, "find_care"))
        return

    # Default to the benefits assistant.
    c.set_active_flow(ph, "benefits_qa")
    send_ai_response(phone, ph, invoke_ai(ph, text, "benefits_qa"))


# ── Dashboard push (triggers, direct sends, live-agent replies) ─────────────
def handle_push(p):
    phone = p.get("phone", "")
    ph = c.hash_phone(phone)
    if p.get("vignette"):
        handle_trigger(phone, ph, p["vignette"])
    elif p.get("agent_message") is not None:
        text = str(p["agent_message"])[: c.rcs_limit("textBodyChars")]
        agent = p.get("agent", "Care Advocate")
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
    _send(phone, phone_hash, _media_received_card(media, payload.get("classification", "")))


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
        "Try a JPEG or PNG under 100 MB, or use the secure upload link below."
    )
    return [{
        "Content": {"TextMessage": {"Body": body}},
        "Suggestions": [
            {"OpenUrl": {
                "Text": "Secure Upload", "PostbackData": "photo_secure_upload",
                "Url": c.webview_url("upload-insurance-card", ph=phone_hash),
                "Application": "WEBVIEW", "WebviewViewMode": "TALL",
            }},
            {"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}},
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
    card = {
        "Title": "Photo Received",
        "Description": description,
    }
    if media_key:
        card["Media"] = {"FileUrl": c.inbound_media_url(media_key), "Height": "MEDIUM"}
    return [{
        "Content": {"RichCard": {"CardOrientation": "VERTICAL", "CardContent": card}},
        "Suggestions": [{"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}}],
    }]


# ── Bedrock AI assistant ────────────────────────────────────────────────────
def _member_ctx(phone_hash):
    """Member facts injected into the AI system prompt. The name comes from the
    Recipients tab so the assistant greets the person actually holding the
    phone; brand.md's memberName is only the fallback (dashboard previews, or a
    recipient with no name set). Plan details stay sample data from brand.md."""
    b = c.brand()
    return (f"Member: {c.tester_name(phone_hash, fallback=c.member_name())}, "
            f"Plan: {b.get('memberPlan', '')}, "
            f"Member ID: {b.get('memberIdMasked', '')}, "
            f"Location: {b.get('memberCity', '')}.")


def _json_contract():
    return (
        'RULES:\n'
        '1. Return EXACTLY ONE valid JSON object. No markdown, no preamble.\n'
        '2. text: {"type":"text","body":"...","suggestions":[...]}; '
        'rich card: {"type":"rich_card","title":"...","description":"...","suggestions":[...]}.\n'
        '3. EVERY response includes suggestions. Max 4, each text under 25 chars.\n'
        f'4. Always include {{"type":"dial","text":"Call Member Services","phone_number":"{c.member_services_phone()}"}} '
        'and {"type":"reply","text":"Main Menu","postback":"home_menu"}.\n'
        '5. If the member wants a human, include '
        '{"type":"reply","text":"Talk to a Person","postback":"handover_start"}.\n'
        '6. Prefer text; use rich_card only for structured info. Use everyday language.\n'
        '7. body/title/description are shown as PLAIN TEXT on the phone. Never use '
        'markdown: no **bold**, *italic*, `code`, # headings, or [links](url). '
        'For a list, put each item on its own line starting with "- ".'
    )


def _benefits_prompt(phone_hash):
    return (f"You are {c.brand_name()}'s virtual benefits advisor over RCS.\n{_member_ctx(phone_hash)}\n\n"
            f"Use ONLY this plan knowledge:\n{c.content_body('benefits.md')}\n\n{_json_contract()}")


def _find_care_prompt(phone_hash):
    # The extra rule is what makes RequestLocation reachable: finding a provider
    # is the one vignette where the member's own position is the missing input,
    # and RCS can ask the handset for it instead of asking the member to type a
    # postcode. handle_location receives the answer.
    return (f"You are {c.brand_name()}'s provider-finder assistant over RCS.\n{_member_ctx(phone_hash)}\n\n"
            f"Use ONLY this provider directory:\n{c.content_body('providers.md')}\n\n{_json_contract()}\n"
            '7. When you do not yet know where the member is, include exactly one '
            '{"type":"share_location","text":"Share My Location"} '
            "suggestion so their phone can offer to send it. Drop it once you know their location, "
            "and never ask twice in a row.")


def invoke_ai(ph, user_message, vignette):
    system = _find_care_prompt(ph) if vignette == "find_care" else _benefits_prompt(ph)

    messages = []
    for m in c.conversation_history(ph, limit=6):
        d = m.get("direction")
        if d == "inbound":
            messages.append({"role": "user", "content": [{"text": m.get("body", "")}]})
        elif d == "outbound":
            messages.append({"role": "assistant", "content": [{"text": m.get("body", "")}]})
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
                {"type": "reply", "text": "Main Menu", "postback": "home_menu"},
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
        "suggestions": [{"type": "reply", "text": "Main Menu", "postback": "home_menu"}],
    }


def send_ai_response(phone, ph, data):
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

    c.send_rcs(phone, content)
    c.log_message(ph, "outbound", _summarize_ai(data), rcs_content=content)


# ── Send loop ───────────────────────────────────────────────────────────────
def _send(phone, ph, messages, actor=""):
    """Send each message and log it as an outbound turn. `actor` labels the turn
    in the dashboard transcript; the usual bot reply leaves it empty."""
    if not messages:
        return
    multi = len(messages) > 1
    for msg in messages:
        ttl = msg.pop("_ttl", None) if isinstance(msg, dict) else None
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
