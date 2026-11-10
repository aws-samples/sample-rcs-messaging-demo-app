"""AnyWealth fraud alert — a verified-sender rich card with an expiring code.

This is AnyWealth's representative vignette, and it exists to make one point that
only RCS can make for a bank: the message carries the bank's *verified sender
identity*. The handset renders AnyWealth's registered logo, name and brand colour
itself, so the member can tell this really is their bank asking about a flagged
charge — not a smishing text wearing the bank's name. That trust is the whole
reason a financial brand registers its own RCS agent (R3.5).

The flow sends a single rich card about a flagged transaction, read from
`content/wealth.md`, with two reply chips — "Yes, it was me" / "No, it wasn't" —
and a one-time step-up code shown in the card. Three RCS features carry the
scenario:

- `time_to_live`   RCS gets a short window to deliver the alert; if it misses it,
                   the platform revokes the message rather than showing a stale
                   fraud prompt, and the SMS fallback takes over.
- `per_message_fallback`  a hand-written SMS body (no card chips survive as SMS)
                   so the alert still reaches the member if RCS can't deliver —
                   active only when the stack was deployed with
                   `-c smsFallbackNumber=+1…` (see common.send_rcs).
- `otp`            the step-up code the member quotes to the fraud line to prove
                   it's them, with its own validity window.

Triggers: `Start: Wealth_Fraud_Alert`, or the dashboard push.
Postback prefix: fraud_

Messages returned by this flow may carry a private `_ttl` key (seconds); the
channel adapter passes it to SendRcsMessage as TimeToLive, and `_fallback_body`,
the plain-text SMS sent if RCS fails or that TTL expires.
"""

import random

import common as c

# How long the step-up code stays valid once the member has it. Drives the "code
# expires in N minutes" copy and (when a real verify step is wired) the stored
# ttl. Read from content/wealth.md so the sample data owns it, with a safe
# default when the key is absent. Read lazily inside the flow (like every other
# accessor here) rather than at import time: the module is imported through the
# flow registry before the content directory is necessarily in place, so a
# module-level read would fail the import.
def _code_ttl_seconds() -> int:
    return int(c.content_frontmatter("wealth.md").get("otpTtlSeconds", 300))

# How long RCS gets to deliver the alert before the platform gives up on it —
# SendRcsMessage TimeToLive. Deliberately much shorter than the code validity
# window (_code_ttl_seconds) and a separate number: a fraud alert is
# time-sensitive, so if RCS can't deliver it promptly the member should get the
# SMS fallback rather than a late RCS card. One minute leaves the rest of the
# code's validity window to act on the code.
DELIVERY_TTL_SECONDS = 60


def _wealth() -> dict:
    """The AnyWealth sample knowledge (member, account, flagged transaction)."""
    return c.content_frontmatter("wealth.md")


def _fraud_line() -> str:
    """The number the member calls when the charge was not theirs. Falls back to
    the brand's member-services phone when the sample data omits it."""
    return _wealth().get("fraudLinePhone") or c.member_services_phone()


def on_start(phone, phone_hash):
    return _fraud_alert()


def on_trigger(phone, phone_hash, vignette):
    return _fraud_alert()


