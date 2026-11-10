"""Shared welcome card for the AnyBuild app-side hellos (not a vignette).

Each AnyBuild app side (builder, supplier) opens with a short welcome: who is
writing, what kind of messages to expect, how to stop them, and a few chips into
the vignettes that side uses. The copy lives in content/construction.md under
`hello`; hello_builder.py and hello_supplier.py are thin wrappers that pick the
side, because a home-menu tile calls on_start with no vignette id.

The welcome is transactional: it carries no offer. STOP and HELP are answered
by the keyword replies registered on the RCS agent, so this card only tells the
person they exist.
"""

import common as c

_NOTICE = "Message frequency varies. Msg & data rates may apply. Reply STOP to opt out, HELP for help."


def hello_card(side: str, chips: list):
    """The welcome message for `side` ("builder" or "supplier") with reply chips
    `[(label, postback)]` into that side's vignettes (at most four)."""
    h = c.hello(side)
    if not h:
        return [{"Content": {"TextMessage": {"Body": (
            "No welcome copy is set up yet. Add `hello` in content/construction.md."
        )}}}]
    bullets = "\n".join(f"- {b}" for b in h.get("bullets", []))
    desc = f"{h.get('intro', '')}\n\n{bullets}\n\n{_NOTICE}".strip()
    card = {"Title": h.get("title", c.brand_name())[:200], "Description": desc[:2000]}
    media = c.brand_card_media()
    if media:
        card["Media"] = media
    card["Suggestions"] = [
        {"Reply": {"Text": label[:25], "PostbackData": postback}} for label, postback in chips[:4]
    ]
    return [{
        "Content": {"RichCard": {"CardOrientation": "VERTICAL", "CardContent": card}},
        # SMS fallback for the welcome; inactive unless deployed with
        # -c smsFallbackNumber=+1… (see common.send_rcs). The welcome is mostly
        # text already, so it survives as SMS with its opt-out line intact.
        "_fallback_body": f"{h.get('intro', '')} {_NOTICE}",
    }]
