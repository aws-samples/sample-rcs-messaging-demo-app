"""Delivery Location — "where is the framing lumber?", deterministic (AnyBuild).

After a supplier drops a load, the builder sees where it was left: a map pin
with a label ("Driveway, north side") and the supplier's drop photo. Three
replies cover what actually happens on a jobsite:

- "Found it": the load is where it was said to be.
- "Not here": the driver is asked to share where he left it.
- "We moved it": someone on site moved the load and shares the new spot.

Both of the last two use RequestLocation. The tap opens the handset's own
location picker and the answer comes back as an inbound LOCATION event
(channel_adapter.handle_location -> location_update below), which updates the
drop spot and shows the new pin and its distance from the lot. RequestLocation
is a one-time answer the person chooses to give. It is not tracking, and the
reply is coordinates only: there is no street address, so the label is our own.

This demo has one phone, so it plays both people: the "Not here" reply sends the
driver's prompt to the same handset. In a real deployment the driver prompt goes
to the supplier's driver.

Triggers: `Start: Delivery_Location`, or the `home_delivery` postback.
Postback prefix: delivery_
"""

import common as c

_STATE = "delivery"


def on_start(phone, phone_hash):
    return _delivered(phone_hash)


def on_trigger(phone, phone_hash, vignette):
    return _delivered(phone_hash)


def preview_message():
    return _delivered("")


def _spot(phone_hash):
    """(label, lat, lng) of the current drop spot: a shared location when there
    is one, else the one in the content."""
    d = c.delivery()
    st = c.get_build_state(phone_hash, _STATE)
    if st.get("lat") is not None:
        return st.get("label", "Shared location"), float(st["lat"]), float(st["lng"])
    return d.get("droppedLabel", ""), d.get("droppedLat", 0), d.get("droppedLng", 0)


def _show_chip(phone_hash, text="Show Drop Spot"):
    label, lat, lng = _spot(phone_hash)
    return {"ShowLocation": {
        "Text": text[:25], "PostbackData": "delivery_show_spot",
        "Latitude": lat, "Longitude": lng,
        "Label": f"{c.delivery().get('po', 'Load')} \u2014 {label}"[:100],
    }}


def _delivered(phone_hash):
    d, sup, site = c.delivery(), c.supplier(), c.site()
    if not d:
        return [{"Content": {"TextMessage": {"Body": (
            "No delivery is set up yet. Add `delivery` in content/construction.md."
        )}}}]
    label, _, _ = _spot(phone_hash)
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": f"Delivered: {d.get('po', '')}"[:200],
                    "Description": (
                        f"{d.get('items', '')}\n"
                        f"Left at: {label} at {d.get('droppedTime', '')}\n"
                        f"{site.get('lot', '')}, {site.get('address', '')}\n"
                        f"Driver: {sup.get('driver', '')}, {sup.get('name', '')}"
                    )[:2000],
                    "Media": {"FileUrl": c.resolve_media("media/anybuild/delivery-drop.png"), "Height": "MEDIUM"},
                    "Suggestions": [
                        _show_chip(phone_hash),
                        {"Reply": {"Text": "Found It", "PostbackData": "delivery_found"}},
                        {"Reply": {"Text": "Not Here", "PostbackData": "delivery_missing"}},
                        {"Reply": {"Text": "We Moved It", "PostbackData": "delivery_moved"}},
                    ],
                },
            }
        },
        # SMS fallback for the entry message; inactive unless deployed with
        # -c smsFallbackNumber=+1… (see common.send_rcs). A map pin does not
        # survive as SMS, so the label and address carry the answer.
        "_fallback_body": (
            f"{c.brand_name()}: {d.get('po', '')} ({d.get('items', '')}) was left at "
            f"{label} at {site.get('address', '')} at {d.get('droppedTime', '')}. "
            f"Not there? Call {c.member_services_phone()}."
        ),
    }]


