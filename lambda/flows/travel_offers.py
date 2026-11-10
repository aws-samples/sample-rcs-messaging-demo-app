"""Travel Offers — deterministic promotional carousel (AnyTravel).

An event-driven marketing send: the brand opens with a short welcome message,
then pushes a carousel of booking offers that coincide with public events (a concert, a game, a marathon) to an opted-in
member. Each card ties an event to a nearby property, a member rate, and the
stay dates implied by the event.

Selecting an offer ("Book This Stay") hands straight off to the Room Booking
assistant with the property and the offer's dates already filled in, so the
guest never re-enters what the offer already implied — they only confirm guest
count and the booking. That handoff lives in channel_adapter.handle_postback (an
agentic flow can't be entered from a deterministic flow module), so this module
deliberately does NOT handle `offers_book_*` itself.

Offers and properties come from content/hotels.md → offers, read through the
selected brand's hotel accessors in common.py. The brand name on every card is
read from content via c.brand_name(); no brand literal appears in this module.

Promotional content is kept clean: the brand is present on every card and there
is no prohibited content. This is a demo of an opt-in member offer; like the
rest of the demo it does not implement STOP/HELP keyword handling.

Triggers: `Start: Travel_Offers`, or the `home_offers` postback.
Postback prefix: offers_
"""

import common as c


def _brand():
    return c.brand_name()


def on_start(phone, phone_hash):
    return _offers_carousel()


def on_trigger(phone, phone_hash, vignette):
    return _offers_carousel()


def _offer_card(offer):
    prop = c.hotel_property_by_id(offer.get("propertyId", "")) or {}
    rate = float(offer.get("memberRate", 0) or 0)
    desc = (
        f"{offer.get('event', '')}\n"
        f"{prop.get('name', '')} — {prop.get('city', '')}\n\n"
        f"Member rate ${rate:.0f}/night\n"
        f"Includes: {offer.get('perk', '')}"
    )
    return {
        "Title": offer.get("headline", "Travel Offer")[:200],
        "Description": desc[:2000],
        "Media": {"FileUrl": c.resolve_media(offer.get("image", "")), "Height": "MEDIUM"},
        # One clear CTA. The handoff into the booking assistant (with this
        # offer's property + dates pre-filled) is done in
        # channel_adapter.handle_postback, which intercepts offers_book_* before
        # this flow's on_postback sees it.
        "Suggestions": [
            {"Reply": {"Text": "Book This Stay", "PostbackData": f"offers_book_{offer['id']}"}},
        ],
    }


def _offers_carousel():
    offers = c.travel_offers()[:10]  # carousel supports 2–10 cards; [:10] caps the top
    cards = [_offer_card(o) for o in offers]
    # Carousel guard: a 0- or 1-card carousel is invalid (the 2–10 bound), so
    # degrade to a plain text message rather than build an invalid carousel.
    if len(cards) < 2:
        return [{"Content": {"TextMessage": {"Body": (
            "No member offers are available right now. Add offers in content/hotels.md."
        )}}}]
    names = ", ".join(cd["Title"] for cd in cards[:3])
    # A short welcome ahead of the carousel, so the guest knows what the swipeable
    # cards are before they see them. Its own message, with no chips: the Start
    # Over chip goes on the last message of the batch, which is the carousel.
    intro = {"Content": {"TextMessage": {"Body": c.offers_intro()}}}
    return [intro, {
        "Content": {"Carousel": {"CardWidth": "MEDIUM", "CardContents": cards}},
        # No message-level chips here: channel_adapter attaches the single
        # Start Over chip (reset_conversation) to the last message of the batch.
        # SMS fallback for the entry message. A shoppable carousel degrades to a
        # sentence — SMS has neither the images nor the per-card chips — so this
        # names a couple of offers and a number instead of pretending the
        # carousel arrived. Inactive unless deployed with -c smsFallbackNumber=
        # +1…; see common.send_rcs.
        "_fallback_body": (
            f"{_brand()}: member travel offers tied to upcoming events, including "
            f"{names}. Booking needs rich messaging, which isn't available on your "
            f"device right now. Call {c.member_services_phone()} to book."
        ),
    }]


def on_postback(phone, phone_hash, postback_data):
    # Note: offers_book_* is intentionally NOT handled here — it is intercepted
    # in channel_adapter.handle_postback, which hands off to the agentic Room
    # Booking assistant with the offer's property and dates pre-filled. Entering
    # an AI flow needs the AI helpers (invoke_ai/send_ai_response), which a
    # deterministic flow module does not have.
    #
    # offers_browse (the retired "Start Over" chip on older messages) is not
    # handled here either: channel_adapter.handle_postback routes it to the
    # global Reset before this flow sees it.
    return None
