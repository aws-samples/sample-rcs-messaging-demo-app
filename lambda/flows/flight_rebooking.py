"""Disruption rebooking — deterministic carousel with a hotel hand-off (AnyTravel).

When a flight is cancelled the airline messages the traveler first, then pushes
a carousel of the next available flights. One tap rebooks at no cost and returns
a confirmation with an Add to Calendar chip. An option that leaves tomorrow also
offers a hotel tonight near the airport: that chip (`rebook_hotel`) hands off to
the Room Booking assistant with the property and tonight's dates filled in. The
hand-off lives in channel_adapter.handle_postback, because entering an AI-driven
flow needs the AI helpers that a flow module does not have, so this module does
not handle `rebook_hotel` itself.

Data come from content/flights.md (`disruption`); the hotel comes from
content/hotels.md through `overnightPropertyId`.

Triggers: `Start: Flight_Rebooking`, or the `home_rebooking` postback.
Postback prefix: rebook_
"""

import re

import common as c

PICK_PREFIX = "rebook_pick_"


def on_start(phone, phone_hash):
    return _disruption()


def on_trigger(phone, phone_hash, vignette):
    return _disruption()


def preview_message():
    return _disruption()


def _arrive_text(o):
    days = int(o.get("arriveDayDelta", 0) or 0)
    return f"{o.get('arriveLabel', '')}" + (f" (+{days} day)" if days == 1 else f" (+{days} days)" if days > 1 else "")


def _option_card(o):
    seats = int(o.get("seatsLeft", 0) or 0)
    return {
        "Title": f"{o.get('date', '')} · {o.get('departLabel', '')}"[:200],
        "Description": (
            f"Flight {o.get('number', '')}\n"
            f"{o['origin'].get('code', '')} {o.get('departLabel', '')} → "
            f"{o['dest'].get('code', '')} {_arrive_text(o)}\n"
            f"{o.get('stops', '')}"
            + (f" · {seats} seats left" if seats else "")
            + ("\nLeaves tomorrow: hotel tonight available" if o.get("overnight") else "")
        )[:2000],
        "Suggestions": [{"Reply": {"Text": "Rebook This Flight", "PostbackData": f"{PICK_PREFIX}{o['id']}"}}],
    }


def _options_message(options):
    """The options as a carousel (2 to 10 cards), or one rich card for one."""
    if len(options) == 1:
        return {"Content": {"RichCard": {"CardOrientation": "VERTICAL", "CardContent": _option_card(options[0])}}}
    return {"Content": {"Carousel": {"CardWidth": "MEDIUM", "CardContents": [_option_card(o) for o in options[:10]]}}}


def _disruption():
    dz = c.disruption()
    cancelled = dz.get("cancelled") or {}
    options = dz.get("options", [])[:10]  # a carousel holds 2 to 10 cards
    if not cancelled or len(options) < 2:
        return [{"Content": {"TextMessage": {"Body": (
            "No rebooking options to show. Add a disruption in content/flights.md."
        )}}}]
    route = f"{cancelled['origin'].get('code', '')} → {cancelled['dest'].get('code', '')}"
    notice = {"Content": {"TextMessage": {"Body": (
        f"We're sorry. Flight {cancelled.get('number', '')} {route} at "
        f"{cancelled.get('departLabel', '')} tonight is cancelled because of "
        f"{dz.get('reason', 'an operational issue')}.\n\n"
        "You're protected: pick any flight below to rebook at no cost, or tell me what "
        "works for you (for example, \"I need to land before noon\"). Your seat "
        "preference and bags move with you."
    )}}}
    return [notice, {
        **_options_message(options),
        # SMS fallback: the carousel's value is one-tap rebooking, which SMS
        # cannot carry, so the SMS names the first option and the phone line.
        # Inactive unless deployed with -c smsFallbackNumber=+1…; see
        # common.send_rcs.
        "_fallback_body": (
            f"{c.brand_name()}: flight {cancelled.get('number', '')} {route} tonight is cancelled. "
            f"The next flight is {options[0].get('number', '')} at {options[0].get('departLabel', '')}. "
            f"To rebook at no cost, call {c.member_services_phone()}."
        ),
    }]


