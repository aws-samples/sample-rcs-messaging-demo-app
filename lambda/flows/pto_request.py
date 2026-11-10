"""PTO (paid time off) Request — internal staff self-service, deterministic flow.

Demonstrates an INTERNAL employee/staff use case with a lightweight approval
step: request -> pending (simulated manager review) -> approved. There's no
second party in this demo, so "Check Status" simulates the manager's approval
the first time it's tapped — this keeps the flow single-user, matching every
other vignette in this project, while still showing the request/approve shape.

Triggers: `Start: PTO_Request`, or dashboard push.
Postback prefix: pto_
"""

import common as c

# Ranges are (first-day offset from today in days, number of days). Dates are
# computed when a message is built (UTC today), so a request is always upcoming;
# the chip text, the stored/pending text and the calendar event all come from
# `_range()`. Chip ids never contain a date.
_RANGE_PLAN = {
    "pto_range_a": (14, 2),
    "pto_range_b": (28, 5),
    "pto_range_c": (42, 1),
}
_PTO_START_TIME = "09:00"
_PTO_END_TIME = "17:00"


def _month_day(d):
    """"Oct 26" (month abbreviation and day)."""
    return c.sample_day_label(d).split(", ", 1)[1]


def _label(d):
    """"Mon, Oct 26"."""
    weekday, rest = c.sample_day_label(d).split(", ", 1)
    return f"{weekday[:3]}, {rest}"


_MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_WEEKDAY_ABBR = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _date_from_label(label):
    """Inverse of `_label` ("Mon, Oct 26" -> date), or None. The stored pending
    request keeps only the label, so the year is the one (last, this or next)
    whose date carries that weekday and is nearest today."""
    try:
        weekday, rest = label.split(", ", 1)
        month_abbr, day = rest.split(" ", 1)
        month, day = _MONTH_ABBR.index(month_abbr) + 1, int(day)
        wd = _WEEKDAY_ABBR.index(weekday)
    except (AttributeError, ValueError):
        return None
    today = c.sample_date(0)
    best = None
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            d = today.replace(year=year, month=month, day=day)
        except ValueError:
            continue
        if d.weekday() == wd and (best is None or abs((d - today).days) < abs((best - today).days)):
            best = d
    return best


def _range(postback_id):
    """Start/end dates, labels, chip text, day count and calendar epochs."""
    offset, days = _RANGE_PLAN[postback_id]
    start = c.sample_date(offset)
    end = c.sample_date(offset + days - 1)
    if days == 1:
        chip = f"{_month_day(start)} (1 day)"
    elif start.month == end.month:
        chip = f"{_month_day(start)}\u2013{end.day} ({days} days)"
    else:
        chip = f"{_month_day(start)}\u2013{_month_day(end)} ({days} days)"
    return {
        "start_label": _label(start),
        "end_label": _label(end),
        "days": days,
        "chip": chip,
        "start": c.sample_epoch(start, _PTO_START_TIME),
        "end": c.sample_epoch(end, _PTO_END_TIME),
    }


def on_start(phone, phone_hash):
    return _balance_card(phone_hash)


def on_trigger(phone, phone_hash, vignette):
    return _balance_card(phone_hash)


def _balance_card(phone_hash):
    pending = c.get_pending_pto(phone_hash)
    if pending:
        return _pending_card(pending)
    name = c.tester_name(phone_hash, fallback=c.employee_name())
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "Request Time Off",
                    "Description": (
                        f"{name} — {c.employee_role()}\n\n"
                        f"PTO balance: {c.pto_balance_days():g} days remaining\n\n"
                        "Pick a date range to request:"
                    ),
                    "Media": {"FileUrl": c.resolve_media("media/pto.png"), "Height": "MEDIUM"},
                    "Suggestions": [
                        {"Reply": {"Text": _range(rid)["chip"], "PostbackData": rid}}
                        for rid in _RANGE_PLAN
                    ],
                },
            }
        },
        "Suggestions": [{"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}}],
        # SMS fallback for the vignette's entry message; inactive unless the
        # stack was deployed with -c smsFallbackNumber=+1\u2026. See common.send_rcs.
        # The balance is the part worth delivering; the three date-range chips
        # are the part that cannot survive, so the fallback states the balance
        # and stops rather than listing ranges the member can't tap.
        "_fallback_body": (
            f"{c.brand_name()}: your PTO balance is "
            f"{c.pto_balance_days():g} days remaining. Rich messaging isn't "
            "available on your device right now, so please submit time-off "
            f"requests through your supervisor or call {c.member_services_phone()}."
        ),
    }]


def _submitted(phone_hash, start_label, end_label, days):
    c.set_pending_pto(phone_hash, start_label, end_label, days)
    return _pending_card(c.get_pending_pto(phone_hash))


def _pending_card(pending):
    span = pending["start_label"] if pending["start_label"] == pending["end_label"] else f"{pending['start_label']} \u2013 {pending['end_label']}"
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "Request Submitted",
                    "Description": (
                        f"{span} ({pending['days']} day{'s' if pending['days'] != 1 else ''})\n\n"
                        f"Pending review from {c.manager_name()}. We'll let you know here as soon "
                        "as it's decided."
                    ),
                    "Suggestions": [
                        {"Reply": {"Text": "Check Status", "PostbackData": "pto_status"}},
                    ],
                },
            }
        },
        "Suggestions": [
            {"Reply": {"Text": "Cancel Request", "PostbackData": "pto_cancel"}},
            {"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}},
        ],
    }]


