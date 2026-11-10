"""Deterministic pricing and confirmation for the AnyTravel Room Booking flow (design C14).

Room Booking is AI-driven, but the model is not a reliable source of numbers:
left to itself it quoted different nightly rates for the same stay in the
summary and the confirmation. So the model only IDENTIFIES the stay (property
id, room id, ISO dates, guest count) and everything numeric is computed here
from content/hotels.md via common's hotel accessors:

- `rate_table_text()` is the generated rate table the prompt includes, so the
  model sees exactly the ids and rates the code will charge;
- `price_stay(raw, today, offer_id)` validates the model's stay against content
  and prices it (standard rate from `properties[].rates`, or the Travel Offer's
  `memberRate` only for that offer's property and room); it never raises;
- `summary_text(stay)` and `confirmation_card(stay, first_name, reference)` render
  the priced stay with one money formatter, so both show the same numbers;
- `new_reference()` makes a booking reference with a brand-derived prefix.

All functions are pure apart from reading content (and `new_reference`'s random
digits). No brand literal, property, rate or time is hardcoded: editing
content/hotels.md re-prices and re-themes everything with no code change.
"""

import random
from datetime import date, datetime, timedelta, timezone

import common as c

# Longest stay the assistant may book in one reservation.
MAX_NIGHTS = 30

_rng = random.SystemRandom()


# ── Helpers ────────────────────────────────────────────────────────────────
def _num(v):
    """A real number (int/float, not bool), else None."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def _int(v):
    """An integer from an int or an all-digit string, else None (no bool/float)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip())
    return None


def _iso_date(v):
    """A date from an ISO YYYY-MM-DD string, else None."""
    if not isinstance(v, str) or len(v.strip()) != 10:
        return None
    try:
        return date.fromisoformat(v.strip())
    except ValueError:
        return None


def _money(x) -> str:
    """'$219' for a whole amount, '$219.50' otherwise, with thousands commas."""
    x = float(x)
    if abs(x - round(x)) < 0.005:
        return f"${round(x):,.0f}"
    return f"${x:,.2f}"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _md(d: date) -> str:
    return f"{d.strftime('%b')} {d.day}"


def _date_range(check_in: str, check_out: str) -> str:
    """'Aug 15 – Aug 17, 2026'; the start year is shown only when it differs."""
    a, b = date.fromisoformat(check_in), date.fromisoformat(check_out)
    start = _md(a) if a.year == b.year else f"{_md(a)}, {a.year}"
    return f"{start} – {_md(b)}, {b.year}"


def _rate_line(stay: dict) -> str:
    member = " (member rate)" if stay.get("rate_kind") == "member" else ""
    return f"{_money(stay['nightly'])}/night{member}"


