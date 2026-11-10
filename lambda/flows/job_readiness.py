"""Job Readiness — dependencies and hand-offs between trades, deterministic (AnyBuild).

On a jobsite, work waits on other work: countertops can't go on until the lower
cabinets are in, and the backsplash waits on the countertops. This vignette shows
that chain, and what happens at each hand-off.

The chain comes from content/construction.md (`readiness.chain`); each step
lists the ids it `needs`. When the first trade marks its step done ("Cabinets
Done"), every step whose needs are now all met is cleared, and the crew for the
next one receives a ready message with a proposed start. That crew can accept,
propose another date, or push back with a reason ("Cabinets not level"), which
reopens the earlier step and blocks the chain again. A step the crew has
accepted is "scheduled", not "done", so what depends on it keeps waiting.

There is one phone in this demo, so it plays both crews: the cabinet trade's
"Cabinets Done" tap and the countertop crew's reply both come from it. In a real
deployment each message goes to that trade's own contact.

Triggers: `Start: Job_Readiness`, or the `home_ready` postback.
Postback prefix: ready_
"""

import common as c

_STATE = "ready"
_DONE = "ready_done_"
_ACCEPT = "ready_accept_"
_PROPOSE = "ready_propose_"
_NOTREADY = "ready_notready_"
_DATE = "ready_date_"
_ISSUE = "ready_issue_"


def on_start(phone, phone_hash):
    return _chain_card(phone_hash)


def on_trigger(phone, phone_hash, vignette):
    return _chain_card(phone_hash)


def preview_message():
    return _chain_card("")


def _chain():
    return c.readiness().get("chain", [])


def _step(sid):
    return next((s for s in _chain() if s["id"] == sid), None)


def _state(phone_hash):
    st = c.get_build_state(phone_hash, _STATE)
    return {"done": list(st.get("done", []) or []), "scheduled": dict(st.get("scheduled", {}) or {}),
            "issue": st.get("issue", "")}


def _status(step, st):
    """"done", "scheduled", "ready" (all needs done) or "waiting"."""
    sid = step["id"]
    if sid in st["done"]:
        return "done"
    if sid in st["scheduled"]:
        return "scheduled"
    needs = step.get("needs", []) or []
    return "ready" if all(n in st["done"] for n in needs) else "waiting"


def _line(step, st):
    status = _status(step, st)
    head = f"{step.get('name', '')} ({step.get('trade', '')})"
    if status == "done":
        return f"Done: {head}"
    if status == "scheduled":
        return f"Scheduled {st['scheduled'][step['id']]}: {head}"
    if status == "ready":
        return f"Ready to start: {head}" if step.get("needs") else f"Not done yet: {head}"
    blockers = [(_step(n) or {}).get("name", n) for n in step.get("needs", []) if n not in st["done"]]
    return f"Waiting: {head}, needs {', '.join(blockers).lower()}"


def _chain_card(phone_hash):
    chain, site = _chain(), c.site()
    if not chain:
        return [{"Content": {"TextMessage": {"Body": (
            "No readiness chain is set up yet. Add `readiness` in content/construction.md."
        )}}}]
    st = _state(phone_hash)
    lines = [_line(s, st) for s in chain]
    desc = f"{site.get('lot', '')}, {site.get('community', '')}\n\n" + "\n".join(f"- {l}" for l in lines)
    if st["issue"]:
        desc += f"\n\nOpen issue: {st['issue']}"
    chips = [
        {"Reply": {"Text": s["doneChip"][:25], "PostbackData": f"{_DONE}{s['id']}"}}
        for s in chain if s.get("doneChip") and _status(s, st) == "ready"
    ]
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "What's Ready",
                    "Description": desc[:2000],
                    "Media": {"FileUrl": c.resolve_media("media/anybuild/readiness.png"), "Height": "MEDIUM"},
                    **({"Suggestions": chips[:4]} if chips else {}),
                },
            }
        },
        # SMS fallback for the entry message; inactive unless deployed with
        # -c smsFallbackNumber=+1… (see common.send_rcs). The status lines are
        # plain text already; the hand-off taps need rich messaging.
        "_fallback_body": f"{c.brand_name()} {site.get('lot', '')}: " + " ".join(lines),
    }]


