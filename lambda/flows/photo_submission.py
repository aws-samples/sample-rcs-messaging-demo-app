"""Classify a Photo — native RCS inbound media, deterministic flow.

Demonstrates receiving a member-submitted photo directly inside the RCS
thread (as opposed to the compliance-forward webview upload in
insurance_upload.py), then classifying it with Bedrock. Deliberately scoped
to a GENERIC, non-sensitive example — asking for "any photo" rather than a
document that's likely to carry PII/PHI — because this path sends raw file
bytes across the public carrier/RCS network. See the dashboard's PII/PHI
guidance tooltip for why this vignette is NOT the right pattern for anything
that could contain PII (an invoice, a statement, a driver's license) or PHI
(a symptom photo, an insurance card, a medical report).

The interesting event here is the member's next MEDIA message, not a
postback — this module only sends the opening prompt. Actual media handling
lives in channel_adapter.handle_media, since a FILE-type inbound message carries
the file details (see channel_adapter.parse_inbound), not a vignette/flow marker.

Triggers: `Start: Photo_Submission`, or the `home_photo` postback.
Postback prefix: photo_
"""

import common as c


def on_start(phone, phone_hash):
    return _prompt(phone_hash)


def on_trigger(phone, phone_hash, vignette):
    return _prompt(phone_hash)


def _prompt(phone_hash):
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "Classify a Photo",
                    "Description": (
                        "Reply to this message with a photo (as an RCS message) and "
                        "we'll describe what's in it using GenAI.\n\n"
                        "Tip: this works best with a JPEG or PNG photo (not HEIC), and "
                        "please avoid anything containing personal or sensitive info — "
                        "this photo travels across the carrier/RCS network, so it's "
                        "not the right path for PII or PHI."
                    ),
                    "Media": {"FileUrl": c.resolve_media("media/photo-submission.png"), "Height": "MEDIUM"},
                },
            }
        },
        # No "Secure Upload Instead" suggestion here on purpose: this card
        # demonstrates the NATIVE RCS inbound-media path ("not for PII/PHI"),
        # and a one-tap jump to the compliance-forward webview sends the member
        # down the OTHER vignette's path (insurance_upload), which would blur the
        # lesson on the very card meant to teach native RCS. The webview remains the
        # recovery option on the media-failure card (channel_adapter.
        # _media_failure_card), where it belongs — e.g. an iPhone HEIC that the
        # native channel can't accept.
        "Suggestions": [
            {"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}},
        ],
        # SMS fallback for the vignette's entry message; inactive unless the
        # stack was deployed with -c smsFallbackNumber=+1…. See common.send_rcs.
        # Note the invitation to "send a photo" is weaker over SMS: inbound MMS
        # is a different path from inbound RCS media and this stack does not
        # ingest it, so the fallback steers to the secure upload page instead of
        # asking for something it cannot receive.
        "_fallback_body": (
            f"{c.brand_name()}: photo classification needs the rich messaging "
            "experience, which isn't available on your device right now. "
            "To send a document securely instead, use "
            f"{c.webview_url('upload-insurance-card', ph=phone_hash)}"
        ),
    }]


def on_postback(phone, phone_hash, postback_data):
    return None
