"""Hotel express check-in — deterministic, event-driven 2-way flow (AnyTravel).

The property sends a check-in reminder the day of arrival (an unprompted
outbound — the event-driven-send pattern, same shape as the clinic-initiated
reschedule in appointment.py). From there the guest completes express check-in
entirely in the thread: confirm the stay, choose an optional upgrade, and
receive a digital room key. No app, no front-desk line.

Property, upgrade and rate data come from content/hotels.md; the brand name and
member-services phone are read from the selected brand's identity, so the flow
re-themes with the content and carries no brand literal in its runtime strings.

Triggers: `Start: Express_Checkin`, or the `home_checkin` postback.
Postback prefix: checkin_
"""

import common as c


# Which property this sample reminder is for. First property in hotels.md,
# resolved at call time so editing the content file re-themes the flow. The
# fallback name is built from the selected brand name (never a literal) so a
# re-themed brand stays consistent even with no properties in content.
def _property():
    props = c.hotel_properties()
    return props[0] if props else {
        "name": f"{_brand()} Hotel", "city": "", "address": "",
        "lat": 0, "lng": 0, "image": "",
    }


def _brand():
    return c.brand_name()


def _banner(card):
    """Add the selected brand's card image as the card media, as the welcome
    cards do. A brand with no card image or banner sends the card without media
    rather than a broken image."""
    media = c.brand_card_media()
    if media:
        card["Media"] = media
    return card


def _stay_times():
    """(check-in, checkout) as 12-hour text, from content/hotels.md."""
    cin, cout = c.hotel_times()
    return c.format_time_12h(cin), c.format_time_12h(cout)


# Arrival windows are tied to the check-in time: before it, the three hours from
# it, and after that. Computed in minutes since midnight so a check-in such as
# 14:30 reads "2:30 PM" and not a rounded hour.
def _clock(minutes):
    """Minutes since midnight -> ("3", "PM") or ("2:30", "PM")."""
    minutes %= 24 * 60
    h, m = divmod(minutes, 60)
    num = str(h % 12 or 12) if m == 0 else f"{h % 12 or 12}:{m:02d}"
    return num, ("AM" if h < 12 else "PM")


def _clock_text(minutes):
    num, ap = _clock(minutes)
    return f"{num} {ap}"


def _range_text(start, end, joiner):
    """"3 and 6 PM" / "10 AM and 1 PM" (joiner " and "), or "3–6 PM" (joiner "–")."""
    n1, a1 = _clock(start)
    n2, a2 = _clock(end)
    if a1 == a2:
        return f"{n1}{joiner}{n2} {a2}"
    return f"{n1} {a1}{joiner}{n2} {a2}"


def _arrival_bounds():
    """(start, end) of the middle arrival window, in minutes since midnight."""
    cin = c.hotel_times()[0]
    h, m = (int(p) for p in cin.split(":"))
    start = h * 60 + m
    return start, start + 180


def _eta_windows():
    start, end = _arrival_bounds()
    return {
        "checkin_eta_early": f"before {_clock_text(start)}",
        "checkin_eta_afternoon": f"between {_range_text(start, end, ' and ')}",
        "checkin_eta_late": f"after {_clock_text(end)}",
    }


def _eta_chip_labels():
    start, end = _arrival_bounds()
    return (
        f"Before {_clock_text(start)}"[:25],
        _range_text(start, end, "–")[:25],
        f"After {_clock_text(end)}"[:25],
    )


def on_start(phone, phone_hash):
    return _reminder()


def on_trigger(phone, phone_hash, vignette):
    return _reminder()


def _reminder():
    p = _property()
    check_in, check_out = _stay_times()
    loc = (p.get("address") or p.get("city") or "").strip()
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": _banner({
                    "Title": f"{_brand()}: You check in today",
                    "Description": (
                        f"Welcome back! Your room at {p.get('name', '')} is almost ready.\n\n"
                        f"{p.get('city', '')}\n"
                        f"{loc}\n\n"
                        f"Check-in from {check_in} · Checkout {check_out}\n"
                        "Skip the front desk — check in right here and we'll send a "
                        "digital key to your phone."
                    ),
                    "Suggestions": [
                        {"Reply": {"Text": "Express Check-In", "PostbackData": "checkin_start"}},
                        {"Reply": {"Text": "Change Arrival Time", "PostbackData": "checkin_eta"}},
                    ],
                }),
            }
        },
        "Suggestions": [
            {"ShowLocation": {
                "Text": "Get Directions", "PostbackData": "checkin_directions",
                "Latitude": p.get("lat", 0), "Longitude": p.get("lng", 0),
                "Label": p.get("name", _brand()),
            }},
        ],
        # SMS fallback for the entry message. Written out rather than derived
        # from the card: the card's value is its chips, image and map pin, none
        # of which survive as SMS. Inactive unless the stack was deployed with
        # -c smsFallbackNumber=+1…; see common.send_rcs.
        "_fallback_body": (
            f"{_brand()}: You check in today at {p.get('name', '')}, {loc}. "
            f"Check-in from {check_in}, checkout {check_out}. "
            f"To check in or change your arrival time, call {c.member_services_phone()}."
        ),
    }]


