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


def on_start(phone, phone_hash):
    return _reminder()


def on_trigger(phone, phone_hash, vignette):
    if "reschedule" in vignette:
        return _reschedule_options(clinic_initiated=True)
    return _reminder()


def _clinic():
    return f"{c.brand_name()} Medical Group"


def _reminder():
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "Upcoming Appointment",
                    "Description": (
                        "Annual Physical Exam\n"
                        "Dr. Rachel Torres — Internal Medicine\n\n"
                        "Thursday, July 10 at 9:30 AM\n"
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
            "Thursday July 10 at 9:30 AM. "
            f"{_clinic()}, 800 Walnut St, Suite 300, Philadelphia. "
            "Please arrive 15 minutes early with your insurance card and photo ID. "
            f"To confirm, reschedule or cancel, call {c.member_services_phone()}."
        ),
    }]


def _confirmed():
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "Appointment Confirmed",
                    "Description": (
                        "See you Thursday, July 10 at 9:30 AM.\n\n"
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
                            "StartTime": 1752148200, "EndTime": 1752151800,
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
            f"This is {_clinic()} about your Annual Physical on Thursday, "
            "July 10 at 9:30 AM.\n\n"
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
            {"Reply": {"Text": "Fri 7/11 2:00 PM", "PostbackData": "appt_slot_fri"}},
            {"Reply": {"Text": "Mon 7/14 10:00 AM", "PostbackData": "appt_slot_mon"}},
            {"Reply": {"Text": "Wed 7/16 8:30 AM", "PostbackData": "appt_slot_wed"}},
            {"Reply": {"Text": "More Options", "PostbackData": "appt_more_slots"}},
        ],
    }]


def _rescheduled(slot_text):
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "Rescheduled",
                    "Description": (
                        f"Your appointment has been moved to:\n{slot_text}\n"
                        "Dr. Rachel Torres — Internal Medicine\n"
                        f"{_clinic()} — 800 Walnut St\n\n"
                        "We'll send a reminder 24 hours before."
                    ),
                    "Suggestions": [
                        {"CreateCalendarEvent": {
                            "Text": "Add to Calendar", "PostbackData": "appt_reschedule_cal",
                            "Title": "Annual Physical — Dr. Torres",
                            "Description": f"{_clinic()}, 800 Walnut St Suite 300",
                            "StartTime": 1752235200, "EndTime": 1752238800,
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


_SLOTS = {
    "appt_slot_fri": "Friday, July 11 at 2:00 PM",
    "appt_slot_mon": "Monday, July 14 at 10:00 AM",
    "appt_slot_wed": "Wednesday, July 16 at 8:30 AM",
}


def on_postback(phone, phone_hash, postback_data):
    if postback_data == "appt_confirm":
        return _confirmed()
    if postback_data == "appt_reschedule":
        return _reschedule_options()
    if postback_data == "appt_cancel":
        return _cancelled()
    if postback_data in _SLOTS:
        return _rescheduled(_SLOTS[postback_data])
    if postback_data == "appt_more_slots":
        return [{"Content": {"TextMessage": {"Body": "Additional availability:\n- Thu 7/17 11:00 AM\n- Fri 7/18 3:30 PM\n- Mon 7/21 9:00 AM\n\nOr type a preferred date/time and I'll check."}}}]
    if postback_data == "appt_ack":
        return [{"Content": {"TextMessage": {"Body": "You're all set! Message us anytime if you need anything."}}}]
    return None
