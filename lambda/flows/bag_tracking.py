"""Bag tracking — deterministic, two-way, location-aware (AnyTravel).

A checked bag missed its flight. The airline tells the traveler where it is and
when it lands, and asks where to deliver it: to the hotel on the trip, or to a
location the traveler shares with RequestLocation (one tap, sent only if the
traveler taps; it is not tracking). A shared location is routed here by
channel_adapter.handle_location while this vignette is the active flow.

Data come from content/flights.md (`bag`); the hotel comes from
content/hotels.md through `deliveryPropertyId`.

Triggers: `Start: Bag_Tracking`, or the `home_bags` postback.
Postback prefix: bag_
"""

import common as c


def on_start(phone, phone_hash):
    return _notice()


def on_trigger(phone, phone_hash, vignette):
    return _notice()


def preview_message():
    return _notice()


def _hotel():
    return c.hotel_property_by_id(c.bag().get("deliveryPropertyId", "")) or {}


def _notice():
    b = c.bag()
    if not b:
        return [{"Content": {"TextMessage": {"Body": "No bag to track. Add one in content/flights.md."}}}]
    hotel = _hotel()
    chips = []
    if hotel:
        chips.append({"Reply": {"Text": "Deliver to My Hotel", "PostbackData": "bag_to_hotel"}})
    chips += [
        {"RequestLocation": {"Text": "Share Delivery Spot", "PostbackData": "bag_share"}},
        {"DialPhone": {"Text": "Call Baggage Service", "PostbackData": "bag_call",
                       "PhoneNumber": c.member_services_phone()}},
    ]
    airport = b.get("airportInfo", {})
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": f"Your bag is on its way: tag {b.get('tag', '')}"[:200],
                    "Description": (
                        f"{b.get('description', 'Your bag')} missed flight {b.get('flightNumber', '')}. "
                        f"It's on {b.get('nextFlight', '')}, landing at {airport.get('code', '')} "
                        f"at {b.get('nextArriveLabel', '')}, and is held at the "
                        f"{b.get('office', 'baggage office')}.\n\n"
                        f"We can deliver it {b.get('deliveryWindow', 'later today')} at no cost. "
                        "Where should it go?"
                    )[:2000],
                    "Suggestions": chips,
                },
            }
        },
        # SMS fallback: the delivery choice needs the chips, so the SMS gives
        # the status and the phone line. Inactive unless deployed with
        # -c smsFallbackNumber=+1…; see common.send_rcs.
        "_fallback_body": (
            f"{c.brand_name()}: your bag {b.get('tag', '')} arrives on {b.get('nextFlight', '')} "
            f"at {b.get('nextArriveLabel', '')}. To arrange delivery, call {c.member_services_phone()}."
        ),
    }]


def _scheduled(where):
    b = c.bag()
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "Delivery scheduled",
                    "Description": (
                        f"Bag {b.get('tag', '')} will be delivered to {where}, "
                        f"{b.get('deliveryWindow', 'later today')}.\n\n"
                        "We'll message you when the courier is on the way."
                    )[:2000],
                },
            }
        },
    }]


def location_update(phone_hash, lat, lon):
    """The reply to a location shared while this vignette is active: deliver
    there, and say how far that is from the arrival airport."""
    airport = c.bag().get("airportInfo", {})
    try:
        miles = c.haversine_miles(airport.get("lat", lat), airport.get("lng", lon), lat, lon)
        where = f"the location you shared, about {miles:.0f} mi from {airport.get('code', 'the airport')}"
    except (TypeError, ValueError):
        where = "the location you shared"
    return _scheduled(where)


def on_freetext(phone, phone_hash, text):
    """A typed delivery address, or "send it to my hotel". The model only reads
    the address; it must look like a street address (a number and a name) before
    the delivery is scheduled, else the traveler is asked again with the chips."""
    if not c.bag():
        return None
    data = c.ai_extract(
        "The traveler was asked where to deliver a delayed bag: to their hotel, or to another "
        'address. Return {"relevant": true|false, "to_hotel": true|false, '
        '"address": "the street address as one line, or empty", '
        '"note": "delivery instructions under 60 characters, or empty"}.',
        text,
    )
    if data is None:
        return [{"Content": {"TextMessage": {"Body": "I couldn't read that. Use the options below."}}}] + _notice()
    if not data.get("relevant"):
        return None
    if data.get("to_hotel") is True and _hotel():
        return on_postback(phone, phone_hash, "bag_to_hotel")
    address = c.extracted_text(data, "address", 120)
    if not (len(address) >= 8 and any(ch.isdigit() for ch in address) and any(ch.isalpha() for ch in address)):
        return [{"Content": {"TextMessage": {"Body": (
            "What's the full street address, with the number? Or use an option below."
        )}}}] + _notice()
    note = c.extracted_text(data, "note", 60)
    return _scheduled(address + (f" ({note})" if note else ""))


def on_postback(phone, phone_hash, postback_data):
    if postback_data == "bag_to_hotel":
        hotel = _hotel()
        if hotel:
            return _scheduled(f"{hotel.get('name', 'your hotel')}, {hotel.get('address', '')}".rstrip(", "))
        return _notice()
    return None
