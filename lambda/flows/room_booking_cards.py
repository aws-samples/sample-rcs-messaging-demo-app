"""Property_Card post-processing for the AnyTravel Room Booking flow (design C9).

Room Booking is AI-driven, but the Bedrock JSON contract carries no trustworthy
media field, so the model cannot attach a property's photo itself. This module
supplies that one deterministic step as a pure transform on the AI's reply dict,
applied between `invoke_ai` and `send_ai_response`:

- every `dial` and `view_location` suggestion is dropped from the conversational
  reply (the model adds them despite the prompt; only the Property_Card's own
  Open Map and the separate booking-confirmation card carry those actions);
- the property is resolved from the REPLY (its title first, then title plus
  body/description), not from the guest's input, so the result is the same for
  a tap with any chip id, typed text, or an offer handoff;
- when exactly one property resolves and it has not been carded yet in this
  booking session, the reply is merged into ONE rich card: the property's photo
  as media, the AI's title and text, an "Open Map" view_location first, then the
  AI's remaining suggestions (at most four in total).

A reply naming zero or several properties (for example the list of all
properties) is sent without media. Everything is read from content/hotels.md via
common's hotel accessors — no brand literal, no hardcoded city, property or
coordinates. The matcher derives its tokens from each property's `city` and
`name`, so editing the content re-themes it with no code change.
"""

import copy
import re

import common as c

# Per-card suggestion limit (RCS rich card allows four).
_MAX_CARD_SUGGESTIONS = 4
# Suggestion kinds that conversational booking replies must not carry (R15.10).
_DROPPED_KINDS = {"dial", "view_location"}


def _city_tokens(prop: dict) -> set:
    """Lowercase match tokens for one property: its city's first segment (the
    city name before a comma, e.g. 'Seattle, WA' -> 'seattle') and each word of
    the property name except the brand word, so 'AnyTravel Harbor' also matches
    'harbor'. Multi-word city names (e.g. 'New York') are kept whole."""
    tokens = set()
    city = str(prop.get("city", "")).split(",")[0].strip().lower()
    if city:
        tokens.add(city)
    name = str(prop.get("name", "")).strip().lower()
    # Drop the brand word (first token of the name) so the brand name itself is
    # not a city match; keep the distinctive remainder (e.g. 'harbor').
    parts = name.split()
    for w in parts[1:]:
        w = re.sub(r"[^a-z0-9]", "", w)
        if len(w) >= 3:
            tokens.add(w)
    return tokens


def resolve_property(text: str):
    """The single property a piece of text names, or None.

    Returns the property dict when exactly one property's tokens match the text
    (whole-word, case-insensitive); returns None when zero or more than one
    match, so ambiguous replies are left as they are rather than guessed.
    """
    t = (text or "").lower()
    hits = []
    for prop in c.hotel_properties():
        for tok in _city_tokens(prop):
            # whole-word / phrase match (handles multi-word tokens like 'new york')
            if re.search(r"(?<!\w)" + re.escape(tok) + r"(?!\w)", t):
                hits.append(prop)
                break
    return hits[0] if len(hits) == 1 else None


def _filter_suggestions(suggestions) -> list:
    """Copy of `suggestions` without dial / view_location entries."""
    if not isinstance(suggestions, list):
        return []
    return [
        copy.deepcopy(s) for s in suggestions
        if not (isinstance(s, dict) and s.get("type") in _DROPPED_KINDS)
    ]


def _reply_property(data: dict):
    """Resolve the property a reply presents: title first, then title + text."""
    title = str(data.get("title", "") or "")
    prop = resolve_property(title) if title else None
    if prop is None:
        text = data.get("description") or data.get("body") or ""
        prop = resolve_property(f"{title}\n{text}")
    return prop


def apply_property_card(data, carded_id, hint_id=None):
    """Merge a property's photo and Open Map into a Room Booking reply.

    Pure: `data` is not mutated. Returns `(reply, property_id)` where
    `property_id` is the id of the property just carded, or None when the reply
    was only filtered (zero / several properties, or already carded).

    `hint_id` is the id of the property a priced quote names this turn. It is
    used only when the reply's own text (title, then title plus text) does not
    resolve to exactly one property, so the card's title is built from content
    ("<name> — <city>") and the text carries no name line of its own. An id that
    names no property is ignored.
    """
    if not isinstance(data, dict):
        return data, None

    filtered = copy.deepcopy(data)
    filtered["suggestions"] = _filter_suggestions(data.get("suggestions", []))
    if "message_suggestions" in data:
        filtered["message_suggestions"] = _filter_suggestions(data.get("message_suggestions", []))

    prop = _reply_property(data)
    if prop is None and hint_id:
        prop = c.hotel_property_by_id(hint_id)
    pid = (prop or {}).get("id")
    if not prop or not pid or pid == carded_id:
        return filtered, None

    name = str(prop.get("name", "") or "")
    city = str(prop.get("city", "") or "")
    is_card = data.get("type") == "rich_card"

    if is_card and data.get("title"):
        title = data["title"]
    else:
        title = f"{name} — {city}" if city else name
    description = (data.get("description") if is_card else data.get("body")) or ""
    if is_card and not description:
        description = data.get("body", "") or ""

    open_map = {
        "type": "view_location",
        "text": "Open Map",
        "latitude": float(prop.get("lat", 0) or 0),
        "longitude": float(prop.get("lng", 0) or 0),
        "label": name,
    }

    card = {
        "type": "rich_card",
        "title": title,
        "description": description,
        "suggestions": ([open_map] + filtered["suggestions"])[:_MAX_CARD_SUGGESTIONS],
    }
    media_ref = prop.get("photo") or prop.get("image") or ""
    if media_ref:
        card["image"] = media_ref
    if is_card and data.get("media_height"):
        card["media_height"] = data["media_height"]
    if filtered.get("message_suggestions"):
        card["message_suggestions"] = filtered["message_suggestions"]
    return card, pid
