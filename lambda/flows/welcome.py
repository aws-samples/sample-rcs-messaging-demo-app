"""Welcome — the educational front door (home screen / cold start).

Two messages live here, both built from the selected brand's content:

  * The Welcome_Intro (`_welcome`, returned by on_start / on_trigger): three
    standalone cards sent on first contact, `Start: Welcome`, the configured
    deep-link keyword, a bare greeting with no active flow, and the dashboard's
    Device preview.
  * The Home_Menu (`home_menu`): one short card, the brand name and its line of
    business over the navigation chips. This is where a conversation Reset
    (Start Over, or an old Main Menu chip) lands, so it is deliberately brief
    and does not repeat the Welcome_Intro.

Every card uses the selected brand's own card image (`cardImage` in its block of
content/brand.md, else its `bannerImage`); a brand with neither sends the cards
without media.

The Welcome_Intro is the first message a newly verified tester sees, so it does one job:
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
    carries the navigation set.
  * The navigation chips come from the selected brand's `homeMenu` list in
    content/brand.md (a label and a postback each, at most ten), read through
    common.home_menu(). Adding, renaming or removing a tile is a content edit.
    The postbacks are existing `home_*` ids, so channel_adapter.handle_postback
    routes them into the right flow unchanged.
  * The last message of each of the two carries the private `_no_reset` key,
    which the channel adapter pops before sending: both are where a Reset
    lands or starts, so neither offers a Start Over chip.
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


def _has_assistant():
    """Whether typed text reaches an AI assistant for the selected brand: its
    `defaultVignette` is AI-driven and the brand allows it. Only then may the
    copy invite the guest to ask a question. A brand with an empty
    `defaultVignette` answers typed text with the Home_Menu instead.

    AI_DRIVEN_VIGNETTES is imported here, not at module level: flows/__init__.py
    imports this module before it defines the set."""
    from flows import AI_DRIVEN_VIGNETTES

    vkey = c.default_vignette()
    return vkey in AI_DRIVEN_VIGNETTES and c.vignette_allowed(vkey)


def _brand_media():
    """The card media: the selected brand's card image (`cardImage` in its block
    of content/brand.md, a 3:1 picture with the wordmark kept to the middle so a
    narrower crop on a handset does not cut it), else its `bannerImage`, or None
    when the block defines neither, in which case callers leave the Media key
    out."""
    return c.brand_card_media()


def _with_media(card):
    """Add the brand banner to a card dict when there is one."""
    media = _brand_media()
    if media:
        card["Media"] = media
    return card


def _nav_suggestions():
    """The navigation chip row on the last card: one reply chip per entry of the
    selected brand's `homeMenu` (content/brand.md), in order. Message-level
    suggestions cap at 11 and homeMenu is already cut to ten, so there is room
    to spare. Pushing a specific vignette to the device is the dashboard's job.
    The postbacks are existing `home_*` ids, so channel_adapter routing is
    unchanged. Returns [] when the brand defines no homeMenu."""
    return c.build_suggestions(
        [
            {"type": "reply", "text": e["label"], "postback": e["postback"]}
            for e in c.home_menu()
        ],
        max_count=c.rcs_limit("suggestionsPerMessage"),
    )


def _welcome():
    brand = c.brand_name()
    menu = c.home_menu()
    # The first two tiles double as card-level "try it" chips on the intro card.
    intro_chips = [
        {"Reply": {"Text": e["label"], "PostbackData": e["postback"]}} for e in menu[:2]
    ]
    nav = _nav_suggestions()

    # Card 1 — frame the whole thread: this is an AWS EUM RCS demo of a
    # fictitious brand, and here is what RCS is. One short paragraph (at most
    # 200 characters with the brand name) so the banner, text and chips fit one
    # screen; the line of business lives on the Home_Menu. Card-level chips (the
    # brand's first two homeMenu tiles) offer concrete "try it" jumps; the fuller
    # navigation row is on the last card.
    intro_card = {
        "Title": f"Welcome to the {brand} RCS demo",
        "Description": (
            f"An AWS End User Messaging RCS demo for the fictitious brand {brand}. "
            "No real data here. RCS brings branded cards, images and reply chips "
            "to Messages."
            + (" Tap a chip to try it." if intro_chips else "")
        ),
    }
    _with_media(intro_card)
    if intro_chips:
        intro_card["Suggestions"] = intro_chips
    intro = {
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": intro_card,
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
    trust_card = _with_media(
        {
            "Title": "Verified brand, and your choice to be here",
            "Description": (
                "A business registers its RCS agent with carriers and Google, "
                "which verify the brand name, logo and color shown above, so "
                "the sender is hard to impersonate.\n\n"
                "You opt in by starting this chat and can opt out anytime by "
                "texting STOP. End User Messaging answers STOP and HELP itself."
            ),
        }
    )
    brand_trust = {
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": trust_card,
            }
        },
    }

    # Card 3 — SMS fallback, told truthfully for THIS deployment, then the
    # compact navigation chip row that stands in for the old carousel menu.
    if c.sms_fallback_active():
        fallback_para = (
            "SMS fallback is ENABLED here. If an RCS message can't reach your "
            "device, it is re-sent as SMS from a backup number, without the "
            "cards, images and chips."
        )
    else:
        fallback_para = (
            "SMS fallback is OFF here. When enabled (it needs an SMS-capable "
            "number), an RCS message that can't reach a device is re-sent as "
            "SMS, minus cards and chips."
        )

    if _has_assistant():
        closing = (
            "Pick a capability below, or just ask a question -- an AI "
            "assistant can answer."
            if nav
            else "Just ask a question -- an AI assistant can answer."
        )
    else:
        # No default assistant: typed text returns the Home_Menu, so make no AI
        # claim and do not invite a question.
        closing = "Pick a capability below." if nav else "More is coming soon."
    fallback_body = _with_media(
        {
            "Title": "When RCS is not available: SMS fallback",
            "Description": (
                f"{fallback_para}\n\n"
                "It lets a business adopt RCS without leaving anyone behind.\n\n"
                f"{closing}"
            ),
        }
    )
    fallback_card = {
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": fallback_body,
            }
        },
        # Private key, popped by channel_adapter before the send (like _ttl and
        # _fallback_body): this last card carries the navigation chips, so it
        # gets no Start Over chip.
        "_no_reset": True,
    }
    if nav:
        fallback_card["Suggestions"] = nav

    return [intro, brand_trust, fallback_card]


def _truncate(text, limit):
    """Cut text to `limit` characters, ending in an ellipsis when it was cut."""
    return text if len(text) <= limit else text[: max(limit - 1, 0)].rstrip() + "…"


def home_menu(phone, phone_hash):
    """The Home_Menu: where a conversation Reset lands. One short card with the
    brand name and its line of business over the brand's navigation chips (the
    `homeMenu` tiles of content/brand.md), on the brand's card image. Unlike the
    Welcome_Intro it teaches nothing and carries no card-level chips. Like
    on_start it touches no per-recipient state."""
    nav = _nav_suggestions()
    lob = (c.line_of_business() or "").strip()
    if lob and not lob.endswith((".", "!", "?")):
        lob += "."
    if _has_assistant():
        prompt = (
            "Pick one below, or ask me a question." if nav else "Just ask me a question."
        )
    else:
        prompt = "Pick one below." if nav else "More is coming soon."
    description = f"{lob}\n\n{prompt}" if lob else prompt

    card = _with_media(
        {
            "Title": _truncate(c.brand_name(), c.rcs_limit("richCardTitleChars")),
            "Description": _truncate(
                description, c.rcs_limit("richCardDescriptionChars")
            ),
        }
    )
    message = {
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": card,
            }
        },
        # Private key, popped by channel_adapter before the send: the Home_Menu
        # is where a Reset lands, so it offers no Start Over chip.
        "_no_reset": True,
    }
    if nav:
        message["Suggestions"] = nav
    return [message]


def on_postback(phone, phone_hash, postback_data):
    # Unknown-trigger fallback routes back here. channel_adapter routes the
    # Main Menu chip (home_menu) to the conversation Reset, which sends the
    # Home_Menu itself after clearing state; the branch is kept so a direct call
    # still returns the same Home_Menu.
    if postback_data == "home_menu":
        return home_menu(phone, phone_hash)
    return None