def _add_years(d: date, years: int) -> date:
    """`d` moved `years` whole years later; 29 Feb becomes 28 Feb when the
    target year is not a leap year."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)


def offer_dates(offer, today):
    """The offer's (check_in, check_out) ISO dates, rolled forward (R20.10).

    The offers' dates in content/hotels.md are fixed, so they go stale. When
    check-in is on or after `today` the dates are returned unchanged; otherwise
    both move forward by the smallest whole number of years that puts check-in
    on or after `today`, keeping the night count exact. Returns None for a
    missing or invalid date or a check-out that is not after check-in. Never
    raises; pure given `today`.
    """
    try:
        if not isinstance(offer, dict) or not isinstance(today, date):
            return None
        d_in, d_out = _iso_date(offer.get("checkIn")), _iso_date(offer.get("checkOut"))
        if d_in is None or d_out is None or d_out <= d_in:
            return None
        if d_in >= today:
            return d_in.isoformat(), d_out.isoformat()
        nights = (d_out - d_in).days
        years = max(1, today.year - d_in.year)
        shifted = _add_years(d_in, years)
        while shifted < today:
            years += 1
            shifted = _add_years(d_in, years)
        return shifted.isoformat(), (shifted + timedelta(days=nights)).isoformat()
    except Exception:
        return None


def _member_offer(offer_id: str, property_id: str, room_id: str):
    """The offer whose member rate applies to this property and room, or None."""
    if not offer_id or not isinstance(offer_id, str):
        return None
    offer = c.travel_offer_by_id(offer_id)
    if not offer:
        return None
    rate = _num(offer.get("memberRate"))
    if offer.get("propertyId") != property_id or offer.get("roomId") != room_id:
        return None
    if rate is None or rate <= 0:
        return None
    return offer


# ── Prompt block ───────────────────────────────────────────────────────────
def rate_table_text(today=None) -> str:
    """The rate table the Room Booking prompt includes; "" with no properties.

    Offer lines show the offer's dates rolled forward from `today` (default:
    the current UTC date), the same dates `price_stay` will accept (R20.10)."""
    props = c.hotel_properties()
    if today is None:
        today = datetime.now(timezone.utc).date()
    if not props:
        return ""
    rooms = c.room_types()
    lines = ["RATE TABLE (standard nightly USD; quote ONLY these):"]
    for p in props:
        rates = p.get("rates") or {}
        cells = []
        for r in rooms:
            rate = _num(rates.get(r.get("id")))
            if rate is not None and rate > 0:
                cells.append(f"{r.get('id')} {_money(rate)}")
        lines.append(f"- {p.get('id')} ({p.get('name', '')}, {p.get('city', '')}): "
                     + ", ".join(cells))
    lines.append("ROOMS: " + ", ".join(
        f"{r.get('id')} = {r.get('name', '')} (sleeps {r.get('sleeps', '')})" for r in rooms))
    offers = [o for o in c.travel_offers() if _num(o.get("memberRate"))]
    lines.append(
        "A member rate applies ONLY to a stay the guest started from a Travel Offer, for "
        "that offer's property and that offer's room. Every other stay or room is quoted "
        "at the standard rate above."
    )
    for o in offers:
        d_in, d_out = offer_dates(o, today) or (o.get("checkIn", ""), o.get("checkOut", ""))
        lines.append(
            f"- offer {o.get('id')}: {o.get('propertyId')}, room {o.get('roomId')}, "
            f"member rate {_money(o.get('memberRate'))}, {d_in} to {d_out}"
        )
    return "\n".join(lines)


# ── Pricing ────────────────────────────────────────────────────────────────
def price_stay(raw, today, offer_id=""):
    """Validate the model's stay against content and price it, or return None.

    `raw` is `{property_id, room_id, check_in, check_out, guests}`; `today` is a
    `datetime.date`. Never raises: any invalid input yields None.
    """
    try:
        return _price_stay(raw, today, offer_id)
    except Exception:
        return None


def _price_stay(raw, today, offer_id):
    if not isinstance(raw, dict) or not isinstance(today, date):
        return None
    pid, rid = raw.get("property_id"), raw.get("room_id")
    if not isinstance(pid, str) or not isinstance(rid, str):
        return None
    prop = c.hotel_property_by_id(pid.strip())
    room = c.room_type_by_id(rid.strip())
    if not prop or not room:
        return None
    pid, rid = prop["id"], room["id"]
    rate = _num((prop.get("rates") or {}).get(rid))
    if rate is None or rate <= 0:
        return None

    d_in, d_out = _iso_date(raw.get("check_in")), _iso_date(raw.get("check_out"))
    if d_in is None or d_out is None or d_out <= d_in or d_in < today:
        return None
    nights = (d_out - d_in).days
    if nights > MAX_NIGHTS:
        return None

    guests = _int(raw.get("guests"))
    sleeps = _int(room.get("sleeps"))
    if guests is None or sleeps is None or not 1 <= guests <= sleeps:
        return None

    offer = _member_offer(offer_id, pid, rid)
    nightly = float(offer["memberRate"]) if offer else rate
    stay = {
        "property_id": pid,
        "property_name": str(prop.get("name", "") or ""),
        "city": str(prop.get("city", "") or ""),
        "lat": float(_num(prop.get("lat")) or 0.0),
        "lng": float(_num(prop.get("lng")) or 0.0),
        "room_id": rid,
        "room_name": str(room.get("name", "") or ""),
        "check_in": d_in.isoformat(),
        "check_out": d_out.isoformat(),
        "nights": nights,
        "guests": guests,
        "nightly": nightly,
        "total": round(nightly * nights, 2),
        "rate_kind": "member" if offer else "standard",
        "reference": "",
    }
    if offer:
        stay["offer_id"] = offer["id"]
    return stay


# ── Rendering ──────────────────────────────────────────────────────────────
def summary_text(stay: dict) -> str:
    """The deterministic summary that replaces the model's quote text."""
    return "\n".join([
        f"{stay['room_name']} · {_plural(stay['guests'], 'guest')}",
        f"{_date_range(stay['check_in'], stay['check_out'])} "
        f"({_plural(stay['nights'], 'night')})",
        f"{_rate_line(stay)} · Total {_money(stay['total'])}",
        "",
        "Ready to confirm?",
    ])


def confirmation_card(stay: dict, first_name: str, reference: str) -> dict:
    """The booking confirmation as an assistant-JSON rich_card, built with no
    model call. The channel adapter adds Start Over; no menu chip here."""
    check_in_time, check_out_time = c.hotel_times()
    name, city = stay["property_name"], stay["city"]
    guests = _plural(stay["guests"], "guest")
    nights = _plural(stay["nights"], "night")
    greeting = f"You're all set, {first_name}!" if first_name else "You're all set!"
    description = "\n".join([
        f"{name} — {city}" if city else name,
        f"{_date_range(stay['check_in'], stay['check_out'])} ({nights})",
        f"{stay['room_name']} · {guests}",
        _rate_line(stay),
        f"Estimated total: {_money(stay['total'])}",
        "",
        f"Reference: {reference}",
        "",
        f"{greeting} Tap below to save your stay to your calendar.",
    ])
    title = "Booking Confirmed! 🎉"
    return {
        "type": "rich_card",
        "title": title[:c.rcs_limit("richCardTitleChars")],
        "description": description[:c.rcs_limit("richCardDescriptionChars")],
        "suggestions": [
            {
                "type": "calendar",
                "text": "Add to Calendar",
                "start_time": f"{stay['check_in']}T{check_in_time}:00",
                "end_time": f"{stay['check_out']}T{check_out_time}:00",
                "title": f"{name} stay",
                "description": (f"{stay['room_name']}, {guests}, {nights} at {name}"
                                f"{', ' + city if city else ''}. Ref: {reference}"),
            },
            {
                "type": "view_location",
                "text": "View on Map",
                "latitude": float(stay.get("lat", 0) or 0),
                "longitude": float(stay.get("lng", 0) or 0),
                "label": name,
            },
            {
                "type": "dial",
                "text": c.call_label(),
                "phone_number": c.member_services_phone(),
            },
        ],
    }


def new_reference() -> str:
    """Booking reference: the brand name's capitals (or its first two letters
    when it has fewer than two capitals), '-', five random digits."""
    brand = str(c.brand_name() or "")
    prefix = "".join(ch for ch in brand if ch.isupper() and ch.isascii())
    if len(prefix) < 2:
        letters = "".join(ch for ch in brand if ch.isalpha())
        prefix = (letters[:2] or "BK").upper()
    return f"{prefix}-{_rng.randrange(100000):05d}"
