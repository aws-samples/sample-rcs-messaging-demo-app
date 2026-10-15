"""IVS Interactive Fitness webview experiment -- EXPERIMENTAL, not member-facing.

Second of the Amazon IVS webview probes (see ivs_experiment.py for the iCasino
one). Target is the hosted "Amazon IVS Live Fitness demo" at
https://fitness.ivsdemos.com/ -- a live interactive fitness
stream with a leaderboard and basic user interactions
(github.com/aws-samples/amazon-ivs-fitness-web-demo, hosted on ivs.rocks).

Same shape and reasoning as the iCasino probe:
  * RCS cards cannot embed a live page, so we use an OpenUrl suggestion with
    Application=WEBVIEW, which opens the URL in a modal browser on top of the
    conversation. OpenUrl.Url is the absolute external https URL, not a
    c.webview_url() (that helper is only for pages this API serves itself).
  * The URL opens as a TOP-LEVEL document, so any framing restriction on the
    site is irrelevant (this one sends no X-Frame-Options at all).
  * Sent as a Full webview plus a device-browser control, so the two results
    can be compared.

Where iCasino uses real-time betting/gaming video, this adds the low-latency
fitness interactivity (leaderboard, user interactions) -- a different IVS
surface to try in an RCS webview.

Triggers: `Start: IVS_Fitness`, or dashboard push (Settings tab).
Postback prefix: fit_
"""

import common as c

# The external hosted demo. Absolute https URL on purpose -- see the module
# docstring; not one of our own webview pages.
_IVS_FITNESS_URL = "https://fitness.ivsdemos.com/"


def on_start(phone, phone_hash):
    return _experiment_card()


def on_trigger(phone, phone_hash, vignette):
    return _experiment_card()


def _experiment_card():
    return [{
        "Content": {
            "TextMessage": {
                "Body": (
                    "Experiment: open a live Amazon IVS interactive fitness "
                    "stream in an RCS webview.\n\n"
                    "Tap each chip and note whether the fitness stream and its "
                    "leaderboard actually work. Webview opens inside this "
                    "conversation; Browser opens your default browser and is the "
                    "control. Approve any permission or autoplay prompt -- and "
                    "note if none appears."
                )
            }
        },
        # FULL webview + a device browser control + Main Menu. (HALF view mode
        # was dropped: the half panel is too small for a live video app.)
        "Suggestions": [
            {"OpenUrl": {
                "Text": "Webview (Full)", "PostbackData": "fit_webview_full",
                "Url": _IVS_FITNESS_URL, "Application": "WEBVIEW", "WebviewViewMode": "FULL",
            }},
            {"OpenUrl": {
                # No Application field: the documented default is the device
                # browser. Written as an omission so this chip also tests what a
                # caller gets when they specify nothing.
                "Text": "Browser (control)", "PostbackData": "fit_browser",
                "Url": _IVS_FITNESS_URL,
            }},
            {"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}},
        ],
    }]


def preview_message():
    """Dashboard-only phone preview. Same shape as a real send; no side effects."""
    return _experiment_card()


_CHIP_LABELS = {
    "fit_webview_full": "webview, FULL view mode",
    "fit_browser": "device browser (control)",
}


def on_postback(phone, phone_hash, postback_data):
    label = _CHIP_LABELS.get(postback_data)
    if not label:
        return None
    return [{
        "Content": {"TextMessage": {"Body": f"IVS fitness experiment opened: {label}."}}}]
