"""Verification code (OTP) — demonstrates SendRcsMessage with TimeToLive.

A 6-digit code stays valid for five minutes, but RCS is given only one minute to
deliver it. If it isn't delivered in that window, EUM revokes it (a real concern
for time-sensitive codes) and the SMS fallback takes over with four minutes of
validity left. The user can reply with the code to "verify", or request a resend.

Triggers: `Start: Verification`, or the `home_verify` postback.
Postback prefix: otp_

Messages returned by this flow may carry a private `_ttl` key (seconds); the
channel adapter passes it to SendRcsMessage as TimeToLive. They also carry
`_fallback_body`, the plain-text SMS sent if RCS fails or that TTL expires —
active only when the stack was deployed with `-c smsFallbackNumber=+1…`.
"""

import time
import random

import common as c

# How long the code is accepted once the member has it. Drives the DynamoDB item
# ttl (which verify() checks itself) and the "expires in N minutes" copy.
CODE_TTL_SECONDS = 300  # 5 minutes

# How long RCS gets to deliver the code before the platform gives up on it —
# SendRcsMessage TimeToLive. Deliberately much shorter than CODE_TTL_SECONDS and
# a separate number rather than the same one: TTL expiry is what triggers the SMS
# fallback, so a delivery window equal to the validity window would fall back at
# the exact instant the code stopped working. One minute leaves four to use it.
# Valid range is 1s to 48h; the short end is also what makes RCS_TTL_EXPIRED
# observable in a demo without waiting out a realistic window.
DELIVERY_TTL_SECONDS = 60


def on_start(phone, phone_hash):
    return _send_code(phone_hash)


def on_trigger(phone, phone_hash, vignette):
    return _send_code(phone_hash)


def _code_message(code):
    return [{
        "Content": {
            "TextMessage": {
                "Body": (
                    f"Your {c.brand_name()} verification code is {code}. "
                    f"It expires in {CODE_TTL_SECONDS // 60} minutes. "
                    "Reply with the code to confirm your login."
                )
            }
        },
        "Suggestions": [
            {"Reply": {"Text": "Resend Code", "PostbackData": "otp_resend"}},
            {"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}},
        ],
        # Passed through to SendRcsMessage as TimeToLive by the channel adapter.
        "_ttl": DELIVERY_TTL_SECONDS,
        # Per-message SMS fallback, written separately rather than derived from
        # the RCS body: the fallback caps at 1,600 characters against the RCS
        # body's 3,072, and an SMS has no suggestion chips to explain itself.
        # TTL expiry is the documented trigger for fallback, which is why the
        # pair belongs on this vignette in particular — a code RCS could not
        # deliver inside DELIVERY_TTL_SECONDS still reaches the member as an SMS,
        # with most of CODE_TTL_SECONDS left to act on it.
        #
        # Ignored unless the stack was deployed with -c smsFallbackNumber=+1…;
        # see common.send_rcs.
        "_fallback_body": (
            f"Your {c.brand_name()} verification code is {code}. "
            f"It expires in {CODE_TTL_SECONDS // 60} minutes."
        ),
        # Keep the live code out of the stored transcript. The member still
        # receives the full message; this only changes what is written to
        # DynamoDB. Honoured by channel_adapter._send.
        #
        # Note this covers the OUTBOUND leg only. If the member replies with the
        # code, channel_adapter logs their inbound text verbatim, so the code can
        # still appear in the transcript from that side — which is one more reason
        # GET /api/conversations* is behind the API key.
        "_redact_log": (
            f"[Verification code sent — expires in {CODE_TTL_SECONDS // 60} minutes]"
        ),
    }]


def _send_code(phone_hash):
    code = f"{random.randint(0, 999999):06d}"
    c.table.put_item(Item={
        "pk": f"OTP#{phone_hash}", "sk": "CODE",
        "code": code, "ttl": int(time.time()) + CODE_TTL_SECONDS,
    })
    return _code_message(code)


def preview_message():
    """Dashboard-only phone preview: same message shape as a real send, with a
    placeholder code and no DynamoDB write — previewing must have zero side
    effects since it can be triggered on every card open."""
    return _code_message("123456")


def _verified():
    return [{
        "Content": {"TextMessage": {"Body": "Verified. You're securely signed in to AnyHealth."}},
        "Suggestions": [{"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}}],
    }]


def _incorrect():
    return [{
        "Content": {"TextMessage": {"Body": "That code doesn't match or has expired. Tap Resend Code for a new one."}},
        "Suggestions": [
            {"Reply": {"Text": "Resend Code", "PostbackData": "otp_resend"}},
            {"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}},
        ],
    }]


def verify(phone, phone_hash, text):
    """Called by the channel adapter when the verification flow is active and the
    user replies with free text (the code)."""
    entered = "".join(ch for ch in (text or "") if ch.isdigit())
    # A code past its ttl is rejected even while its row is still in the table:
    # DynamoDB deletes expired items on its own schedule (typically within a few
    # days), so the five-minute window is enforced here, not left to that.
    item = c.unexpired(c.table.get_item(Key={"pk": f"OTP#{phone_hash}", "sk": "CODE"}).get("Item"))
    if item and entered and entered == item.get("code"):
        c.table.delete_item(Key={"pk": f"OTP#{phone_hash}", "sk": "CODE"})
        c.clear_active_flow(phone_hash)
        return _verified()
    return _incorrect()


def on_postback(phone, phone_hash, postback_data):
    if postback_data == "otp_resend":
        return _send_code(phone_hash)
    return None