def _rebooked(o):
    dz = c.disruption()
    prop = c.hotel_property_by_id(dz.get("overnightPropertyId", "")) or {}
    route = f"{o['origin'].get('code', '')} → {o['dest'].get('code', '')}"
    chips = [{"CreateCalendarEvent": {
        "Text": "Add to Calendar", "PostbackData": "rebook_cal",
        "Title": f"Flight {o.get('number', '')} {route}",
        "Description": (
            f"{o['origin'].get('name', '')} to {o['dest'].get('name', '')}. "
            f"Confirmation {c.flight_confirmation()}."
        ),
        "StartTime": o.get("departEpoch", 0),
        "EndTime": o.get("arriveEpoch", o.get("departEpoch", 0)),
    }}]
    overnight = ""
    if o.get("overnight") and prop:
        overnight = (
            f"\n\nYour new flight leaves tomorrow. {prop.get('name', '')} is near the "
            "airport if you need a room tonight."
        )
        chips.append({"Reply": {"Text": "Book a Hotel Tonight", "PostbackData": "rebook_hotel"}})
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "You're rebooked ✅",
                    "Description": (
                        f"Flight {o.get('number', '')} · {route}\n"
                        f"{o.get('date', '')} · departs {o.get('departLabel', '')}, "
                        f"arrives {_arrive_text(o)}\n"
                        f"{o.get('stops', '')}\n\n"
                        f"Confirmation {c.flight_confirmation()} is unchanged, and there "
                        f"is no fee for this change.{overnight}"
                    )[:2000],
                    "Suggestions": chips,
                },
            }
        },
    }]


_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _hhmm(value):
    v = value.strip() if isinstance(value, str) else ""
    return v if _HHMM.match(v) else ""


def on_freetext(phone, phone_hash, text):
    """A typed preference, "I need to land before noon" or "nonstop tomorrow
    morning". The model only turns it into filters (times, nonstop, day); the
    options are filtered here, so it can never offer a flight that isn't listed."""
    dz = c.disruption()
    options = dz.get("options", [])
    if len(options) < 2:
        return None
    data = c.ai_extract(
        "The traveler's flight was cancelled and they were shown the next flights. They typed "
        'what works for them. Return {"relevant": true|false, '
        '"arrive_before": "HH:MM 24-hour, or empty", "depart_after": "HH:MM, or empty", '
        '"depart_before": "HH:MM, or empty", "nonstop": true|false, '
        '"day": "today"|"tomorrow"|""}.',
        text,
    )
    if data is None:
        return [{"Content": {"TextMessage": {"Body": "I couldn't read that. Here are all the options."}}},
                _options_message(options[:10])]
    if not data.get("relevant"):
        return None
    arrive_before, depart_after, depart_before = (
        _hhmm(data.get("arrive_before")), _hhmm(data.get("depart_after")), _hhmm(data.get("depart_before")))
    day = {"today": 0, "tomorrow": 1}.get(data.get("day"))
    nonstop = data.get("nonstop") is True
    asked = []
    if arrive_before:
        asked.append(f"land before {c.format_time_12h(arrive_before)}")
    if depart_after:
        asked.append(f"leave after {c.format_time_12h(depart_after)}")
    if depart_before:
        asked.append(f"leave before {c.format_time_12h(depart_before)}")
    if nonstop:
        asked.append("nonstop")
    if day is not None:
        asked.append("today" if day == 0 else "tomorrow")
    if not asked:
        return None

    def fits(o):
        return ((not arrive_before or o.get("arriveTime", "99:99") < arrive_before)
                and (not depart_after or o.get("departTime", "") > depart_after)
                and (not depart_before or o.get("departTime", "99:99") < depart_before)
                and (not nonstop or str(o.get("stops", "")).lower() == "nonstop")
                and (day is None or int(o.get("dayOffset", 0) or 0) == day))

    matches = [o for o in options if fits(o)]
    wanted = ", ".join(asked)
    if not matches:
        return [{"Content": {"TextMessage": {"Body": (
            f"None of the flights {wanted}. Here are all the options, or call to ask about others."
        )}}}, _options_message(options[:10])]
    return [{"Content": {"TextMessage": {"Body": (
        f"{len(matches)} flight{'s' if len(matches) != 1 else ''} {wanted}:"
    )}}}, _options_message(matches)]


def on_postback(phone, phone_hash, postback_data):
    # rebook_hotel is intercepted in channel_adapter.handle_postback (see the
    # module docstring), so it never reaches this function.
    if postback_data.startswith(PICK_PREFIX):
        o = c.disruption_option_by_id(postback_data[len(PICK_PREFIX):])
        if o:
            return _rebooked(o)
        return [{"Content": {"TextMessage": {"Body": (
            "Sorry, that flight is no longer available. Here are the current options."
        )}}}] + _disruption()
    return None
