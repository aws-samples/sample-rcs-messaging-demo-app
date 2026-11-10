"""Flight check-in and boarding pass — deterministic, event-driven (AnyTravel).

The day before departure the airline sends a check-in reminder (an unprompted
outbound, the same event-driven pattern as the hotel's Express Check-In). The
traveler checks in from the card, can change seat first, and gets a boarding
pass that opens in a webview, plus an Add to Calendar chip for the flight.

Flight and seat data come from content/flights.md through the flight accessors
in common.py; the brand name and phone come from the selected brand's identity,
so no brand literal appears in a runtime string.

Triggers: `Start: Flight_Checkin`, or the `home_flight_checkin` postback.
Postback prefix: board_
"""

import common as c


def _banner(card):
    media = c.brand_card_media()
    if media:
        card["Media"] = media
    return card


def _route(f):
    return f"{f['origin'].get('code', '')} → {f['dest'].get('code', '')}"


def _traveler(phone_hash):
    """The traveler's name for the boarding pass: the Recipients-tab name, else
    the brand's sample member."""
    return c.tester_name(phone_hash, fallback=c.member_name()) or c.member_name()


def on_start(phone, phone_hash):
    return _reminder()


def on_trigger(phone, phone_hash, vignette):
    return _reminder()


def preview_message():
    return _reminder()


def _reminder():
    f = c.next_flight()
    if not f:
        return [{"Content": {"TextMessage": {"Body": "No upcoming flight. Add one in content/flights.md."}}}]
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": _banner({
                    "Title": f"Check in for flight {f.get('number', '')}"[:200],
                    "Description": (
                        f"{f['origin'].get('city', '')} to {f['dest'].get('city', '')}\n"
                        f"{_route(f)} · {f.get('date', '')}\n"
                        f"Departs {f.get('departLabel', '')} · Arrives {f.get('arriveLabel', '')}\n"
                        f"Seat {f.get('seat', '')} · {c.flight_cabin()}\n\n"
                        "Check-in is open. Check in now and your boarding pass "
                        "arrives right here."
                    )[:2000],
                    "Suggestions": [
                        {"Reply": {"Text": "Check In", "PostbackData": "board_checkin"}},
                        {"Reply": {"Text": "Change Seat", "PostbackData": "board_seat"}},
                    ],
                }),
            }
        },
        # SMS fallback for the entry message: the check-in buttons and the
        # boarding pass need rich messaging, so the SMS points to the phone line.
        # Inactive unless deployed with -c smsFallbackNumber=+1…; see
        # common.send_rcs.
        "_fallback_body": (
            f"{c.brand_name()}: check-in is open for flight {f.get('number', '')}, "
            f"{_route(f)}, {f.get('date', '')} at {f.get('departLabel', '')}. "
            f"Confirmation {c.flight_confirmation()}. To check in, call {c.member_services_phone()}."
        ),
    }]


def _seat_choices():
    chips = []
    lines = []
    for s in c.seat_options()[: c.rcs_limit("suggestionsPerMessage") - 1]:
        price = float(s.get("price", 0) or 0)
        tag = "no charge" if price == 0 else f"+${price:.0f}"
        chips.append({"Reply": {"Text": str(s.get("label", s.get("seat", "Seat")))[:25],
                                "PostbackData": f"board_seat_{s['id']}"}})
        lines.append(f"- {s.get('label', s.get('seat', ''))} ({tag})")
    return [{
        "Content": {"TextMessage": {"Body": (
            "These seats are open on your flight. Pick one and we'll check you in:\n\n"
            + "\n".join(lines)
        )}},
        "Suggestions": chips,
    }]


def _checked_in(phone_hash, seat=None):
    f = c.next_flight()
    seat_no = (seat or {}).get("seat") or f.get("seat", "")
    price = float((seat or {}).get("price", 0) or 0)
    extra = f"\nSeat change: {seat_no}" + ("" if price == 0 else f" (+${price:.0f})") if seat else ""
    origin, dest = f["origin"], f["dest"]
    pass_url = c.webview_url(
        "boarding-pass",
        name=_traveler(phone_hash),
        flight=f.get("number", ""),
        origin=origin.get("code", ""), dest=dest.get("code", ""),
        date=f.get("date", ""), depart=f.get("departLabel", ""),
        boarding=f.get("boardingLabel", ""), gate=f.get("gate", ""),
        terminal=f.get("terminal", ""), group=f.get("group", ""),
        seat=seat_no, conf=c.flight_confirmation(),
    )
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": _banner({
                    "Title": "You're checked in ✈️",
                    "Description": (
                        f"Flight {f.get('number', '')} · {_route(f)} · {f.get('date', '')}\n"
                        f"Seat {seat_no} · Group {f.get('group', '')}{extra}\n\n"
                        f"Boarding {f.get('boardingLabel', '')} at gate {f.get('gate', '')}, "
                        f"terminal {f.get('terminal', '')}. Departs {f.get('departLabel', '')}.\n\n"
                        "Your boarding pass is ready. We'll message you here if the "
                        "gate or time changes."
                    )[:2000],
                    "Suggestions": [
                        {"OpenUrl": {
                            "Text": "Boarding Pass", "PostbackData": "board_pass_wv",
                            "Url": pass_url,
                            "Application": "WEBVIEW", "WebviewViewMode": "TALL",
                        }},
                        {"CreateCalendarEvent": {
                            "Text": "Add to Calendar", "PostbackData": "board_cal",
                            "Title": f"Flight {f.get('number', '')} {_route(f)}",
                            "Description": (
                                f"{origin.get('name', '')} to {dest.get('name', '')}. "
                                f"Confirmation {c.flight_confirmation()}, seat {seat_no}."
                            ),
                            "StartTime": f.get("departEpoch", 0),
                            "EndTime": f.get("arriveEpoch", f.get("departEpoch", 0)),
                        }},
                    ],
                }),
            }
        },
    }]


def on_postback(phone, phone_hash, postback_data):
    if postback_data == "board_checkin":
        return _checked_in(phone_hash)
    if postback_data == "board_seat":
        return _seat_choices()
    if postback_data.startswith("board_seat_"):
        seat = c.seat_option_by_id(postback_data[len("board_seat_"):])
        if seat:
            return _checked_in(phone_hash, seat)
        return _seat_choices()
    return None