def _approved(pending):
    start = _date_from_label(pending.get("start_label"))
    end = _date_from_label(pending.get("end_label"))
    calendar = []
    if start and end:
        calendar = [{"CreateCalendarEvent": {
            "Text": "Add to Calendar", "PostbackData": "pto_cal",
            "Title": "Time Off", "Description": "Approved time off",
            "StartTime": c.sample_epoch(start, _PTO_START_TIME),
            "EndTime": c.sample_epoch(end, _PTO_END_TIME),
        }}]
    span = pending["start_label"] if pending["start_label"] == pending["end_label"] else f"{pending['start_label']} \u2013 {pending['end_label']}"
    remaining = c.pto_balance_days() - float(pending["days"])
    content = {
        "Title": "Time Off Approved",
        "Description": (
            f"{c.manager_name()} approved your request for {span}.\n\n"
            f"Remaining PTO balance: {remaining:g} days"
        ),
    }
    if calendar:
        content["Suggestions"] = calendar
    return [{
        "Content": {"RichCard": {"CardOrientation": "VERTICAL", "CardContent": content}},
        "Suggestions": [{"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}}],
    }]


def _cancelled():
    return [{
        "Content": {"TextMessage": {"Body": "Your time off request has been cancelled."}},
        "Suggestions": [
            {"Reply": {"Text": "New Request", "PostbackData": "pto_new"}},
            {"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}},
        ],
    }]


# The longest request a typed answer may make, in calendar days, and how far
# ahead it may start.
_MAX_TYPED_DAYS = 30
_MAX_TYPED_AHEAD_DAYS = 365


def on_freetext(phone, phone_hash, text):
    """Typed dates, "next Thursday and Friday for a wedding". The model only reads
    the dates; this code checks them (from tomorrow on, at most _MAX_TYPED_DAYS
    days, within the balance) and submits them like a date-range chip."""
    data = c.ai_extract(
        'The employee was asked which dates they want off. Return {"relevant": true|false, '
        '"start": "YYYY-MM-DD", "end": "YYYY-MM-DD, the same as start for a single day", '
        '"reason": "under 40 characters, or empty"}.',
        text,
    )
    if data is None:
        return [{"Content": {"TextMessage": {"Body": "I couldn't read those dates. Pick a range below."}}}] \
            + _balance_card(phone_hash)
    if not data.get("relevant"):
        return None
    pending = c.get_pending_pto(phone_hash)
    if pending:
        return [{"Content": {"TextMessage": {"Body": (
            "You already have a request waiting for review. Cancel it first to ask for other dates."
        )}}}] + _pending_card(pending)
    start = c.parse_iso_date(data.get("start"))
    end = c.parse_iso_date(data.get("end")) or start
    today = c.sample_date(0)
    problem = ""
    if not start:
        problem = "Which dates? For example, \"next Thursday and Friday\"."
    elif start <= today:
        problem = "Time off has to start from tomorrow on."
    elif end < start:
        problem = "The last day comes before the first day."
    elif (start - today).days > _MAX_TYPED_AHEAD_DAYS:
        problem = "That's more than a year out."
    else:
        days = (end - start).days + 1
        if days > _MAX_TYPED_DAYS:
            problem = f"That's {days} days. Requests here can be up to {_MAX_TYPED_DAYS}."
        elif days > c.pto_balance_days():
            problem = f"That's {days} days, and you have {c.pto_balance_days():g} remaining."
    if problem:
        return [{"Content": {"TextMessage": {"Body": problem}}}] + _balance_card(phone_hash)
    days = (end - start).days + 1
    reason = c.extracted_text(data, "reason", 40)
    span = _label(start) if days == 1 else f"{_label(start)} \u2013 {_label(end)}"
    return [{"Content": {"TextMessage": {"Body": (
        f"Requesting {span} ({days} day{'s' if days != 1 else ''})"
        + (f" for {reason}" if reason else "") + "."
    )}}}] + _submitted(phone_hash, _label(start), _label(end), days)


def on_postback(phone, phone_hash, postback_data):
    if postback_data in _RANGE_PLAN:
        r = _range(postback_data)
        return _submitted(phone_hash, r["start_label"], r["end_label"], r["days"])
    if postback_data == "pto_status":
        pending = c.get_pending_pto(phone_hash)
        if not pending:
            return [{"Content": {"TextMessage": {"Body": "You have no pending time off requests."}},
                     "Suggestions": [{"Reply": {"Text": "New Request", "PostbackData": "pto_new"}},
                                     {"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}}]}]
        c.clear_pending_pto(phone_hash)
        return _approved(pending)
    if postback_data == "pto_cancel":
        c.clear_pending_pto(phone_hash)
        return _cancelled()
    if postback_data == "pto_new":
        return _balance_card(phone_hash)
    return None
