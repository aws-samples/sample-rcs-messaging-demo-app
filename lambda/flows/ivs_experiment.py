"""IVS iCasino webview experiment -- EXPERIMENTAL, not a member-facing vignette.

An off-theme probe that opens the public Amazon IVS iCasino Web demo in an RCS
in-conversation webview. The page is at https://icasino.ivsdemos.com/, which
loads amazon-ivs-web-broadcast.js and renders a live interactive stream from
Amazon IVS (Interactive Video Service).

Two things make this the right shape:

  1. RCS cards cannot embed a live page -- card Media is a static image/video
     only. The nearest thing is an OpenUrl suggestion with Application=WEBVIEW,
     which opens the URL in a modal browser ON TOP of the conversation.

  2. The site sends `x-frame-options: SAMEORIGIN`, so it refuses to be framed by
     any other origin. That rules out iframing it inside one of our own webview
     pages -- but a WEBVIEW OpenUrl opens it as a TOP-LEVEL document, not an
     iframe, so the header does not apply. We therefore point OpenUrl.Url
     straight at the external https URL rather than at c.webview_url(...), which
     is only for pages this API serves itself.

Like media_probe, it sends the same URL as a FULL webview plus a device-browser
control, so the two results can be compared. The result on each handset shows
whether the messaging app's webview plays the stream.

Triggers: `Start: IVS_Experiment`, or dashboard push (Settings tab).
Postback prefix: ivs_
"""

import common as c

# The external live-video demo. An absolute https URL on purpose -- see the
# module docstring: this is NOT one of our own webview pages, so it does not go
# through c.webview_url().
_IVS_URL = "https://icasino.ivsdemos.com/"


def on_start(phone, phone_hash):
    return _experiment_card()


def on_trigger(phone, phone_hash, vignette):
    return _experiment_card()


def _experiment_card():
    return [{
        "Content": {
            "TextMessage": {
                "Body": (
                    "Experiment: open a live Amazon IVS video stream in an RCS "
                    "webview.\n\n"
                    "Tap each chip and note whether the iCasino stream actually "
                    "plays. Webview opens inside this conversation; Browser opens "
                    "your default browser and is the control. Approve any "
                    "permission or autoplay prompt -- and note if none appears."
                )
            }
        },
        # Message-level suggestions allow up to 11. FULL webview + a device
        # browser control + Main Menu. (HALF view mode was dropped: the half
        # panel is too small for a live video app to be usable.) Transient by
        # design: a one-shot experiment, not something to leave in the thread.
        "Suggestions": [
            {"OpenUrl": {
                "Text": "Webview (Full)", "PostbackData": "ivs_webview_full",
                "Url": _IVS_URL, "Application": "WEBVIEW", "WebviewViewMode": "FULL",
            }},
            {"OpenUrl": {
                # No Application field: the documented default is the device
                # browser. Written as an omission so this chip also tests what a
                # caller gets when they specify nothing.
                "Text": "Browser (control)", "PostbackData": "ivs_browser",
                "Url": _IVS_URL,
            }},
            {"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}},
        ],
    }]


def preview_message():
    """Dashboard-only phone preview. Same shape as a real send; no side effects."""
    return _experiment_card()


_CHIP_LABELS = {
    "ivs_webview_full": "webview, FULL view mode",
    "ivs_browser": "device browser (control)",
}


def on_postback(phone, phone_hash, postback_data):
    label = _CHIP_LABELS.get(postback_data)
    if not label:
        return None
    # Reply with a short line rather than returning None, which would fall
    # through the adapter's postback-prefix loop to the Bedrock assistant and
    # answer an experiment tap with a care-advocate pleasantry -- a model call we
    # do not want, and a message landing on top of the webview as it opens.
    return [{
        "Content": {"TextMessage": {"Body": f"IVS experiment opened: {label}."}}}]
