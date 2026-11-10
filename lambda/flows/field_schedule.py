"""Field Schedule — tomorrow's crew plan, deterministic (AnyBuild).

A superintendent publishes the next day's plan to "the guys in the trailer": who
is on which task, what time, and where to meet. Each person confirms with one
tap or says they can't make it (with a reason), and anyone can ask for a roll
call to see who has answered. A "can't make it" is passed to the superintendent
and the backup is offered the slot.

The recipient plays the first person on the plan; a name set on the Recipients
tab replaces the sample name. There is no second party in this single-user demo,
so the other crew members' answers are fixed in content/construction.md
(`fieldPlan.tasks[].confirmed`) and only the recipient's own answer changes.

Triggers: `Start: Field_Schedule`, or the `home_plan` postback.
Postback prefix: plan_
"""

import common as c

_STATE = "plan"
_REASONS = {"sick": "Sick", "other": "Other job", "vehicle": "Vehicle trouble"}
_WHY_PREFIX = "plan_why_"


def on_start(phone, phone_hash):
    return _plan_card(phone_hash)


def on_trigger(phone, phone_hash, vignette):
    return _plan_card(phone_hash)


def preview_message():
    return _plan_card("")


def _me(phone_hash, plan):
    """(my task dict, my display name)."""
    tasks = plan.get("tasks", [])
    mine = tasks[0] if tasks else {}
    name = c.tester_name(phone_hash, fallback=mine.get("lead", "")) if mine else ""
    return mine, name


def _roll_chip():
    return {"Reply": {"Text": "Crew Roll Call", "PostbackData": "plan_roll"}}


def _plan_card(phone_hash):
    plan, site = c.field_plan(), c.site()
    if not plan or not plan.get("tasks"):
        return [{"Content": {"TextMessage": {"Body": (
            "No crew plan is set up yet. Add `fieldPlan` in content/construction.md."
        )}}}]
    mine, name = _me(phone_hash, plan)
    crew = []
    for i, t in enumerate(plan["tasks"]):
        who = f"{name} (you)" if i == 0 else t.get("lead", "")
        crew.append(f"- {t.get('startLabel', '')}  {t.get('task', '')}: {who}")
    desc = (
        f"{plan.get('date', 'Tomorrow')} \u00b7 {site.get('lot', '')}, {site.get('community', '')}\n"
        f"Meet at {plan.get('meetPoint', 'the site')} at {plan.get('meetLabel', '')}\n\n"
        f"Your task: {mine.get('task', '')} at {mine.get('startLabel', '')}\n\n"
        "The crew:\n" + "\n".join(crew)
    )
    chips = [
        {"Reply": {"Text": "Confirm", "PostbackData": "plan_confirm"}},
        {"Reply": {"Text": "Can't Make It", "PostbackData": "plan_decline"}},
    ]
    if plan.get("startEpoch"):
        chips.append({"CreateCalendarEvent": {
            "Text": "Add to Calendar", "PostbackData": "plan_cal",
            "Title": f"{mine.get('task', 'Site work')} \u2014 {site.get('lot', '')}",
            "Description": f"Meet at {plan.get('meetPoint', 'the site')}. {c.builder_name()}",
            "StartTime": plan["startEpoch"], "EndTime": plan["endEpoch"],
        }})
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "Tomorrow's Crew Plan",
                    "Description": desc[:2000],
                    "Media": {"FileUrl": c.resolve_media("media/anybuild/field-plan.png"), "Height": "MEDIUM"},
                    "Suggestions": chips,
                },
            }
        },
        "Suggestions": [_roll_chip()],
        # SMS fallback for the entry message; inactive unless deployed with
        # -c smsFallbackNumber=+1… (see common.send_rcs). Confirming needs the
        # reply chips, so the fallback gives the plan and a number.
        "_fallback_body": (
            f"{c.brand_name()}: {plan.get('date', 'Tomorrow')}, meet at {plan.get('meetPoint', 'the site')} "
            f"{plan.get('meetLabel', '')}. Your task: {mine.get('task', '')} at {mine.get('startLabel', '')}. "
            f"To confirm or decline, call {c.member_services_phone()}."
        ),
    }]


def _confirmed_count(plan, mine_confirmed: bool) -> int:
    others = sum(1 for t in plan.get("tasks", [])[1:] if t.get("confirmed"))
    return others + (1 if mine_confirmed else 0)


def _confirm_card(phone_hash):
    plan, site = c.field_plan(), c.site()
    mine, name = _me(phone_hash, plan)
    c.set_build_state(phone_hash, _STATE, response="confirmed", reason="")
    total = len(plan.get("tasks", []))
    first = (name or "").split(" ")[0]
    return [{
        "Content": {"TextMessage": {"Body": (
            f"Thanks{', ' + first if first else ''}. You're set for {mine.get('startLabel', '')}. "
            f"{_confirmed_count(plan, True)} of {total} crew have confirmed for {plan.get('date', 'tomorrow')}."
        )}},
        "Suggestions": [_roll_chip()],
    }]


