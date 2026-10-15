"""Chime SDK meeting orchestration for the video-visit vignette.

A video visit is two participants in one Chime SDK meeting: the **member**, in a
WebRTC client inside the RCS in-conversation webview
(lambda/webviews/video-visit.html), and the **clinician**, in the operator
dashboard (web/src/components/VideoVisitModal.tsx). Both exchange the same visit
token for join material, which is what puts them in the same room.

Shape of the thing: a *visit token* is minted when the vignette is sent and
stored in DynamoDB with a short TTL. The Chime meeting itself is created lazily
on the first join, so sending the card costs nothing — a meeting is only billed
once somebody actually opens it.

Why a pre-minted token rather than create-on-demand: /api/video/* cannot be
authenticated. It is called from a member's in-app browser session, which has no
way to hold the operator's dashboard API key — the same constraint as
/api/uploads/presign and /api/secure-doc. An endpoint that created a meeting for
any id it was handed would let anyone who found the URL spend money on Chime
attendee-minutes. So the endpoint only ever serves tokens this deployment already
minted, the token is a 122-bit uuid4, it expires, and the number of joins per
visit is capped.

Two things here are shaped by problems found in testing this sample, and
reverting either one brings back a failure that looks like a WebRTC connection
problem:

  • **Joins are budgeted, not counted as live participants.** The first version
    capped *attendees* at 4 and claimed a slot per join with no way to release
    it, so an operator who retried a failed join four times locked themselves out
    of their own visit with "this visit already has 4 participants" — while the
    member sat in the meeting. A rejoin after a dropped connection, a page
    reload, or a failed SDK load is normal and must stay cheap. MAX_JOINS is now
    a generous spend ceiling, not a room capacity.

  • **Leaving is role-scoped.** The first version had end() delete the meeting for
    everybody, and the webview calls it on `pagehide` — which in an iOS webview
    fires when the page is merely backgrounded. A member glancing at another app
    destroyed the meeting under the clinician, and the next join created a
    *different* meeting, so the two ended up in separate empty rooms. Now a
    member leaving only ends the visit if the clinician isn't there.

HIPAA: a clinician-patient video visit is a healthcare context, and a real
deployment would carry Protected Health Information (in the media stream, and
potentially in anything logged around it). This demo is not a HIPAA-compliant
system. If you adapt it for real PHI you are responsible for the controls beyond
what it provides -- an AWS Business Associate Addendum (BAA) that covers every
service in the path (Amazon Chime SDK, DynamoDB, Lambda, S3), encryption, audit
logging, and access controls. See https://aws.amazon.com/compliance/hipaa-compliance/
and confirm each service's HIPAA eligibility.
"""

import os
import json
import time
import uuid

import boto3
from botocore.exceptions import ClientError

import common as c

# Chime SDK Meetings has its own control-plane endpoint and is not available in
# every Region; the media Region is a separate choice from the control-plane
# Region. Both default to the deploy Region and are overridable so a deploy
# outside Chime's footprint can still point at a supported one.
CHIME_CONTROL_REGION = os.environ.get("CHIME_CONTROL_REGION", c.REGION)
CHIME_MEDIA_REGION = os.environ.get("CHIME_MEDIA_REGION", c.REGION)

# How long a visit link stays usable. Long enough for a member to notice the
# message and tap it, short enough that a link leaking later is worthless.
#
# It is measured from the moment the token is minted and is a hard cutoff for
# getting in: past it, join refuses (no join budget spent, no attendee created)
# and status and ping answer as they do for an unknown token, whether or not
# DynamoDB has deleted the row yet (it does so on its own schedule, typically
# within a few days of the ttl). A call already under way is not cut off, because
# the Chime session does not depend on this row, but nobody can rejoin it and its
# presence is no longer tracked.
#
# end() is the exception: it never checks the ttl, because it only releases
# things. A consult that runs past the cutoff can still be torn down by the
# clinician's "Leave and end visit", rather than staying up (and billing) with the
# member still in it. That holds for as long as the row exists; once DynamoDB has
# deleted it the meeting id is gone, and Chime's own limits are the backstop (a
# meeting ends after five continuous minutes with no attendees, or after 24 hours).
VISIT_TTL_SECONDS = 1800  # 30 minutes