def _directions(site):
    return {"ShowLocation": {
        "Text": "Directions to Site", "PostbackData": "ready_directions",
        "Latitude": site.get("lat", 0), "Longitude": site.get("lng", 0),
        "Label": f"{site.get('lot', 'Jobsite')} \u2014 {site.get('address', '')}"[:100],
    }}


def _ready_notice(step, prereq_names):
    """The message to the crew of `step`: it is cleared, with a proposed start."""
    site = c.site()
    return {
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": f"Ready: {step.get('name', '')}"[:200],
                    "Description": (
                        f"Done: {', '.join(prereq_names)}.\n"
                        f"{site.get('lot', 'The lot')} is ready for {step.get('trade', 'your crew')}.\n\n"
                        f"Proposed start: {step.get('date', '')}, {step.get('startLabel', '')}\n"
                        f"Site: {site.get('address', '')}\n"
                        f"Superintendent: {site.get('superintendent', '')}"
                    )[:2000],
                    "Suggestions": [
                        {"Reply": {"Text": "Accept", "PostbackData": f"{_ACCEPT}{step['id']}"}},
                        {"Reply": {"Text": "Propose New Date", "PostbackData": f"{_PROPOSE}{step['id']}"}},
                        {"Reply": {"Text": "Not Ready", "PostbackData": f"{_NOTREADY}{step['id']}"}},
                        _directions(site),
                    ],
                },
            }
        },
    }


def _mark_done(phone_hash, sid):
    step = _step(sid)
    if not step:
        return _chain_card(phone_hash)
    st = _state(phone_hash)
    if sid not in st["done"]:
        st["done"].append(sid)
    c.set_build_state(phone_hash, _STATE, done=st["done"], issue="")
    st = _state(phone_hash)
    # Steps this just cleared: not done or scheduled, and every need now met.
    cleared = [s for s in _chain()
               if _status(s, st) == "ready" and sid in (s.get("needs") or [])]
    out = [{"Content": {"TextMessage": {"Body": (
        f"{step.get('name', '')} marked done by {step.get('trade', 'the trade')}."
        + (f" {len(cleared)} step{'s' if len(cleared) != 1 else ''} cleared to start." if cleared else "")
    )}}}]
    for nxt in cleared:
        needs = [(_step(n) or {}).get("name", n) for n in nxt.get("needs", [])]
        out.append(_ready_notice(nxt, needs))
    return out


def _accepted(phone_hash, sid, date_label=None, start_epoch=None, end_epoch=None, note=""):
    step = _step(sid)
    st = _state(phone_hash)
    when = date_label or step.get("date", "")
    st["scheduled"][sid] = when
    c.set_build_state(phone_hash, _STATE, scheduled=st["scheduled"])
    site = c.site()
    after = [s for s in _chain() if sid in (s.get("needs") or [])]
    content = {
        "Title": "Start Confirmed",
        "Description": (
            f"{step.get('name', '')}: {when}, {step.get('startLabel', '')}\n"
            f"Site: {site.get('lot', '')}, {site.get('address', '')}\n\n"
            + (f"{note}\n\n" if note else "")
            + (f"{after[0].get('trade', '')} is next, once this is installed." if after else
               "Nothing else is waiting on this step.")
        ),
        "Suggestions": [{"Reply": {"Text": "See What's Ready", "PostbackData": "ready_chain"}}],
    }
    s_e = start_epoch or step.get("startEpoch")
    e_e = end_epoch or step.get("endEpoch")
    if s_e:
        content["Suggestions"].insert(0, {"CreateCalendarEvent": {
            "Text": "Add to Calendar", "PostbackData": "ready_cal",
            "Title": f"{step.get('name', '')} \u2014 {site.get('lot', '')}",
            "Description": f"{step.get('trade', '')} for {c.builder_name()} at {site.get('address', '')}",
            "StartTime": s_e, "EndTime": e_e,
        }})
    return [{"Content": {"RichCard": {"CardOrientation": "VERTICAL", "CardContent": content}}}]


