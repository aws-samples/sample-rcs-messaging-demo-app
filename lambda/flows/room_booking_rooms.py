"""Room_Carousel and Room_Detail_Card for the AnyTravel Room Booking flow (design C15).

Room Booking is AI-driven. When the assistant offers the room types as reply
chips, a row of names says nothing about what the guest is choosing, so the
demo turns those chips into a swipeable carousel with one photo per room type:

- `strip_room_chips` removes the chips that name a Room_Type from the AI's reply
  (both `suggestions` and `message_suggestions`) and reports which room types
  they named;
- `room_carousel` builds the carousel message, one card per Room_Type in content
  order: the room's first photo, its name, its occupancy and either the known
  property's standard nightly rate or the room's short description, plus one
  Choose chip (`room_pick_<id>`);
- `room_detail` turns the assistant's reply to a Choose tap into a rich card that
  carries the chosen room's second photo.

Pure: no I/O and no input is mutated. Everything is read from content/hotels.md
through common's hotel accessors and every limit from c.rcs_limit, so no brand,
room, property or price literal appears here. The carousel only displays the
standard rate from `properties[].rates`; it never prices a stay (the quote does,
design C14).
"""
import copy
import re

import common as c
from flows.room_booking_quote import _money

# PostbackData prefix of the Choose chip; channel_adapter routes on it.
PICK_PREFIX = "room_pick_"


def _photos(room: dict) -> list:
    """The room's photo paths, via common.room_photos when it is available."""
    helper = getattr(c, "room_photos", None)
    if callable(helper):
        photos = helper(room)
    else:
        photos = room.get("photos") or []
    if not isinstance(photos, list):
        return []
    return [p for p in photos if isinstance(p, str) and p]


def _room_by_id(room_id):
    for room in c.room_types():
        if isinstance(room, dict) and room.get("id") == room_id:
            return room
    return None


def _name_tokens(room: dict) -> list:
    """Lowercase phrases that name a room: its name and, when the name ends in
    " Room", the name without it ('King Room' -> 'king room', 'king')."""
    name = str(room.get("name", "") or "").strip().lower()
    if not name:
        return []
    tokens = [name]
    short = re.sub(r"\s+room$", "", name).strip()
    if short and short != name:
        tokens.append(short)
    return tokens


def _is_reply_chip(s) -> bool:
    # A chip without a type is a reply chip, as in common.build_suggestions.
    return isinstance(s, dict) and s.get("type", "reply") == "reply"


def _chip_names_room(chip: dict, room: dict) -> bool:
    text = str(chip.get("text", "") or "").lower()
    return any(
        re.search(r"(?<!\w)" + re.escape(tok) + r"(?!\w)", text)
        for tok in _name_tokens(room)
    )


def room_chip_ids(suggestions) -> list:
    """Ids of the Room_Types that the reply chips in `suggestions` name, in
    content order and without duplicates. Only reply chips count."""
    chips = [s for s in (suggestions or []) if _is_reply_chip(s)] if isinstance(suggestions, list) else []
    ids = []
    for room in c.room_types():
        if not isinstance(room, dict) or not room.get("id"):
            continue
        if room["id"] in ids:
            continue
        if any(_chip_names_room(chip, room) for chip in chips):
            ids.append(room["id"])
    return ids


def _is_room_chip(s) -> bool:
    return _is_reply_chip(s) and any(
        isinstance(r, dict) and r.get("id") and _chip_names_room(s, r)
        for r in c.room_types()
    )


def strip_room_chips(data):
    """`(reply, ids)`: a copy of the AI reply without the reply chips that name a
    Room_Type, and the ids those chips named (across `suggestions` and
    `message_suggestions`, content order). A non-dict reply is returned as is."""
    if not isinstance(data, dict):
        return data, []
    reply = copy.deepcopy(data)
    found = []
    for key in ("suggestions", "message_suggestions"):
        chips = reply.get(key)
        if not isinstance(chips, list):
            continue
        found.extend(s for s in chips if _is_room_chip(s))
        reply[key] = [s for s in chips if not _is_room_chip(s)]
    return reply, room_chip_ids(found)


def _rate(prop, room_id):
    rates = (prop or {}).get("rates")
    if not isinstance(rates, dict):
        return None
    try:
        rate = float(rates.get(room_id))
    except (TypeError, ValueError):
        return None
    return rate if rate > 0 else None


def _room_card(room: dict, prop) -> dict:
    sleeps = room.get("sleeps", "")
    rate = _rate(prop, room.get("id"))
    if rate is not None:
        desc = f"Sleeps {sleeps} · {_money(rate)}/night at {prop.get('name', '')}"
    else:
        desc = f"Sleeps {sleeps} · {room.get('blurb', '')}"
    card = {
        "Title": str(room.get("name", "") or "")[: c.rcs_limit("richCardTitleChars")],
        "Description": desc.strip()[: c.rcs_limit("richCardDescriptionChars")],
        "Suggestions": [
            {"Reply": {"Text": "Choose", "PostbackData": f"{PICK_PREFIX}{room['id']}"}},
        ],
    }
    photos = _photos(room)
    if photos:
        card["Media"] = {"FileUrl": c.resolve_media(photos[0]), "Height": "MEDIUM"}
    return card


def room_carousel(property_id):
    """The Room_Carousel RCS message, or None when content has fewer Room_Types
    than a carousel allows. `property_id` names the booking's known property
    (or None); its standard rates are shown when it has one for the room."""
    rooms = [r for r in c.room_types() if isinstance(r, dict) and r.get("id")]
    if len(rooms) < c.rcs_limit("carouselCardsMin"):
        return None
    prop = c.hotel_property_by_id(property_id) if property_id else None
    cards = [_room_card(r, prop) for r in rooms[: c.rcs_limit("carouselCardsMax")]]
    return {"Content": {"Carousel": {"CardWidth": "MEDIUM", "CardContents": cards}}}


def room_detail(reply, room_id):
    """The assistant's reply to a Choose tap as a Room_Detail_Card: a rich card
    with the room's second photo (none when it has no second photo), the reply's
    title or else the room name, and the reply's text. At most a card's worth of
    suggestions is kept; message-level chips are kept as they are. An unknown
    room id, or a reply that is not a dict, is returned unchanged."""
    room = _room_by_id(room_id)
    if not isinstance(reply, dict) or room is None:
        return reply
    card = {
        "type": "rich_card",
        "title": reply.get("title") or str(room.get("name", "") or ""),
        "description": reply.get("description") or reply.get("body") or "",
    }
    photos = _photos(room)
    if len(photos) > 1:
        card["image"] = photos[1]
        if reply.get("media_height"):
            card["media_height"] = reply["media_height"]
    suggestions = reply.get("suggestions")
    card["suggestions"] = (
        copy.deepcopy(suggestions[: c.rcs_limit("suggestionsPerCard")])
        if isinstance(suggestions, list) else []
    )
    if "message_suggestions" in reply:
        card["message_suggestions"] = copy.deepcopy(reply["message_suggestions"])
    return card