# The two sides of a visit. Not free-form: the role decides who is allowed to end
# the meeting for everybody, and it is supplied by an unauthenticated caller, so
# an unrecognised value is rejected rather than defaulted.
MEMBER = "member"
CLINICIAN = "clinician"
ROLES = (MEMBER, CLINICIAN)

# Total CreateAttendee calls allowed per visit — the cost control, since this
# endpoint is necessarily unauthenticated and every attendee is billed per
# minute. Sized to be invisible to a real visit (two participants, each free to
# reload or reconnect several times) and still finite for anyone who finds a
# token. It is NOT a room capacity; see the module docstring.
MAX_JOINS = 12

# How long a heartbeat vouches for someone's presence. The clients ping every
# ~15s, so this tolerates one missed ping plus latency. Too short and the
# clinician's "patient is waiting" indicator flickers; too long and it keeps
# claiming somebody is there well after they closed the page.
PRESENCE_TTL_SECONDS = 45

_chime = None


def _client():
    # Built lazily so importing this module (which dashboard_handler does on
    # every cold start, for every route) costs nothing when no call is made.
    global _chime
    if _chime is None:
        _chime = boto3.client("chime-sdk-meetings", region_name=CHIME_CONTROL_REGION)
    return _chime


def _key(token):
    return {"pk": f"VISIT#{token}", "sk": "MEETING"}


def _seen_attr(role):
    return f"seen_{role}"


# Condition for a write that must only land on a visit that exists and has not
# expired, same boundary as common.unexpired. A guard on the write rather than a
# read first, so a heartbeat stays a single DynamoDB call. The caller binds #ttl
# to "ttl" and :now to the current epoch second. Only _touch uses it: end()
# deliberately does not.
_LIVE = "attribute_exists(pk) AND (attribute_not_exists(#ttl) OR #ttl > :now)"


def create_visit(phone_hash="", label="Video visit"):
    """Mint a visit token. Called when the vignette is sent, before any Chime
    resource exists — so an unopened invitation costs nothing."""
    token = uuid.uuid4().hex
    c.table.put_item(Item={
        **_key(token),
        "phone_hash": phone_hash,
        "label": label,
        "created_at": int(time.time()),
        "ttl": int(time.time()) + VISIT_TTL_SECONDS,
    })
    return token


def visit_url(token):
    return c.webview_url("video-visit", visit=token)


