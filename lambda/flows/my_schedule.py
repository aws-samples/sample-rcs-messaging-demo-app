"""My Schedule — internal staff shift viewing, deterministic flow.

Demonstrates an INTERNAL employee/staff use case: viewing upcoming shifts and
jumping straight into Shift Swap for a shift the employee wants to trade.

Triggers: `Start: My_Schedule`, or dashboard push.
Postback prefix: sched_
"""

import common as c


def on_start(phone, phone_hash):
    return _schedule_card(phone_hash)


def on_trigger(phone, phone_hash, vignette):
    return _schedule_card(phone_hash)


def _schedule_card(phone_hash):
    rows = c.shifts()
    if not rows:
        body = "You have no upcoming shifts scheduled."
    else:
        lines = [
            f"{s['day']}, {s['date']} — {s['start']}\u2013{s['end']} ({s.get('role', '')})"
            for s in rows
        ]
        body = "Upcoming shifts:\n" + "\n".join(lines)
    name = c.tester_name(phone_hash, fallback=c.employee_name())
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "My Schedule",
                    "Description": f"{name} — {c.work_location()}\n\n{body}",
                    "Media": {"FileUrl": c.resolve_media("media/schedule.png"), "Height": "MEDIUM"},
                    "Suggestions": [
                        {"OpenUrl": {
                            "Text": "View Full Schedule", "PostbackData": "sched_wv",
                            "Url": c.webview_url("schedule"),
                            "Application": "WEBVIEW", "WebviewViewMode": "TALL",
                        }},
                    ],
                },
            }
        },
        "Suggestions": [
            {"Reply": {"Text": "Request Time Off", "PostbackData": "sched_pto"}},
            {"Reply": {"Text": "Swap a Shift", "PostbackData": "sched_swap"}},
            {"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}},
        ],
        # SMS fallback for the vignette's entry message; inactive unless the
        # stack was deployed with -c smsFallbackNumber=+1…. See common.send_rcs.
        # The shift list is plain text in the card too, so it degrades better
        # than most — it is reused verbatim, with the webview URL carrying the
        # "View Full Schedule" chip's job.
        "_fallback_body": (
            f"{c.brand_name()} — {body}\n\n"
            f"Full schedule: {c.webview_url('schedule')}"
        ),
    }]


def on_postback(phone, phone_hash, postback_data):
    if postback_data == "sched_view":
        return _schedule_card(phone_hash)
    # These two chips jump into other internal flows. channel_adapter.py
    # special-cases both postbacks to set the active flow before dispatch —
    # see the `internal` dict in handle_postback, mirroring the existing
    # home_rx/home_appt pattern used for the home-menu carousel.
    return None
