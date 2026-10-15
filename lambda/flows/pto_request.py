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

_RANGES = {
    "pto_range_a": ("Mon, Jul 21", "Tue, Jul 22", 2),
    "pto_range_b": ("Mon, Aug 4", "Fri, Aug 8", 5),
    "pto_range_c": ("Mon, Sep 1", "Mon, Sep 1", 1),
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
                        {"Reply": {"Text": "Jul 21\u201322 (2 days)", "PostbackData": "pto_range_a"}},
                        {"Reply": {"Text": "Aug 4\u20138 (5 days)", "PostbackData": "pto_range_b"}},
                        {"Reply": {"Text": "Sep 1 (1 day)", "PostbackData": "pto_range_c"}},
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
    span = pending["start_label"] if pending["start_label"] == pending["end_label"] else f"{pending['start_label']} \u2013 {pending['end_label']}"
    remaining = c.pto_balance_days() - float(pending["days"])
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "Time Off Approved",
                    "Description": (
                        f"{c.manager_name()} approved your request for {span}.\n\n"
                        f"Remaining PTO balance: {remaining:g} days"
                    ),
                    "Suggestions": [
                        {"CreateCalendarEvent": {
                            "Text": "Add to Calendar", "PostbackData": "pto_cal",
                            "Title": "Time Off", "Description": "Approved time off",
                            "StartTime": 1753070400, "EndTime": 1753156800,
                        }},
                    ],
                },
            }
        },
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


def on_postback(phone, phone_hash, postback_data):
    if postback_data in _RANGES:
        start, end, days = _RANGES[postback_data]
        return _submitted(phone_hash, start, end, days)
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