def _roll_call(phone_hash):
    plan = c.field_plan()
    mine, name = _me(phone_hash, plan)
    state = c.get_build_state(phone_hash, _STATE)
    answer = state.get("response", "")
    confirmed, waiting, out = [], [], []
    for i, t in enumerate(plan.get("tasks", [])):
        who = f"{name} (you)" if i == 0 else t.get("lead", "")
        line = f"- {who}: {t.get('task', '')}, {t.get('startLabel', '')}"
        if i == 0:
            if answer == "confirmed":
                confirmed.append(line)
            elif answer == "declined":
                out.append(line + (f" ({state.get('reason')})" if state.get("reason") else ""))
            else:
                waiting.append(line)
        elif t.get("confirmed"):
            confirmed.append(line)
        else:
            waiting.append(line)
    parts = []
    if confirmed:
        parts.append("Confirmed:\n" + "\n".join(confirmed))
    if waiting:
        parts.append("Waiting on:\n" + "\n".join(waiting))
    if out:
        parts.append(f"Can't make it ({plan.get('backup', 'a backup')} offered the slot):\n" + "\n".join(out))
    return [{"Content": {"TextMessage": {"Body": "\n\n".join(parts)}}}]


def _reason_prompt(lead="Sorry to hear it. What's the reason?"):
    return [{
        "Content": {"TextMessage": {"Body": lead + " Tap one, or type it in your own words."}},
        "Suggestions": [
            {"Reply": {"Text": label, "PostbackData": f"{_WHY_PREFIX}{key}"}}
            for key, label in _REASONS.items()
        ],
    }]


def _declined(phone_hash, reason, note=""):
    """Record "can't make it" with its reason (and the person's own words, when
    typed) and tell them who has been told."""
    plan, site = c.field_plan(), c.site()
    stored = f"{reason}: {note}" if note else reason
    c.set_build_state(phone_hash, _STATE, response="declined", reason=stored, awaiting="")
    return [{
        "Content": {"TextMessage": {"Body": (
            f"Noted: {reason}{f' ({note})' if note else ''}. "
            f"{site.get('superintendent', 'The superintendent')} has been told, "
            f"and {plan.get('backup', 'a backup')} has been offered your slot."
        )}},
        "Suggestions": [_roll_chip()],
    }]


# Typed reasons the model may pick, mapped to the label the roll call shows. The
# chip reasons above are a subset; "personal" exists only for typed answers.
_TYPED_REASONS = {"sick": "Sick", "other_job": "Other job", "vehicle": "Vehicle trouble",
                  "personal": "Personal"}


def on_freetext(phone, phone_hash, text):
    """A typed reply to the crew plan: "can't make it, truck's in the shop" or
    "I'll be there". The model only classifies it; the reason must be one of
    _TYPED_REASONS and the outcome is the same as the chips'."""
    if not c.field_plan().get("tasks"):
        return None
    awaiting = c.get_build_state(phone_hash, _STATE).get("awaiting") == "reason"
    data = c.ai_extract(
        "The user was sent tomorrow's crew plan and can confirm or say they can't make it."
        + (" They have just been asked why they can't make it." if awaiting else "")
        + ' Return {"relevant": true|false, "intent": "confirm"|"decline", '
        '"reason": "sick"|"other_job"|"vehicle"|"personal"|"", '
        '"note": "their reason in their own words, under 80 characters, or empty"}.',
        text,
    )
    if data is None:
        return _reason_prompt("I couldn't read that.") if awaiting else None
    if not data.get("relevant"):
        return None
    if data.get("intent") == "decline" or awaiting:
        reason = _TYPED_REASONS.get(data.get("reason"), "Other")
        return _declined(phone_hash, reason, c.extracted_text(data, "note", 80))
    if data.get("intent") == "confirm":
        return _confirm_card(phone_hash)
    return None


def on_postback(phone, phone_hash, postback_data):
    if postback_data == "plan_confirm":
        c.set_build_state(phone_hash, _STATE, awaiting="")
        return _confirm_card(phone_hash)
    if postback_data == "plan_decline":
        c.set_build_state(phone_hash, _STATE, awaiting="reason")
        return _reason_prompt()
    if postback_data.startswith(_WHY_PREFIX):
        reason = _REASONS.get(postback_data[len(_WHY_PREFIX):])
        if not reason:
            return _plan_card(phone_hash)
        return _declined(phone_hash, reason)
    if postback_data == "plan_roll":
        return _roll_call(phone_hash)
    return None