def join(token, role=MEMBER):
    """Exchange a visit token for Chime join material.

    Returns {"Meeting": …, "Attendee": …} — exactly the two objects
    MeetingSessionConfiguration takes in the browser — or {"error": …}.
    """
    if not token:
        return {"error": "missing visit token"}
    if role not in ROLES:
        return {"error": "unknown participant role"}
    item = c.unexpired(c.table.get_item(Key=_key(token)).get("Item"))
    if not item:
        # Unknown and expired get the same answer, which is the correct one to
        # give either way. unexpired() applies the ttl here because the row
        # outlives it until DynamoDB gets round to deleting it.
        return {"error": "unknown or expired visit"}

    # Spend the join budget *before* creating the attendee, so a burst cannot
    # overshoot it. Costs an unused unit if CreateAttendee then fails, which is
    # the safe direction to fail in.
    try:
        c.table.update_item(
            Key=_key(token),
            UpdateExpression="ADD join_count :one",
            ConditionExpression="attribute_not_exists(join_count) OR join_count < :max",
            ExpressionAttributeValues={":one": 1, ":max": MAX_JOINS},
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            print(f"VIDEO_VISIT_BUDGET_EXHAUSTED token={token[:8]}… role={role}")
            return {"error": "this visit has been rejoined too many times — send a new invitation"}
        raise

    meeting = _ensure_meeting(token, item)
    if "error" in meeting:
        return meeting

    try:
        attendee = _client().create_attendee(
            MeetingId=meeting["MeetingId"],
            # Not the phone number and not the conversation hash: the external
            # user id is echoed to every other attendee in the meeting, so it
            # carries the role (which the other side may legitimately show) and
            # nothing else.
            ExternalUserId=f"{role}-{uuid.uuid4().hex[:8]}",
        )["Attendee"]
    except ClientError as e:
        # A meeting can be terminated out from under us (Chime ends idle
        # meetings). Drop the stored meeting so the next join makes a fresh one
        # rather than failing forever on a dead id.
        if e.response["Error"]["Code"] in ("NotFoundException", "BadRequestException"):
            _forget_meeting(token)
            return {"error": "that visit has ended — try joining again"}
        raise

    _touch(token, role)
    print(f"VIDEO_VISIT_JOIN token={token[:8]}… role={role} meeting={meeting['MeetingId']} "
          f"attendee={attendee['AttendeeId']} media_region={meeting.get('MediaRegion')}")
    return {"Meeting": meeting, "Attendee": attendee}


def _ensure_meeting(token, item):
    stored = item.get("meeting")
    if stored:
        return json.loads(stored)

    try:
        meeting = _client().create_meeting(
            ClientRequestToken=token,          # idempotent on retry
            MediaRegion=CHIME_MEDIA_REGION,
            ExternalMeetingId=token[:64],
        )["Meeting"]
    except ClientError as e:
        # The error code only: the failed request carried the whole token as
        # ClientRequestToken and ExternalMeetingId, and a validation error can
        # echo those values back into the log.
        print(f"VIDEO_VISIT_CREATE_FAILED token={token[:8]}… {c.error_code(e)}")
        return {"error": f"could not create the meeting: {e.response['Error']['Code']}"}

    # Both sides can tap at the same instant. Claim the slot conditionally and,
    # if we lost, throw away the meeting we just created and use the winner's —
    # otherwise the two participants join different meetings and each sees an
    # empty room, which looks exactly like a WebRTC connection problem.
    try:
        c.table.update_item(
            Key=_key(token),
            UpdateExpression="SET meeting = :m",
            ConditionExpression="attribute_not_exists(meeting)",
            ExpressionAttributeValues={":m": json.dumps(meeting)},
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        _delete_meeting(meeting["MeetingId"])
        winner = (c.table.get_item(Key=_key(token)).get("Item") or {}).get("meeting")
        if not winner:
            return {"error": "could not join this visit — try again"}
        return json.loads(winner)
    return meeting


def _touch(token, role):
    """Record that `role` is still in the visit. Heartbeat, not a state machine."""
    try:
        c.table.update_item(
            Key=_key(token),
            UpdateExpression="SET #s = :now",
            # Never resurrect a visit the TTL already collected: without this a
            # stray heartbeat from a page nobody closed would recreate the item
            # as a bare stub, and join() would then hand out material for a visit
            # that had properly expired. The same condition keeps a heartbeat from
            # reporting presence on a visit that has expired but not yet been
            # collected.
            ConditionExpression=_LIVE,
            ExpressionAttributeNames={"#s": _seen_attr(role), "#ttl": "ttl"},
            ExpressionAttributeValues={":now": int(time.time())},
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise


def ping(token, role=MEMBER):
    """Heartbeat from a live client. Cheap on purpose — called every ~15s by both
    sides, and it is the only evidence either one is still there."""
    if not token or role not in ROLES:
        return {"ok": False}
    _touch(token, role)
    return {"ok": True}


def status(token):
    """Who is currently in the visit.

    This is what tells the clinician the patient is waiting, so it has to work
    *before* the clinician joins — which means it cannot be derived from the Chime
    session and has to come from the heartbeats.

    Returns booleans only. The endpoint is unauthenticated, so the reply must not
    say anything about the member beyond "somebody is on the call", and must not
    distinguish "wrong token" from "expired token".
    """
    if not token:
        return {"exists": False, "member": False, "clinician": False}
    item = c.unexpired(c.table.get_item(Key=_key(token)).get("Item"))
    if not item:
        return {"exists": False, "member": False, "clinician": False}
    cutoff = int(time.time()) - PRESENCE_TTL_SECONDS
    return {
        "exists": True,
        "started": bool(item.get("meeting")),
        MEMBER: int(item.get(_seen_attr(MEMBER)) or 0) > cutoff,
        CLINICIAN: int(item.get(_seen_attr(CLINICIAN)) or 0) > cutoff,
    }


def end(token, role=MEMBER):
    """Leave the visit, and tear the meeting down if that leaves it empty.

    Chime ends idle meetings on its own, but not immediately, and every minute a
    meeting is alive with an attendee in it is billable — so the last one out
    deletes it rather than waiting.

    The role matters. A clinician leaving ends the visit for everyone: that is
    what the "Leave and end visit" button means, and a member left alone in a
    consult has nobody to talk to. A member leaving only ends it if the clinician
    is not there — because the webview calls this from `pagehide`, which in an iOS
    webview fires when the page is backgrounded, not only when it is closed.
    Treating that as "delete the meeting" is precisely the bug that used to leave
    the two sides in different rooms.

    A visit past its ttl can still be left: the ttl keeps people out, it does not
    stop a call that is already running from being torn down (see
    VISIT_TTL_SECONDS). Presence is no longer recorded once the ttl has passed, so
    a member leaving then never ends the meeting, since "the clinician has not
    been heard from" no longer means the clinician left. The clinician leaving
    still does.
    """
    if not token:
        return {"ok": False}
    if role not in ROLES:
        return {"ok": False, "error": "unknown participant role"}

    try:
        c.table.update_item(
            Key=_key(token),
            UpdateExpression="REMOVE #s",
            # Not _LIVE: this works on a row past its ttl for as long as it exists.
            ConditionExpression="attribute_exists(pk)",
            ExpressionAttributeNames={"#s": _seen_attr(role)},
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        # No such row: never minted, or DynamoDB has deleted it. Nothing to leave,
        # and no meeting id left to delete.
        return {"ok": True, "ended": False}

    item = (c.table.get_item(Key=_key(token)).get("Item") or {})
    expired = c.unexpired(item) is None
    other = CLINICIAN if role == MEMBER else MEMBER
    cutoff = int(time.time()) - PRESENCE_TTL_SECONDS
    other_present = int(item.get(_seen_attr(other)) or 0) > cutoff

    if role == MEMBER and (other_present or expired):
        why = "visit expired, presence untracked" if expired else "clinician still present"
        print(f"VIDEO_VISIT_LEAVE token={token[:8]}… role={role} — {why}, meeting kept")
        return {"ok": True, "ended": False}

    stored = item.get("meeting")
    if stored:
        _delete_meeting(json.loads(stored).get("MeetingId", ""))
        _forget_meeting(token)
    print(f"VIDEO_VISIT_END token={token[:8]}… role={role}")
    return {"ok": True, "ended": True}


def _delete_meeting(meeting_id):
    if not meeting_id:
        return
    try:
        _client().delete_meeting(MeetingId=meeting_id)
    except ClientError as e:
        # Already gone is the expected case on a double pagehide; anything else
        # is worth a log line but not worth failing a teardown over.
        if e.response["Error"]["Code"] != "NotFoundException":
            print(f"VIDEO_VISIT_DELETE_FAILED meeting={meeting_id} {c.error_code(e)}")


def _forget_meeting(token):
    """Drop the meeting and both presences, leaving the token itself usable.

    The join budget is deliberately NOT reset: it is a spend ceiling for the
    lifetime of the token, and resetting it here would hand anyone holding the
    token an unlimited supply of meetings.
    """
    try:
        c.table.update_item(
            Key=_key(token),
            UpdateExpression="REMOVE meeting, #m, #c",
            ConditionExpression="attribute_exists(pk)",
            ExpressionAttributeNames={"#m": _seen_attr(MEMBER), "#c": _seen_attr(CLINICIAN)},
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