def _parse(postback_data, prefix):
    """The step id after `prefix`, if it is a known step id, else None."""
    rest = postback_data[len(prefix):]
    return rest if _step(rest) else None


def _alt_dates(step):
    return [(off, c.sample_day_label(c.sample_date(off)))
            for off in (step.get("altStartDayOffsets") or [])
            if isinstance(off, int) and not isinstance(off, bool)][:4]


def on_postback(phone, phone_hash, postback_data):
    if postback_data == "ready_chain":
        return _chain_card(phone_hash)
    if postback_data.startswith(_DONE):
        sid = _parse(postback_data, _DONE)
        return _mark_done(phone_hash, sid) if sid else _chain_card(phone_hash)
    if postback_data.startswith(_ACCEPT):
        sid = _parse(postback_data, _ACCEPT)
        return _accepted(phone_hash, sid) if sid else _chain_card(phone_hash)
    if postback_data.startswith(_PROPOSE):
        sid = _parse(postback_data, _PROPOSE)
        step = _step(sid) if sid else None
        alts = _alt_dates(step) if step else []
        if not alts:
            return _chain_card(phone_hash)
        return [{
            "Content": {"TextMessage": {"Body": "Which start date works for your crew?"}},
            "Suggestions": [
                {"Reply": {"Text": label[:25], "PostbackData": f"{_DATE}{sid}_{off}"}} for off, label in alts
            ],
        }]
    if postback_data.startswith(_DATE):
        rest = postback_data[len(_DATE):]
        sid, _, off = rest.rpartition("_")
        step = _step(sid)
        try:
            offset = int(off)
        except ValueError:
            offset = None
        if not step or offset is None or offset not in [o for o, _ in _alt_dates(step)]:
            return _chain_card(phone_hash)
        d = c.sample_date(offset)
        days = max(int(step.get("durationDays", 1) or 1), 1)
        return _accepted(
            phone_hash, sid, date_label=c.sample_day_label(d),
            start_epoch=c.sample_epoch(d, step.get("startTime", "")),
            end_epoch=c.sample_epoch(c.sample_date(offset + days - 1), "17:00"),
            note=f"{c.site().get('superintendent', 'The superintendent')} approved your new date.",
        )
    if postback_data.startswith(_NOTREADY):
        sid = _parse(postback_data, _NOTREADY)
        if not sid:
            return _chain_card(phone_hash)
        issues = [str(i) for i in (c.readiness().get("issues") or []) if isinstance(i, str)][:4]
        return [{
            "Content": {"TextMessage": {"Body": "What's holding it up?"}},
            "Suggestions": [
                {"Reply": {"Text": text[:25], "PostbackData": f"{_ISSUE}{sid}_{i}"}}
                for i, text in enumerate(issues)
            ],
        }]
    if postback_data.startswith(_ISSUE):
        rest = postback_data[len(_ISSUE):]
        sid, _, idx = rest.rpartition("_")
        step = _step(sid)
        issues = [str(i) for i in (c.readiness().get("issues") or []) if isinstance(i, str)]
        try:
            text = issues[int(idx)]
        except (ValueError, IndexError):
            text = ""
        if not step or not text:
            return _chain_card(phone_hash)
        return _flag_issue(phone_hash, step, text)
    return None


def _flag_issue(phone_hash, step, text, retry_label=""):
    """The crew pushes back: reopen the steps `step` needs and tell everyone why.
    `retry_label` is a restart date the crew proposed, when it gave one."""
    st = _state(phone_hash)
    for need in step.get("needs", []) or []:
        if need in st["done"]:
            st["done"].remove(need)
    st["scheduled"].pop(step["id"], None)
    c.set_build_state(phone_hash, _STATE, done=st["done"], scheduled=st["scheduled"], issue=text)
    site = c.site()
    needs = [(_step(n) or {}).get("trade", n) for n in step.get("needs", [])]
    return [{
        "Content": {"TextMessage": {"Body": (
            f"Flagged: {text}. {site.get('superintendent', 'The superintendent')} and "
            f"{', '.join(needs) or 'the earlier trade'} have been told, and "
            f"{step.get('name', 'this step').lower()} is on hold until it's fixed."
            + (f" The crew proposed restarting {retry_label}." if retry_label else "")
        )}},
        "Suggestions": [{"Reply": {"Text": "See What's Ready", "PostbackData": "ready_chain"}}],
    }]


