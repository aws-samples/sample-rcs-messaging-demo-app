"""Flight status alert — deterministic, event-driven, time-sensitive (AnyTravel).

The airline's operations system detects a gate change and a delay and sends one
alert (the dashboard's Send button stands in for that system). The alert is only
useful while it is current, so it carries a short TimeToLive: if RCS cannot
deliver it promptly, the platform gives up and, when the stack has an SMS
fallback number, sends the SMS instead of a late card. The card offers the
terminal on a map and a call to Traveler Services.

Data come from content/flights.md (`flight` and `statusChange`).

Triggers: `Start: Flight_Status`, or the `home_flight_status` postback.
Postback prefix: fstatus_
"""

import common as c

# How long RCS gets to deliver the alert (SendRcsMessage TimeToLive). A gate
# change read after boarding has started is worse than useless, so a late card
# should give way to the SMS fallback.
DELIVERY_TTL_SECONDS = 300


def on_start(phone, phone_hash):
    return _alert()


def on_trigger(phone, phone_hash, vignette):
    return _alert()


def preview_message():
    return _alert()


def _alert():
    f, s = c.next_flight(), c.flight_status_change()
    if not f or not s:
        return [{"Content": {"TextMessage": {"Body": "No flight status to show. Add one in content/flights.md."}}}]
    origin = f["origin"]
    route = f"{origin.get('code', '')} → {f['dest'].get('code', '')}"
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": f"Gate change: flight {f.get('number', '')} now at {s.get('newGate', '')}"[:200],
                    "Description": (
                        f"{route} · {f.get('date', '')}\n\n"
                        f"New gate: {s.get('newGate', '')} (was {f.get('gate', '')})\n"
                        f"New departure: {s.get('newDepartLabel', '')} (was {f.get('departLabel', '')})\n"
                        f"Boarding: {s.get('newBoardingLabel', '')}\n\n"
                        f"The change is due to {s.get('reason', 'an operational update')}. "
                        "Your seat and boarding group stay the same."
                    )[:2000],
                    "Suggestions": [
                        {"Reply": {"Text": "Got It", "PostbackData": "fstatus_ack"}},
                        {"ShowLocation": {
                            "Text": "Airport Map", "PostbackData": "fstatus_map",
                            "Latitude": origin.get("lat", 0), "Longitude": origin.get("lng", 0),
                            "Label": origin.get("name", ""),
                        }},
                        {"DialPhone": {
                            "Text": "Call Traveler Services", "PostbackData": "fstatus_call",
                            "PhoneNumber": c.member_services_phone(),
                        }},
                    ],
                },
            }
        },
        "_ttl": DELIVERY_TTL_SECONDS,
        # SMS fallback: the whole alert fits in one text, which is what makes it
        # a good fallback. Inactive unless deployed with -c smsFallbackNumber=+1…;
        # see common.send_rcs.
        "_fallback_body": (
            f"{c.brand_name()}: flight {f.get('number', '')} {route} now departs "
            f"{s.get('newDepartLabel', '')} from gate {s.get('newGate', '')} "
            f"(boarding {s.get('newBoardingLabel', '')}). Questions: {c.member_services_phone()}."
        ),
    }]


def on_postback(phone, phone_hash, postback_data):
    if postback_data == "fstatus_ack":
        return [{"Content": {"TextMessage": {"Body": (
            "Thanks. We'll message you here if anything else changes before you board."
        )}}}]
    return None