def _upgrade_options():
    """Second step: pick an optional upgrade. Driven entirely by hotels.md →
    upgrades, so a content edit changes the choices without touching code."""
    chips = []
    # One chip fewer than the message-level limit leaves room for the Start Over
    # chip the channel adapter appends (ten of the eleven allowed).
    max_chips = c.rcs_limit("suggestionsPerMessage") - 1
    for u in c.room_upgrades()[:max_chips]:
        label = u.get("name", "Option")
        # Suggestion labels cap at 25 chars (validated in common); keep them short.
        chips.append({"Reply": {"Text": label[:25], "PostbackData": f"checkin_up_{u['id']}"}})

    lines = []
    for u in c.room_upgrades():
        price = float(u.get("price", 0) or 0)
        tag = "Complimentary" if price == 0 else f"+${price:.0f}"
        lines.append(f"- {u.get('name', '')} ({tag}): {u.get('blurb', '')}")
    body = (
        "You're confirmed. Would you like an upgrade before we cut your key?\n\n"
        + "\n".join(lines)
    )
    return [{"Content": {"TextMessage": {"Body": body}}, "Suggestions": chips}]


def _eta_options():
    early, mid, late = _eta_chip_labels()
    return [{
        "Content": {"TextMessage": {"Body": (
            "No problem — when do you expect to arrive? We'll have the room ready."
        )}},
        "Suggestions": [
            {"Reply": {"Text": early, "PostbackData": "checkin_eta_early"}},
            {"Reply": {"Text": mid, "PostbackData": "checkin_eta_afternoon"}},
            {"Reply": {"Text": late, "PostbackData": "checkin_eta_late"}},
            {"Reply": {"Text": "Express Check-In", "PostbackData": "checkin_start"}},
        ],
    }]


def _eta_ack(window):
    return [{
        "Content": {"TextMessage": {"Body": (
            f"Got it — we'll note an arrival {window}. Ready to check in now?"
        )}},
        "Suggestions": [
            {"Reply": {"Text": "Express Check-In", "PostbackData": "checkin_start"}},
        ],
    }]


def _digital_key(upgrade=None):
    p = _property()
    check_out = _stay_times()[1]
    # A believable but obviously fake room/key for a demo.
    room_no = "1208"
    extra = ""
    if upgrade and upgrade.get("id") not in ("none", None):
        price = float(upgrade.get("price", 0) or 0)
        if upgrade["id"] == "suite_upgrade":
            room_no = "1810"
        extra = (
            f"\n\nUpgrade applied: {upgrade.get('name', '')}"
            + ("" if price == 0 else f" (+${price:.0f})")
        )
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": _banner({
                    "Title": "You're checked in 🎉",
                    "Description": (
                        f"Room {room_no} at {p.get('name', '')}.{extra}\n\n"
                        "Your digital key is active on this device. Tap Open Door at "
                        "your room, or stop by the desk for a physical key.\n\n"
                        f"Checkout is {check_out} — reply anytime to extend."
                    ),
                    "Suggestions": [
                        {"OpenUrl": {
                            "Text": "Open Door", "PostbackData": "checkin_key_wv",
                            "Url": c.webview_url(
                                "digital-key", room=room_no, property=p.get("name", "")),
                            "Application": "WEBVIEW", "WebviewViewMode": "TALL",
                        }},
                        {"ShowLocation": {
                            "Text": "Hotel Map", "PostbackData": "checkin_directions",
                            "Latitude": p.get("lat", 0), "Longitude": p.get("lng", 0),
                            "Label": p.get("name", _brand()),
                        }},
                    ],
                }),
            }
        },
    }]


def on_postback(phone, phone_hash, postback_data):
    # No "checkin_restart" here: the channel adapter attaches the Start Over chip
    # and routes the old checkin_restart id to the global Reset before this runs.
    if postback_data == "checkin_start":
        return _upgrade_options()
    if postback_data == "checkin_eta":
        return _eta_options()
    windows = _eta_windows()
    if postback_data in windows:
        return _eta_ack(windows[postback_data])
    if postback_data.startswith("checkin_up_"):
        uid = postback_data[len("checkin_up_"):]
        return _digital_key(c.room_upgrade_by_id(uid))
    return None
