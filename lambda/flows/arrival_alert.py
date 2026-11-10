"""Arrival Alert — a geofence event becomes a message, deterministic (AnyBuild).

A supplier's truck crosses a geofence around the community, and the site is told
before it arrives: what is on the truck, how long until it gets there, where it
will be dropped and who is driving. The site replies with one tap, "Gate is
open" or "Hold delivery", and the supplier's driver is told. After "Gate is
open" the card offers the Delivery Location vignette, which picks up when the
load is down.

THE GEOFENCE IS NOT AN RCS FEATURE. RCS has no geofencing and no continuous
location. The customer's own system detects the fence (GPS from a telematics
unit or a driver app) and calls the send; RCS carries the message. This demo
stands in for that system with the dashboard's Send button, which pushes
`Start: Arrival_Alert` to the handset exactly as a real event would. The
`geofence_trigger` entry in content/rcs-features.json says the same, so the
dashboard teaches it too.

Triggers: `Start: Arrival_Alert`, or the `home_arrival` postback.
Postback prefix: arrive_
"""

import common as c


def on_start(phone, phone_hash):
    return _alert()


def on_trigger(phone, phone_hash, vignette):
    return _alert()


def preview_message():
    return _alert()


def _directions(site):
    return {"ShowLocation": {
        "Text": "Directions to Site", "PostbackData": "arrive_directions",
        "Latitude": site.get("lat", 0), "Longitude": site.get("lng", 0),
        "Label": f"{site.get('lot', 'Jobsite')} \u2014 {site.get('address', '')}"[:100],
    }}


def _alert():
    a, sup, site = c.arrival(), c.supplier(), c.site()
    if not a:
        return [{"Content": {"TextMessage": {"Body": (
            "No arrival is set up yet. Add `arrival` in content/construction.md."
        )}}}]
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": f"Delivery Arriving: {a.get('po', '')}"[:200],
                    "Description": (
                        f"{sup.get('name', 'The supplier')}'s truck just entered the "
                        f"{a.get('geofenceName', 'site')} geofence ({a.get('geofenceMiles', '')} mi).\n\n"
                        f"Load: {a.get('items', '')}\n"
                        f"About {a.get('etaMinutes', '')} minutes out\n"
                        f"Drop-off: {a.get('dropLabel', '')}, {site.get('lot', '')}\n"
                        f"Driver: {sup.get('driver', '')}"
                    )[:2000],
                    "Media": {"FileUrl": c.resolve_media("media/anybuild/arrival.png"), "Height": "MEDIUM"},
                    "Suggestions": [
                        {"Reply": {"Text": "Gate Is Open", "PostbackData": "arrive_open"}},
                        {"Reply": {"Text": "Hold Delivery", "PostbackData": "arrive_hold"}},
                        _directions(site),
                    ],
                },
            }
        },
        # SMS fallback for the entry message; inactive unless deployed with
        # -c smsFallbackNumber=+1… (see common.send_rcs). The event itself
        # survives as a sentence; the one-tap replies do not.
        "_fallback_body": (
            f"{c.brand_name()}: {sup.get('name', 'a supplier')} truck arriving at "
            f"{site.get('lot', 'your site')} in about {a.get('etaMinutes', '')} min "
            f"({a.get('po', '')}). Reply or call {c.member_services_phone()} to hold the delivery."
        ),
    }]


def _proceed():
    a, sup = c.arrival(), c.supplier()
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "Gate Open",
                    "Description": (
                        f"{sup.get('driver', 'The driver')} has been told to proceed to "
                        f"{a.get('dropLabel', 'the drop-off')}. We'll message you when the load is down."
                    ),
                    "Suggestions": [
                        {"Reply": {"Text": "See Drop Location", "PostbackData": "home_delivery"}},
                    ],
                },
            }
        },
    }]


def on_postback(phone, phone_hash, postback_data):
    if postback_data in ("arrive_open", "arrive_release"):
        return _proceed()
    if postback_data == "arrive_hold":
        sup = c.supplier()
        return [{
            "Content": {"TextMessage": {"Body": (
                f"Held. {sup.get('driver', 'The driver')} will wait at the entrance. "
                "Tap Release when you're ready for the truck."
            )}},
            "Suggestions": [{"Reply": {"Text": "Release Delivery", "PostbackData": "arrive_release"}}],
        }]
    return None
