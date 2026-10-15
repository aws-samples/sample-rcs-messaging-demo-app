"""Live-agent handover.

The AI (or any flow) can offer "Talk to a Person" (postback `handover_start`).
The channel adapter flips the conversation into LIVE mode: it stops replying
with the bot and forwards the member's messages to the dashboard, where a human
agent replies (those replies are pushed back over RCS via the dashboard's push
path). `handover_end` returns control to the assistant.

This module only builds the member-facing cards; the mode switching lives in
the channel adapter and the dashboard.

Compliance: a live thread is where a member is most likely to type health
information. This sample treats every message as demo data, keeps the
transcript in DynamoDB for 30 days (common.TTL_CONVERSATION_DAYS), and lets
anyone holding the single shared dashboard key read it. If real members use it,
their messages can be protected health information, and HIPAA applies: you need
an AWS Business Associate Addendum, per-user access control on the dashboard, an
audit log of who read what, and a retention period you chose. See SECURITY.md.

Postback prefix: handover_
"""

import common as c


def on_start(phone, phone_hash):
    return escalate_card()


def on_trigger(phone, phone_hash, vignette):
    return escalate_card()


def on_postback(phone, phone_hash, postback_data):
    """Every flow module must expose this: handle_postback routes a postback to
    the active flow's on_postback, so a module without one raised an
    AttributeError (a 500 on the webhook) as soon as a member in this flow
    tapped a chip that wasn't handled earlier in the dispatcher.

    `handover_start` / `handover_end` are still handled by the adapter, because
    they can arrive from any flow and also have to flip the conversation mode.
    This is the fallback for anything else tapped mid-handover — returning None
    lets the adapter try its prefix fallback, then the assistant.
    """
    if postback_data == "handover_end":
        return resolved_card()
    return None


def escalate_card():
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "Connecting you to a care advocate",
                    "Description": (
                        f"A {c.brand_name()} care advocate is joining this chat. "
                        "Go ahead and describe what you need — they'll reply right here."
                    ),
                    "Media": {"FileUrl": c.resolve_media("media/handover.png"), "Height": "MEDIUM"},
                },
            }
        },
        "Suggestions": [
            {"Reply": {"Text": "Back to Assistant", "PostbackData": "handover_end"}},
        ],
        # SMS fallback for the vignette's entry message; inactive unless the
        # stack was deployed with -c smsFallbackNumber=+1…. See common.send_rcs.
        # Handover is the one vignette where a fallback must NOT promise the
        # thing the card promises. If RCS failed, the member cannot chat with an
        # advocate here — inbound RCS is how their replies reach the dashboard,
        # and an SMS reply would not arrive on that path at all. So this hands
        # them a phone number instead of inviting a reply into a dead channel.
        "_fallback_body": (
            f"{c.brand_name()}: we couldn't open a rich chat with a care advocate "
            f"on your device. Please call {c.member_services_phone()} and an "
            "advocate will help you directly."
        ),
    }]


def resolved_card():
    return [{
        "Content": {"TextMessage": {"Body": f"You're back with the {c.brand_name()} assistant. How can I help?"}},
        "Suggestions": [{"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}}],
    }]


def stuck_nudge_card():
    """Sent when a member taps a button that isn't actionable during a live
    handover (e.g. a leftover "Refill Now" from a card sent before the
    handover started) — see channel_adapter.process_inbound's live-mode
    branch. Surfaces the one escape hatch that's always honored (home_menu,
    handled the same as handover_end) so the member is never stuck looking
    at a dead button with no visible way back to the assistant."""
    return [{
        "Content": {"TextMessage": {"Body": "A care advocate has this conversation right now, so that button isn't active. Type your question, or tap below to return to the assistant."}},
        "Suggestions": [{"Reply": {"Text": "Back to Assistant", "PostbackData": "home_menu"}}],
    }]