def _alert_card(code: str) -> list:
    """The fraud-alert rich card. `code` is the step-up code shown in the card —
    a live random value on a real send, a fixed placeholder for the preview."""
    w = _wealth()
    txn = w.get("flaggedTransaction", {}) or {}
    merchant = txn.get("merchant", "an online merchant")
    amount = txn.get("amount", 0)
    currency = txn.get("currency", "USD")
    city = txn.get("city", "")
    when = txn.get("dateTime", "recently")
    card_masked = w.get("cardNumberMasked", "your card")
    minutes = _code_ttl_seconds() // 60

    location = f" in {city}" if city else ""
    # The brand's own card image (its verified look is the point of this card),
    # or no media when the brand defines none.
    media = c.brand_card_media()
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    **({"Media": media} if media else {}),
                    "Title": "Did you make this purchase?",
                    "Description": (
                        f"We spotted an unusual charge on card {card_masked}:\n\n"
                        f"{merchant}\n"
                        f"${amount:,.2f} {currency}{location}\n"
                        f"{when}\n\n"
                        "If this was you, tap \"Yes, it was me\" and no action is "
                        "needed. If not, tap \"No, it wasn't\" and we'll freeze the "
                        "card right away.\n\n"
                        f"To verify it's you, your one-time code is {code} "
                        f"(expires in {minutes} minutes)."
                    ),
                    "Suggestions": [
                        {"Reply": {"Text": "Yes, it was me", "PostbackData": "fraud_confirm_me"}},
                        {"Reply": {"Text": "No, it wasn't", "PostbackData": "fraud_not_me"}},
                        {"DialPhone": {
                            "Text": "Call Fraud Line",
                            "PostbackData": "fraud_call",
                            "PhoneNumber": _fraud_line(),
                        }},
                    ],
                },
            }
        },
        "Suggestions": [{"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}}],
        # Give RCS a short delivery window; if it lapses the platform revokes the
        # card and the SMS fallback below carries the alert instead. Passed to
        # SendRcsMessage as TimeToLive by the channel adapter.
        "_ttl": DELIVERY_TTL_SECONDS,
        # Per-message SMS fallback, written out rather than derived from the card:
        # the card's value is in its reply chips and the dial action, none of
        # which survive as SMS, so the plain text has to carry the charge details
        # and a phone number. The step-up code is deliberately left out of the
        # SMS — an SMS has none of RCS's verified sender identity to vouch for who
        # sent it, so it must not read like a code-bearing bank text a scammer
        # could imitate. Inactive unless the stack was deployed with
        # -c smsFallbackNumber=+1…; see common.send_rcs.
        "_fallback_body": (
            f"{c.brand_name()}: we spotted an unusual charge on card {card_masked} "
            f"— {merchant}, ${amount:,.2f} {currency}{location}, {when}. "
            f"If this was not you, call our fraud line at {_fraud_line()} right away."
        ),
    }]


def _fraud_alert() -> list:
    # A fresh step-up code per send. Not persisted here (unlike otp.py): this
    # vignette demonstrates the verified-sender alert and the expiring-code copy,
    # not a full verify round-trip, so on_start stays side-effect free just like
    # the preview — no DynamoDB write, nothing to differ between the two paths.
    code = f"{random.randint(0, 999999):06d}"
    return _alert_card(code)


def preview_message():
    """Dashboard-only phone preview: the same card shape as a real send, with a
    placeholder code and no DynamoDB write and no send — previewing must have
    zero side effects since it can be triggered on every card open. Mirrors the
    PREVIEWABLE pattern in dashboard_handler.py."""
    return _alert_card("123456")


def _card_frozen() -> list:
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "Card frozen",
                    "Description": (
                        "Thanks for confirming. We've frozen the card so it can't "
                        "be used, and a specialist will review the charge and reach "
                        "out. A replacement card is on its way.\n\n"
                        "If you need anything sooner, call our fraud line."
                    ),
                    "Suggestions": [
                        {"DialPhone": {
                            "Text": "Call Fraud Line",
                            "PostbackData": "fraud_call",
                            "PhoneNumber": _fraud_line(),
                        }},
                    ],
                },
            }
        },
        "Suggestions": [{"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}}],
    }]


def _confirmed_safe() -> list:
    return [{
        "Content": {"TextMessage": {"Body": (
            "Thanks — we've cleared the alert and left your card active. "
            "No further action is needed."
        )}},
        "Suggestions": [{"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}}],
    }]


def on_postback(phone, phone_hash, postback_data):
    if postback_data == "fraud_confirm_me":
        return _confirmed_safe()
    if postback_data == "fraud_not_me":
        return _card_frozen()
    return None