# How far ahead a typed restart date may be.
_MAX_DATE_DAYS = 60


def _typed_date(value):
    """A typed date the code accepts: from tomorrow to _MAX_DATE_DAYS ahead."""
    d = c.parse_iso_date(value)
    today = c.sample_date(0)
    if d and 1 <= (d - today).days <= _MAX_DATE_DAYS:
        return d
    return None


def on_freetext(phone, phone_hash, text):
    """A typed reply at a hand-off: "cabinets are done", "we'll take it",
    "Thursday works better", or "cabinets aren't level, two doors missing, try
    Monday". The model only classifies it and pulls out the issue and the date;
    the step comes from the chain's state and the date is checked here."""
    chain = _chain()
    if not chain:
        return None
    st = _state(phone_hash)
    # The step whose crew is being asked (cleared, not yet accepted), and the
    # first step a trade can still mark done.
    asked = next((s for s in chain if s.get("needs") and _status(s, st) == "ready"), None)
    open_step = next((s for s in chain if s.get("doneChip") and _status(s, st) == "ready"), None)
    if not asked and not open_step:
        return None
    if asked:
        context = (f"The {asked.get('trade', 'crew')} was told that \"{asked.get('name', '')}\" is "
                   f"ready to start on {asked.get('date', 'the proposed date')}.")
    else:
        context = (f"{open_step.get('trade', 'The trade')} can report that "
                   f"\"{open_step.get('name', '')}\" is done.")
    data = c.ai_extract(
        f"{context} Return {{\"relevant\": true|false, "
        '"intent": "done"|"accept"|"new_date"|"not_ready", '
        '"issue": "what is wrong on site, under 60 characters, or empty", '
        '"date": "a start date they propose, YYYY-MM-DD, or empty"}. '
        "not_ready means they report a problem with the site or the earlier work, even if "
        "they also propose a date; new_date means only that another date suits them better.",
        text,
    )
    if data is None:
        if asked:
            notice = _ready_notice(asked, [(_step(n) or {}).get("name", n) for n in asked.get("needs", [])])
            return [{"Content": {"TextMessage": {"Body": "I couldn't read that. Use the options below."}}}, notice]
        return None
    if not data.get("relevant"):
        return None
    intent = data.get("intent")
    # A reported problem always puts the step on hold, so a typed date never
    # confirms a start the crew just said the site isn't ready for.
    if intent == "new_date" and c.extracted_text(data, "issue", 60):
        intent = "not_ready"
    if intent == "done" and open_step:
        return _mark_done(phone_hash, open_step["id"])
    if not asked:
        return None
    if intent == "accept":
        return _accepted(phone_hash, asked["id"])
    d = _typed_date(data.get("date"))
    if intent == "not_ready":
        issue = c.extracted_text(data, "issue", 60) or "Not ready"
        return _flag_issue(phone_hash, asked, issue, c.sample_day_label(d) if d else "")
    if intent == "new_date":
        if not d:
            return [{"Content": {"TextMessage": {"Body": (
                f"I need a date from tomorrow to {_MAX_DATE_DAYS} days out."
            )}}}] + (on_postback(phone, phone_hash, f"{_PROPOSE}{asked['id']}") or [])
        days = max(int(asked.get("durationDays", 1) or 1), 1)
        offset = (d - c.sample_date(0)).days
        return _accepted(
            phone_hash, asked["id"], date_label=c.sample_day_label(d),
            start_epoch=c.sample_epoch(d, asked.get("startTime", "")),
            end_epoch=c.sample_epoch(c.sample_date(offset + days - 1), "17:00"),
            note=f"{c.site().get('superintendent', 'The superintendent')} approved your new date.",
        )
    return None
