"""Camera / microphone probe — DIAGNOSTIC, not a member-facing vignette.

Exists to answer one question: can a page opened from an RCS OpenUrl suggestion
reach `getUserMedia`? That decides whether a WebRTC video call (Amazon Chime SDK
for JavaScript) can run *inside* the conversation, or whether it has to leave
for the device browser.

The Amazon Chime SDK for JavaScript system requirements list iOS WKWebView 14.3+
and Android Chromium WebView 5+ for audio and video (no content sharing).
Whether the messaging app hosting the RCS webview grants media permissions is up
to that app, so the probe checks it on the handset. RcsOpenUrlAction takes
`Application` (WEBVIEW | BROWSER) and `WebviewViewMode`; camera and microphone
access belongs to the messaging app.

So this sends the *same* URL three ways:

  • WEBVIEW / FULL   — the mode a video call would realistically want
  • WEBVIEW / HALF   — to see whether view mode changes permission behaviour
  • BROWSER          — the control. A full browser with normal permission UI.

If BROWSER grants and the WEBVIEW chips do not, the messaging app's webview is
the blocker — not the page, the network, the TLS certificate, or the device.
That is the whole point of sending all three in one message: it removes every
explanation except the one being tested.

Triggers: `Start: Media_Probe`, or dashboard push.
Postback prefix: probe_
"""

import common as c

# One page, opened three ways. Kept as a module constant so there is visibly no
# chance of the three chips differing in anything but `Application`/view mode.
_PROBE_PAGE = "media-probe"


def on_start(phone, phone_hash):
    return _probe_card()


def on_trigger(phone, phone_hash, vignette):
    return _probe_card()


def _probe_card():
    url = c.webview_url(_PROBE_PAGE)
    return [{
        "Content": {
            "TextMessage": {
                "Body": (
                    "Camera & mic probe. Tap each chip in turn and note what the "
                    "page reports.\n\n"
                    "Full and Half open inside this conversation; Browser opens "
                    "your default browser and is the control. Approve the "
                    "permission prompt if one appears — and note if none does."
                )
            }
        },
        # Message-level suggestions allow up to 11, so all three fit without a
        # card. Chips are deliberately message-level and transient: this is a
        # one-shot diagnostic, not something to leave sitting in the thread.
        "Suggestions": [
            {"OpenUrl": {
                "Text": "Webview (Full)", "PostbackData": "probe_webview_full",
                "Url": url, "Application": "WEBVIEW", "WebviewViewMode": "FULL",
            }},
            {"OpenUrl": {
                "Text": "Webview (Half)", "PostbackData": "probe_webview_half",
                "Url": url, "Application": "WEBVIEW", "WebviewViewMode": "HALF",
            }},
            {"OpenUrl": {
                # No Application field at all, which is the documented default:
                # "By default the URL opens in the device browser." Written as an
                # omission rather than Application="BROWSER" so this chip also
                # tests what a caller gets when they say nothing.
                "Text": "Browser (control)", "PostbackData": "probe_browser",
                "Url": url,
            }},
            {"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}},
        ],
    }]


def preview_message():
    """Dashboard-only phone preview. Same shape as a real send; no side effects."""
    return _probe_card()


# Which chip was tapped, echoed back so the transcript records the mode the
# tester was in when the page reported its result. The webview report itself
# (WEBVIEW_PROBE_REPORT in the dashboard log group) has no idea which chip
# opened it — same URL three ways — so this is the only place the two halves of
# the experiment can be joined.
_CHIP_LABELS = {
    "probe_webview_full": "webview, FULL view mode",
    "probe_webview_half": "webview, HALF view mode",
    "probe_browser": "device browser (control)",
}


def on_postback(phone, phone_hash, postback_data):
    label = _CHIP_LABELS.get(postback_data)
    if not label:
        return None
    # Reply with something, rather than returning None. A None here falls through
    # the channel adapter's postback-prefix loop and ends at the Bedrock
    # assistant, which would answer a diagnostic tap with a care-advocate
    # pleasantry — a model call we do not want, and a message arriving on top of
    # the webview just as it opens. One short line is the quieter outcome, and it
    # timestamps the tap in the transcript.
    return [{
        "Content": {"TextMessage": {"Body": f"Probe opened: {label}."}}}]
