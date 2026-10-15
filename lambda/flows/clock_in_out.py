"""Clock In / Clock Out — internal staff attendance, deterministic flow.

Demonstrates RCS for an INTERNAL employee/staff use case (as opposed to the
other vignettes in this project, which are all member/customer-facing):
starting or ending a work shift with a single tap, no separate workforce app.

Triggers: `Start: Clock_In_Out`, or dashboard push.
Postback prefix: clock_
"""

import common as c


def on_start(phone, phone_hash):
    return _status_card(phone_hash)


def on_trigger(phone, phone_hash, vignette):
    return _status_card(phone_hash)


def _status_card(phone_hash):
    name = c.tester_name(phone_hash, fallback=c.employee_name())
    status = c.get_shift_status(phone_hash)
    if status:
        return [{
            "Content": {
                "RichCard": {
                    "CardOrientation": "VERTICAL",
                    "CardContent": {
                        "Title": "You're Clocked In",
                        "Description": (
                            f"{name} — {c.employee_role()}\n"
                            f"{c.work_location()}\n\n"
                            f"Clocked in at {_display_time(status.get('clocked_in_at', ''))}."
                        ),
                        "Media": {"FileUrl": c.resolve_media("media/clock.png"), "Height": "MEDIUM"},
                        "Suggestions": [
                            {"Reply": {"Text": "Clock Out", "PostbackData": "clock_out"}},
                        ],
                    },
                }
            },
            "Suggestions": [{"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}}],
        }]
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "Clock In / Out",
                    "Description": (
                        f"{name} — {c.employee_role()}\n"
                        f"{c.work_location()}\n\n"
                        "You're not clocked in right now."
                    ),
                    "Media": {"FileUrl": c.resolve_media("media/clock.png"), "Height": "MEDIUM"},
                    "Suggestions": [
                        {"Reply": {"Text": "Clock In", "PostbackData": "clock_in"}},
                    ],
                },
            }
        },
        "Suggestions": [{"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}}],
        # SMS fallback for the vignette's entry message; inactive unless the
        # stack was deployed with -c smsFallbackNumber=+1…. See common.send_rcs.
        # Only the not-clocked-in branch carries one. The clocked-in branch is a
        # status read the employee asked for, whereas this branch is the one that
        # needs to reach them so a shift gets recorded. Clocking in itself needs
        # the chip, so the fallback routes to the timekeeping line.
        "_fallback_body": (
            f"{c.brand_name()}: you're not clocked in at {c.work_location()}. "
            "Rich messaging isn't available on your device right now, so please "
            f"clock in with your supervisor or call {c.member_services_phone()}."
        ),
    }]


def _display_time(iso_ts):
    # Demo-friendly: show a fixed, readable time rather than parsing/formatting
    # the ISO timestamp with timezone math for a sample employee.
    return "9:02 AM" if iso_ts else "just now"


def _clocked_out(phone_hash):
    name = c.tester_name(phone_hash, fallback=c.employee_name())
    first_name = name.split(" ")[0] if name else name
    status = c.get_shift_status(phone_hash)
    c.clock_out(phone_hash)
    duration = "7h 58m" if status else "the shift"
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "Clocked Out",
                    "Description": (
                        f"Great work today, {first_name}. See you next shift.\n\n"
                        f"Location: {c.work_location()}\n"
                        f"Duration: {duration}"
                    ),
                    "Suggestions": [
                        {"OpenUrl": {
                            "Text": "Shift Summary", "PostbackData": "clock_summary_wv",
                            "Url": c.webview_url("shift-summary"),
                            "Application": "WEBVIEW", "WebviewViewMode": "HALF",
                        }},
                    ],
                },
            }
        },
        "Suggestions": [{"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}}],
    }]


def on_postback(phone, phone_hash, postback_data):
    if postback_data == "clock_in":
        c.clock_in(phone_hash)
        return _status_card(phone_hash)
    if postback_data == "clock_out":
        return _clocked_out(phone_hash)
    return None
