"""Secure Document Upload — webview upload, deterministic flow.

The compliance-forward counterpart to photo_submission.py: instead of
sending a photo natively through the RCS/carrier network, the member taps a
webview link that opens an in-app browser. The file bytes are PUT directly
from that browser to S3 via a presigned URL — they never transit any AWS API
server, any message body, or the carrier network at all. Only the link (a
normal RCS suggestion) rides the RCS channel.

That transport property keeps sensitive bytes off the carrier path, which is
the first thing to get right for content like an insurance card or an ID. It
is only one control — see the dashboard's PII guidance tooltip for the
explanation shown to demo viewers, and SECURITY.md for what a real
deployment still needs.

**The webview itself is NOT authenticated in this demo.** `/webview/*` and the
presign endpoint it calls are deliberately open (docs/architecture.md section 3),
because the in-app browser has no way to hold the operator's API key. The link
carries only a truncated phone hash (`common.hash_phone`, an unsalted SHA-256 of
the phone number, so anyone who knows the number can compute it), and the page
URL never expires: anyone holding it can upload against that hash. Only the
presigned S3 PUT URL the page requests is time-limited (600 s, and reusable
within that window). Before handling real PHI you must add a
member-authenticated session here — an identity provider, or at minimum a
single-use signed token bound to the conversation with a short expiry. Do not
read the "secure" in this vignette's name as meaning authenticated; it means
the bytes bypass the carrier network.

The uploaded file (including HEIC from an iPhone) is converted to a
displayable JPEG by lambda/media_convert.py, triggered by an S3 event on the
upload — see that module's docstring.

Triggers: `Start: Insurance_Upload`, or the `home_upload` postback.
Postback prefix: upload_ (mostly unused — the interesting work happens in
the webview + media_convert.py, not via postback).
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
                    "Title": "Secure Document Upload",
                    "Description": (
                        "Try the upload with a sample image, such as a sample insurance "
                        "card. This is a demo, so please don't upload real documents. "
                        "The file goes through an encrypted upload page — it never "
                        "travels through this text conversation.\n\n"
                        "Works with any photo format, including iPhone HEIC."
                    ),
                    "Media": {"FileUrl": c.resolve_media("media/insurance-upload.png"), "Height": "MEDIUM"},
                    "Suggestions": [
                        {"OpenUrl": {
                            "Text": "Upload Securely", "PostbackData": "upload_open",
                            "Url": c.webview_url("upload-insurance-card", ph=phone_hash),
                            "Application": "WEBVIEW", "WebviewViewMode": "TALL",
                        }},
                    ],
                },
            }
        },
        "Suggestions": [{"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}}],
        # SMS fallback for the vignette's entry message; inactive unless the
        # stack was deployed with -c smsFallbackNumber=+1…. See common.send_rcs.
        # The webview URL is the whole point of this vignette and it survives as
        # SMS perfectly well, so the fallback loses very little here — unlike the
        # card-and-chips vignettes.
        "_fallback_body": (
            f"{c.brand_name()} demo: try the upload with a sample image, such as a "
            "sample insurance card. Please don't upload real documents. The file goes "
            "through our encrypted upload page and never travels through this text "
            "conversation. "
            f"{c.webview_url('upload-insurance-card', ph=phone_hash)}"
        ),
    }]


def on_postback(phone, phone_hash, postback_data):
    return None