def _driver_prompt():
    d, sup = c.delivery(), c.supplier()
    return {
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": f"Where did you leave {d.get('po', 'the load')}?"[:200],
                    "Description": (
                        f"{sup.get('driver', 'Driver')}: the builder can't find "
                        f"{d.get('items', 'the load')}. Tap to share where it was left. "
                        "(Driver view.)"
                    )[:2000],
                    "Suggestions": [{"RequestLocation": {"Text": "Share Drop Location", "PostbackData": "delivery_share"}}],
                },
            }
        },
    }


def location_update(phone_hash, lat, lon):
    """The reply to a shared location while this vignette is the active flow:
    store it as the drop spot and show the new pin with its distance from the lot."""
    d, site = c.delivery(), c.site()
    c.set_build_state(phone_hash, _STATE, lat=float(lat), lng=float(lon), label="Shared location")
    miles = c.haversine_miles(site.get("lat", lat), site.get("lng", lon), lat, lon)
    away = "less than 0.1 mi" if miles < 0.1 else f"{miles:.1f} mi"
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "Drop Spot Updated",
                    "Description": (
                        f"{d.get('po', 'The load')} is now marked at the shared location, "
                        f"{away} from {site.get('lot', 'the lot')}.\n\n"
                        "Everyone on this delivery sees the new pin."
                    ),
                    "Suggestions": [_show_chip(phone_hash, "Show New Spot")],
                },
            }
        },
    }]


def on_freetext(phone, phone_hash, text):
    """A typed reply about the load: "found it", "it's not here", or "we moved it
    behind the garage by the dumpster". The model only classifies it and writes a
    short place label; found and missing do exactly what their chips do, and a
    typed spot becomes the drop label (the pin stays where it was until someone
    shares a location)."""
    d = c.delivery()
    if not d:
        return None
    label, lat, lng = _spot(phone_hash)
    data = c.ai_extract(
        f"The user was shown where a delivery ({d.get('po', '')}, {d.get('items', '')}) was left: "
        f"\"{label}\". They typed a reply. Return {{\"relevant\": true|false, "
        '"intent": "found"|"missing"|"moved", '
        '"drop_note": "where the load is now as a short place label, under 50 characters, '
        'for example Behind the garage, by the dumpster, or empty"}.',
        text,
    )
    if data is None:
        return [{"Content": {"TextMessage": {"Body": "I couldn't read that. Use the options below."}}}] \
            + _delivered(phone_hash)
    if not data.get("relevant"):
        return None
    intent = data.get("intent")
    if intent == "found":
        return on_postback(phone, phone_hash, "delivery_found")
    if intent == "missing":
        return on_postback(phone, phone_hash, "delivery_missing")
    note = c.extracted_text(data, "drop_note", 50)
    if intent == "moved" and not note:
        return on_postback(phone, phone_hash, "delivery_moved")
    if not note:
        return None
    c.set_build_state(phone_hash, _STATE, lat=float(lat), lng=float(lng), label=note)
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "Drop Spot Updated",
                    "Description": (
                        f"{d.get('po', 'The load')} is now marked: {note}.\n\n"
                        "Everyone on this delivery sees the new note. Share the exact spot to move the pin."
                    ),
                    "Suggestions": [
                        {"RequestLocation": {"Text": "Share New Location", "PostbackData": "delivery_share_new"}},
                    ],
                },
            }
        },
    }]


def on_postback(phone, phone_hash, postback_data):
    if postback_data == "delivery_found":
        d = c.delivery()
        return [{
            "Content": {"TextMessage": {"Body": f"Great. {d.get('po', 'The delivery')} is marked received."}},
            "Suggestions": [{"Reply": {"Text": "Report Damage", "PostbackData": "home_evidence"}}],
        }]
    if postback_data == "delivery_missing":
        sup = c.supplier()
        return [
            {"Content": {"TextMessage": {"Body": (
                f"Sorry about that. We've asked {sup.get('driver', 'the driver')} where he left "
                f"{c.delivery().get('po', 'the load')}."
            )}}},
            _driver_prompt(),
        ]
    if postback_data == "delivery_moved":
        return [{
            "Content": {"TextMessage": {"Body": "Thanks. Share the load's new spot so everyone sees it."}},
            "Suggestions": [{"RequestLocation": {"Text": "Share New Location", "PostbackData": "delivery_share_new"}}],
        }]
    return None
