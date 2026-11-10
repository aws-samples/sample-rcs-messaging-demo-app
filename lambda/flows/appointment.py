"""Appointment reminder & clinic-initiated reschedule — deterministic 2-way flow.

Two vignette ids share this module, and they are two different *scenarios*, not
two entry points into one:

- `appt_reminder` — the clinic confirms an upcoming visit. The member decides
  whether to confirm, reschedule or cancel, and any of those is a fine answer.
- `appt_reschedule` — the clinic has to move the visit (the provider is
  unavailable). The member did not ask for this and the original slot is gone,
  so the message opens straight into a required choice. This is the
  event-driven-send pattern: an unprompted outbound that lands the recipient in
  a decision, which is most of the real business value of RCS in healthcare.

Both scenarios converge once a new slot is picked, which is why they share a
module. The reschedule *copy* cannot be shared, though — `_reschedule_options`
is reached from three places with different premises, so it takes
`clinic_initiated` rather than assuming the member asked.

Triggers: `Start: Appt_Reminder`, `Start: Appt_Reschedule`, or dashboard push.
Postback prefix: appt_
"""

import common as c

# One source of truth for every date, time and calendar epoch in this flow.
# Dates are offsets in days from today (UTC), so the visit and its slots are
# always upcoming; times are 24-hour "HH:MM". A chip, the text that confirms it
# and the calendar event it attaches are all built from the same `_slot(n)`
# entry, so they cannot disagree. Chip ids carry the slot number, never a date,
# so a card sent yesterday still resolves to a valid (current) slot today.
_VISIT_MINUTES = 60
_REMINDER_VISIT = (3, "09:30")
_SLOT_PLAN = {
    1: (4, "14:00"),
    2: (7, "10:00"),
    3: (9, "08:30"),
    4: (10, "11:00"),
    5: (11, "15:30"),
    6: (14, "09:00"),
}
# Ids used by cards sent before the slots were numbered. Map them to the first
# three slots so a stale tap still lands on a real, future appointment.
_LEGACY_SLOT_IDS = {
    "appt_slot_fri": 1,
    "appt_slot_mon": 2,
    "appt_slot_wed": 3,
}


def _when(offset_days, hhmm):
    """Date, time and the labels/epochs derived from them, computed now."""
    d = c.sample_date(offset_days)
    start = c.sample_epoch(d, hhmm)
    return {
        "date": d,
        "time": hhmm,
        "label": f"{c.sample_day_label(d)} at {c.format_time_12h(hhmm)}",
        "chip": f"{c.sample_short_label(d)} {c.format_time_12h(hhmm)}",
        "start": start,
        "end": start + _VISIT_MINUTES * 60,
    }


def _visit():
    """The existing appointment the reminder is about."""
    return _when(*_REMINDER_VISIT)


def _slot(n):
    """Selectable slot `n` (1-6): date, time, long label, chip label, epochs."""
    return _when(*_SLOT_PLAN[n])


def _slot_chip(n):
    return {"Reply": {"Text": _slot(n)["chip"], "PostbackData": f"appt_slot_{n}"}}


def on_start(phone, phone_hash):
    return _reminder()


def on_trigger(phone, phone_hash, vignette):
    if "reschedule" in vignette:
        return _reschedule_options(clinic_initiated=True)
    return _reminder()


def _clinic():
    return f"{c.brand_name()} Medical Group"


def _reminder():
    visit = _visit()
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "Upcoming Appointment",
                    "Description": (
                        "Annual Physical Exam\n"
                        "Dr. Rachel Torres — Internal Medicine\n\n"
                        f"{visit['label']}\n"
                        f"{_clinic()}\n"
                        "800 Walnut St, Suite 300, Philadelphia\n\n"
                        "Please arrive 15 minutes early.\n"
                        "Bring your insurance card and photo ID."
                    ),
                    "Media": {"FileUrl": c.resolve_media("media/appointment.png"), "Height": "MEDIUM"},
                    "Suggestions": [
                        {"Reply": {"Text": "Confirm", "PostbackData": "appt_confirm"}},
                        {"Reply": {"Text": "Reschedule", "PostbackData": "appt_reschedule"}},
                    ],
                },
            }
        },
        "Suggestions": [
            {"Reply": {"Text": "Cancel", "PostbackData": "appt_cancel"}},
            {"ShowLocation": {
                "Text": "Get Directions", "PostbackData": "appt_directions",
                "Latitude": 39.9489, "Longitude": -75.1580, "Label": _clinic(),
            }},
        ],
        # SMS fallback for the vignette's entry message. Written out rather than
        # derived from the card: the card's value is in its chips and its map
        # pin, and neither survives as SMS, so the plain text has to carry the
        # appointment details and a phone number instead. Inactive unless the
        # stack was deployed with -c smsFallbackNumber=+1…; see common.send_rcs.
        "_fallback_body": (
            f"{c.brand_name()}: Annual Physical Exam with Dr. Rachel Torres, "
            f"{visit['label']}. "
            f"{_clinic()}, 800 Walnut St, Suite 300, Philadelphia. "
            "Please arrive 15 minutes early with your insurance card and photo ID. "
            f"To confirm, reschedule or cancel, call {c.member_services_phone()}."
        ),
    }]


