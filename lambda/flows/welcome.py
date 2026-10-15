"""Welcome — the educational front door (home screen / cold start).

Triggers: `Start: Welcome`, the configured deep-link keyword, a bare greeting
with no active flow, or the `home_menu` postback.

This is the first message a newly verified tester sees, so it does one job:
explain that this thread is an **AWS End User Messaging RCS** demo and teach the
few concepts a viewer needs to make sense of everything else — what RCS is,
how a brand gets a verified identity through registration, how opt-in/opt-out
works, and what SMS fallback does when it is enabled. It is deliberately NOT a
carousel and NOT a wall of one-card-per-vignette tiles: the dashboard is the
place to push individual vignettes to a device during a demo. Here we teach,
then offer a compact set of reply chips so the handset can still self-navigate.

Design notes:
  * Three standalone RichCards, delivered ~1s apart by channel_adapter._send.
    On the iOS and Android handsets tried, the cards of a multi-card carousel
    arrived in a different order and could split across messages, while
    standalone cards rendered consistently on both, so the welcome uses three
    cards in sequence; the Wellness Store uses a carousel because a swipeable
    product catalog is the lesson there.
  * Card-level Suggestions (max 4) stay attached to their card. Message-level
    Suggestions (max 11) render as a chip row under the message; the last card
    carries the compact navigation set, replacing the old 12-tile menu.
  * Every navigation chip reuses the existing `home_*` PostbackData, so
    channel_adapter.handle_postback routes them into the right flow unchanged.
  * Copy pulls brand values from content/brand.md via common.py accessors, and
    reads common.sms_fallback_active() so the SMS-fallback card tells the truth
    about THIS deployment rather than describing a feature it may not have.
  * on_start / on_trigger / on_postback take (phone, phone_hash, …) but touch no
    per-recipient state, so the dashboard's Device preview can call
    on_start("", "") safely.

Postback prefix: home_
"""

import common as c


def on_start(phone, phone_hash):
    return _welcome()


def on_trigger(phone, phone_hash, vignette):
    return _welcome()


def _nav_suggestions():
    """The compact navigation chip row that replaces the old capability
    carousel. Message-level suggestions cap at 11; we send a curated handful of
    the most demo-worthy flows plus Main Menu, not all seventeen vignettes —
    pushing a specific vignette to the device is the dashboard's job. Reuses the
    existing `home_*` PostbackData so channel_adapter routing is unchanged."""
    return c.build_suggestions(
        [
            {"type": "reply", "text": "Prescriptions", "postback": "home_rx"},
            {"type": "reply", "text": "Appointments", "postback": "home_appt"},
            {"type": "reply", "text": "Ask About Benefits", "postback": "home_benefits"},
            {"type": "reply", "text": "Find Care", "postback": "home_find_care"},
            {"type": "reply", "text": "Wellness Store", "postback": "home_store"},
            {"type": "reply", "text": "Verify Login", "postback": "home_verify"},
            {"type": "reply", "text": "Send a Photo", "postback": "home_photo"},
            {"type": "reply", "text": "Upload Securely", "postback": "home_upload"},
        ],
        max_count=c.rcs_limit("suggestionsPerMessage"),
    )


def _welcome():
    brand = c.brand_name()

    # Card 1 — frame the whole thread: this is an AWS EUM RCS demo, and here is
    # what RCS is. Card-level chips offer two concrete "try it" jumps so a viewer
    # can act immediately; the fuller navigation row is on the last card.
    intro = {
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": f"Welcome to the {brand} RCS demo",
                    "Description": (
                        "A demonstration of AWS End User Messaging RCS, themed as a "
                        f"fictitious healthcare brand ({brand}). No real data here.\n\n"
                        "RCS is the successor to SMS: branded cards, images, reply "
                        "chips, and native actions like dialing or maps -- right in "
                        "the Messages app, no app to install.\n\n"
                        "Tap a chip to try it, or read on."
                    ),
                    "Media": {"FileUrl": c.resolve_media("media/welcome-hero.png"), "Height": "SHORT"},
                    "Suggestions": [
                        {"Reply": {"Text": "Prescriptions", "PostbackData": "home_rx"}},
                        {"Reply": {"Text": "Ask About Benefits", "PostbackData": "home_benefits"}},
                    ],
                },
            }
        },
        # SMS fallback on the FIRST message only. The welcome sends three cards,
        # and a fallback body on each would land three near-identical SMS
        # messages when RCS is unavailable (fallback fires per message, not per
        # vignette). Inactive unless the stack was deployed with
        # -c smsFallbackNumber=+1...; see common.send_rcs.
        "_fallback_body": (
            f"{brand}: this is a demo of AWS End User Messaging RCS, but your device "
            "is not showing rich messages right now, so you are seeing SMS instead. "
            f"That switch is exactly what RCS SMS fallback does. Call "
            f"{c.member_services_phone()} for help, or open the thread on an "
            "RCS-capable device to see the full experience."
        ),
    }

    # Card 2 — trust model: registration, verified brand identity, opt-in/out.
    brand_trust = {
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "Verified brand, and your choice to be here",
                    "Description": (
                        "To send RCS, a business registers the agent with carriers and "
                        "Google -- the brand name, logo, and accent color shown above. "
                        "The Messages app renders that identity itself, so an RCS "
                        "sender is hard to impersonate.\n\n"
                        "You stay in control: you opt in by starting the chat, and can "
                        "opt out anytime by texting STOP. End User Messaging answers "
                        "STOP and HELP itself, with the replies the sender registered "
                        "for them."
                    ),
                    "Media": {"FileUrl": c.resolve_media("media/welcome-hero.png"), "Height": "SHORT"},
                },
            }
        },
    }

    # Card 3 — SMS fallback, told truthfully for THIS deployment, then the
    # compact navigation chip row that stands in for the old carousel menu.
    if c.sms_fallback_active():
        fallback_para = (
            "SMS fallback is ENABLED here. If an RCS message can't reach your device, "
            "it's re-sent as SMS from a backup number -- you're still reached, just "
            "without the cards, images, and chips."
        )
    else:
        fallback_para = (
            "SMS fallback is OFF in this demo. When enabled (deploy with an "
            "SMS-capable number), an RCS message that can't reach a device is re-sent "
            "as SMS -- the recipient is still reached, just without the cards, images, "
            "and chips."
        )

    fallback_card = {
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "When RCS is not available: SMS fallback",
                    "Description": (
                        f"{fallback_para}\n\n"
                        "It's the safety net that lets a business adopt RCS without "
                        "leaving anyone behind.\n\n"
                        "Pick a capability below, or just ask a question -- an AI "
                        "assistant can answer."
                    ),
                    "Media": {"FileUrl": c.resolve_media("media/welcome-hero.png"), "Height": "SHORT"},
                },
            }
        },
        "Suggestions": _nav_suggestions(),
    }

    return [intro, brand_trust, fallback_card]


def on_postback(phone, phone_hash, postback_data):
    # The Main Menu chip (home_menu) and any unknown-trigger fallback route back
    # here. Re-send the educational welcome; channel_adapter clears the active
    # flow before calling this for home_menu.
    if postback_data == "home_menu":
        return _welcome()
    return None
