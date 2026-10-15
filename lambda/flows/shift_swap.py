"""Shift Swap — internal staff self-service, deterministic flow.

Demonstrates an INTERNAL employee/staff use case: offering one of your own
shifts to a coworker and getting a decision back in the same conversation.
Like PTO Request, there's no second party in this single-user demo, so
"Check Status" simulates the coworker's acceptance the first time it's
tapped.

Triggers: `Start: Shift_Swap`, or dashboard push.
Postback prefix: swap_
"""

import common as c


def on_start(phone, phone_hash):
    return _pick_shift(phone_hash)


def on_trigger(phone, phone_hash, vignette):
    return _pick_shift(phone_hash)


def _pick_shift(phone_hash):
    pending = c.get_pending_swap(phone_hash)
    if pending:
        return _pending_card(pending)
    rows = c.shifts()
    if not rows:
        return [{"Content": {"TextMessage": {"Body": "You have no upcoming shifts to swap."}}}]
    suggestions = [
        {"Reply": {"Text": f"{s['day']} {s['date']}", "PostbackData": f"swap_shift_{s['id']}"}}
        for s in rows[:4]
    ]
    name = c.tester_name(phone_hash, fallback=c.employee_name())
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "Swap a Shift",
                    "Description": (
                        f"{name} — {c.work_location()}\n\n"
                        "Which of your shifts would you like to offer for a swap?"
                    ),
                    "Media": {"FileUrl": c.resolve_media("media/shift-swap.png"), "Height": "MEDIUM"},
                    "Suggestions": suggestions,
                },
            }
        },
        "Suggestions": [{"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}}],
        # SMS fallback for the vignette's entry message; inactive unless the
        # stack was deployed with -c smsFallbackNumber=+1…. See common.send_rcs.
        # A swap needs two taps (shift, then coworker), so there is no way to
        # complete it over SMS. The fallback says so and routes to a human rather
        # than starting a flow it cannot finish.
        "_fallback_body": (
            f"{c.brand_name()}: to offer one of your shifts for a swap, rich "
            "messaging needs to be available on your device. Please arrange the "
            f"swap with your supervisor or call {c.member_services_phone()}."
        ),
    }]


def _pick_coworker(shift_id):
    shift = c.shift_by_id(shift_id)
    label = f"{shift['day']}, {shift['date']} \u2013 {shift['start']}\u2013{shift['end']}" if shift else "your shift"
    cws = c.coworkers()
    suggestions = [
        {"Reply": {"Text": cw["name"].split(" ")[0], "PostbackData": f"swap_offer_{shift_id}_{cw['id']}"}}
        for cw in cws[:3]
    ]
    return [{
        "Content": {
            "TextMessage": {
                "Body": f"Offering: {label}\n\nWho would you like to offer it to?"
            }
        },
        "Suggestions": suggestions,
    }]


def _submitted(phone_hash, shift_id, coworker_id):
    c.set_pending_swap(phone_hash, shift_id, coworker_id)
    return _pending_card(c.get_pending_swap(phone_hash))


def _pending_card(pending):
    shift = c.shift_by_id(pending["my_shift_id"])
    cw = c.coworker_by_id(pending["coworker_id"])
    shift_label = f"{shift['day']}, {shift['date']} \u2013 {shift['start']}\u2013{shift['end']}" if shift else "your shift"
    cw_name = cw["name"] if cw else "your coworker"
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "Swap Offered",
                    "Description": (
                        f"You offered {shift_label} to {cw_name}.\n\n"
                        "Waiting for them to accept. We'll let you know here as soon as they respond."
                    ),
                    "Suggestions": [
                        {"Reply": {"Text": "Check Status", "PostbackData": "swap_status"}},
                    ],
                },
            }
        },
        "Suggestions": [
            {"Reply": {"Text": "Cancel Offer", "PostbackData": "swap_cancel"}},
            {"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}},
        ],
    }]


def _accepted(pending):
    shift = c.shift_by_id(pending["my_shift_id"])
    cw = c.coworker_by_id(pending["coworker_id"])
    shift_label = f"{shift['day']}, {shift['date']} \u2013 {shift['start']}\u2013{shift['end']}" if shift else "your shift"
    cw_name = cw["name"] if cw else "Your coworker"
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "Swap Accepted",
                    "Description": (
                        f"{cw_name} accepted your swap. {shift_label} is now covered.\n\n"
                        f"{c.manager_name()} has been notified automatically \u2014 no need to follow up."
                    ),
                    "Suggestions": [
                        {"OpenUrl": {
                            "Text": "View Schedule", "PostbackData": "swap_view_schedule",
                            "Url": c.webview_url("schedule"),
                            "Application": "WEBVIEW", "WebviewViewMode": "TALL",
                        }},
                    ],
                },
            }
        },
        "Suggestions": [{"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}}],
    }]


def _cancelled():
    return [{
        "Content": {"TextMessage": {"Body": "Your swap offer has been cancelled."}},
        "Suggestions": [
            {"Reply": {"Text": "New Swap", "PostbackData": "swap_new"}},
            {"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}},
        ],
    }]


def on_postback(phone, phone_hash, postback_data):
    if postback_data.startswith("swap_shift_"):
        shift_id = postback_data[len("swap_shift_"):]
        return _pick_coworker(shift_id)
    if postback_data.startswith("swap_offer_"):
        # Postback carries "<shift_id>_<coworker_id>", e.g. "shift_mon_coworker_dana".
        # Both id sets are fixed/known from workplace.md, so recover the split
        # by matching a known shift id as a prefix rather than parsing
        # positionally (coworker ids also contain underscores).
        rest = postback_data[len("swap_offer_"):]
        shift_id, coworker_id = _split_offer(rest)
        return _submitted(phone_hash, shift_id, coworker_id)
    if postback_data == "swap_status":
        pending = c.get_pending_swap(phone_hash)
        if not pending:
            return [{"Content": {"TextMessage": {"Body": "You have no pending swap offers."}},
                     "Suggestions": [{"Reply": {"Text": "New Swap", "PostbackData": "swap_new"}},
                                     {"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}}]}]
        c.clear_pending_swap(phone_hash)
        return _accepted(pending)
    if postback_data == "swap_cancel":
        c.clear_pending_swap(phone_hash)
        return _cancelled()
    if postback_data == "swap_new":
        return _pick_shift(phone_hash)
    return None


def _split_offer(rest):
    """rest is "<shift_id>_<coworker_id>". Both ids are known/fixed sets from
    workplace.md, so recover the split by checking known shift ids as a
    prefix rather than guessing a delimiter position."""
    for s in c.shifts():
        prefix = s["id"] + "_"
        if rest.startswith(prefix):
            return s["id"], rest[len(prefix):]
    return None, None