def _confirmed():
    visit = _visit()
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "Appointment Confirmed",
                    "Description": (
                        f"See you {visit['label']}.\n\n"
                        "Reminders:\n"
                        "- Bring insurance card & photo ID\n"
                        "- Arrive 15 min early for check-in\n"
                        "- Fast for 12 hours if bloodwork ordered\n"
                        "- List any new medications or symptoms"
                    ),
                    "Suggestions": [
                        {"OpenUrl": {
                            "Text": "Pre-Visit Checklist", "PostbackData": "appt_checklist_wv",
                            "Url": c.webview_url("pre-visit"),
                            "Application": "WEBVIEW", "WebviewViewMode": "TALL",
                        }},
                        {"CreateCalendarEvent": {
                            "Text": "Add to Calendar", "PostbackData": "appt_cal",
                            "Title": "Annual Physical — Dr. Torres",
                            "Description": f"{_clinic()}, 800 Walnut St Suite 300",
                            "StartTime": visit["start"], "EndTime": visit["end"],
                        }},
                        {"ShowLocation": {
                            "Text": "Get Directions", "PostbackData": "appt_directions",
                            "Latitude": 39.9489, "Longitude": -75.1580, "Label": _clinic(),
                        }},
                    ],
                },
            }
        },
        "Suggestions": [{"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}}],
    }]


def _reschedule_options(clinic_initiated=False):
    """Slot picker, reached from three places with two different premises.

    `clinic_initiated=False` — the member tapped "Reschedule" on the reminder,
    or "Rebook" after cancelling. They already know why they're here, so the
    opening line just acknowledges the request.

    `clinic_initiated=True` — the clinic is moving the appointment and this is
    the *first* message in the conversation. "I can help you reschedule" is
    wrong here: nobody asked for help, and a member who gets that out of the
    blue has no idea which appointment it's about or why. So this branch names
    the appointment, gives the reason, and says the original slot is gone —
    everything the member needs to make the choice without replying "what?".
    """
    if clinic_initiated:
        opening = (
            f"This is {_clinic()} about your Annual Physical on "
            f"{_visit()['label']}.\n\n"
            "Dr. Torres is unexpectedly unavailable that day, so we need to move "
            "your visit. Apologies for the short notice.\n\n"
            "Here's her next availability — tap a time and we'll rebook you:"
        )
    else:
        opening = (
            "I can help you reschedule. Here are the next available slots with "
            "Dr. Torres:"
        )
    return [{
        "Content": {"TextMessage": {"Body": opening}},
        "Suggestions": [
            _slot_chip(1),
            _slot_chip(2),
            _slot_chip(3),
            {"Reply": {"Text": "More Options", "PostbackData": "appt_more_slots"}},
        ],
    }]


def _rescheduled(slot):
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "Rescheduled",
                    "Description": (
                        f"Your appointment has been moved to:\n{slot['label']}\n"
                        "Dr. Rachel Torres — Internal Medicine\n"
                        f"{_clinic()} — 800 Walnut St\n\n"
                        "We'll send a reminder 24 hours before."
                    ),
                    "Suggestions": [
                        {"CreateCalendarEvent": {
                            "Text": "Add to Calendar", "PostbackData": "appt_reschedule_cal",
                            "Title": "Annual Physical — Dr. Torres",
                            "Description": f"{_clinic()}, 800 Walnut St Suite 300",
                            "StartTime": slot["start"], "EndTime": slot["end"],
                        }},
                    ],
                },
            }
        },
        "Suggestions": [
            {"Reply": {"Text": "Got It", "PostbackData": "appt_ack"}},
            {"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}},
        ],
    }]


def _cancelled():
    return [{
        "Content": {"TextMessage": {"Body": "Your appointment has been cancelled. Would you like to rebook, or is there anything else I can help with?"}},
        "Suggestions": [
            {"Reply": {"Text": "Rebook", "PostbackData": "appt_reschedule"}},
            {"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}},
        ],
    }]


def _slot_number(postback_data):
    """1-6 for `appt_slot_<n>` (or a legacy id), else None."""
    if postback_data in _LEGACY_SLOT_IDS:
        return _LEGACY_SLOT_IDS[postback_data]
    prefix = "appt_slot_"
    if postback_data.startswith(prefix) and postback_data[len(prefix):].isdigit():
        n = int(postback_data[len(prefix):])
        if n in _SLOT_PLAN:
            return n
    return None


def _more_slots():
    """Slots 4-6, each listed in the text and offered as its own chip."""
    numbers = (4, 5, 6)
    lines = "\n".join(f"- {_slot(n)['chip']}" for n in numbers)
    return [{
        "Content": {"TextMessage": {"Body": (
            f"Additional availability:\n{lines}\n\n"
            "Tap a time to book it, or type a preferred date/time and I'll check."
        )}},
        "Suggestions": [_slot_chip(n) for n in numbers],
    }]


def on_postback(phone, phone_hash, postback_data):
    if postback_data == "appt_confirm":
        return _confirmed()
    if postback_data == "appt_reschedule":
        return _reschedule_options()
    if postback_data == "appt_cancel":
        return _cancelled()
    n = _slot_number(postback_data)
    if n is not None:
        return _rescheduled(_slot(n))
    if postback_data == "appt_more_slots":
        return _more_slots()
    if postback_data == "appt_ack":
        return [{"Content": {"TextMessage": {"Body": "You're all set! Message us anytime if you need anything."}}}]
    return None
