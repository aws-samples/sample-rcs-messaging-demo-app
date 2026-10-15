"""Video visit — EXPERIMENTAL. WebRTC (Amazon Chime SDK JS) inside an RCS webview.

The clinician's office sends a card; the member taps a chip and is in a video
call with them, without installing an app and without leaving the conversation.
That last clause is the part under test: `Application` (WEBVIEW | BROWSER) and
`WebviewViewMode` on RcsOpenUrlAction choose where the link opens; the camera
and microphone grant belongs to the messaging app.

So the card carries both chips deliberately:

  • Join video visit  — WEBVIEW / FULL, the in-conversation experience
  • Open in browser   — no Application field (the documented default, the device
                        browser), where permission prompts certainly work

If the webview chip cannot get a camera, the browser chip still completes the
call, which is also the shape a production design would ship: try to stay in the
conversation, fall out to the browser when the handset will not cooperate.

A visit token is minted per send (see lambda/video_visit.py) and the Chime
meeting is created lazily on first join, so an invitation nobody opens costs
nothing. The token expires in 30 minutes.

Triggers: `Start: Video_Visit`, or dashboard push.
Postback prefix: visit_
"""

import common as c
import video_visit as vv

# Same provider as the appointment vignette, which also names her inline rather
# than through a brand accessor — a video visit is the same clinician the member
# already has an appointment card from.
PROVIDER = "Dr. Rachel Torres"


def on_start(phone, phone_hash):
    return _invite(phone_hash)


def on_trigger(phone, phone_hash, vignette):
    return _invite(phone_hash)


def _invite(phone_hash):
    token = vv.create_visit(phone_hash=phone_hash, label="Video visit")
    # Log only a truncated token prefix for correlation, never the full token or
    # visit URL: the token is a 122-bit secret that grants join access to a
    # billed Chime meeting for 30 minutes, and anyone with CloudWatch read access
    # could otherwise lift a live one from the logs.
    print(f"VIDEO_VISIT_INVITE phone_hash={phone_hash} token={token[:8]}…")
    return invite(token)


def invite(token):
    """The invitation card for an already-minted visit token.

    Split out from _invite so the dashboard can mint the token itself, send this
    card, and join the same meeting from the operator console — the clinician
    side of the call. See dashboard_handler.start_video_visit.
    """
    url = vv.visit_url(token)
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "Your video visit is ready",
                    "Description": (
                        f"{PROVIDER} is ready to see you now.\n\n"
                        "Tap to join. You'll be asked for camera and microphone "
                        "access — the visit is between you and your care team."
                    ),
                    "Suggestions": [
                        {"OpenUrl": {
                            "Text": "Join video visit", "PostbackData": "visit_join_webview",
                            "Url": url,
                            # FULL, not HALF or TALL: a video call wants the whole
                            # screen, and a half-height sheet would put the remote
                            # participant in a letterbox.
                            "Application": "WEBVIEW", "WebviewViewMode": "FULL",
                        }},
                        {"OpenUrl": {
                            # No Application field: "By default the URL opens in
                            # the device browser." The escape hatch, and the
                            # control for whether the webview is what blocked us.
                            "Text": "Open in browser", "PostbackData": "visit_join_browser",
                            "Url": url,
                        }},
                    ],
                },
            }
        },
        "Suggestions": [{"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}}],
        # No _fallback_body. An SMS cannot carry the join link usefully here: the
        # link is single-visit and expiring, and a bare URL in a text message for
        # a video consult is exactly the shape of a phishing lure. If RCS cannot
        # reach the member, the right recovery is a phone call from the clinic,
        # not a text with a link in it.
    }]


def preview_message():
    """Dashboard-only phone preview. Must have no side effects — it can fire on
    every card open — so it does NOT mint a visit token or write to DynamoDB;
    the chip URL is a placeholder."""
    url = c.webview_url("video-visit", visit="preview")
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "Your video visit is ready",
                    "Description": (
                        f"{PROVIDER} is ready to see you now.\n\n"
                        "Tap to join. You'll be asked for camera and microphone "
                        "access — the visit is between you and your care team."
                    ),
                    "Suggestions": [
                        {"OpenUrl": {
                            "Text": "Join video visit", "PostbackData": "visit_join_webview",
                            "Url": url, "Application": "WEBVIEW", "WebviewViewMode": "FULL",
                        }},
                        {"OpenUrl": {
                            "Text": "Open in browser", "PostbackData": "visit_join_browser",
                            "Url": url,
                        }},
                    ],
                },
            }
        },
        "Suggestions": [{"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}}],
    }]


_CHIP_LABELS = {
    "visit_join_webview": "in-conversation webview",
    "visit_join_browser": "device browser",
}


def on_postback(phone, phone_hash, postback_data):
    label = _CHIP_LABELS.get(postback_data)
    if not label:
        return None
    # Reply with one line rather than returning None: a None falls through the
    # channel adapter's prefix loop to the Bedrock assistant, which would answer
    # a join tap with small talk — a model call we do not want, arriving on top
    # of the webview as it opens. This also timestamps which chip was used, which
    # the webview's own logs cannot know (both chips open the same URL).
    return [{"Content": {"TextMessage": {"Body": f"Joining via {label}…"}}}]
