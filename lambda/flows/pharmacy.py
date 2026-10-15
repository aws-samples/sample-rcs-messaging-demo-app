"""Pharmacy Rx refill — deterministic, event-driven flow.

Also the flow that sends a `FileMessage`: the fourth RCS content type, and the
only one this project would otherwise never exercise. It sends two documents in
one exchange, by two different paths, because that pairing is the lesson:

  Magic Medicine Facts       a generic fact sheet, identical for every member.
  (media/…-facts.pdf)        Sent as a `FileMessage`, so AWS fetches it from S3,
                             rehosts it, and it crosses the RCS/carrier network.

  the member's prescription  name, address, prescriber, directions. Never sent
  record                     as a message. A `WEBVIEW` suggestion opens
  (secure-docs/…-info.pdf)   lambda/webviews/rx-patient-info.html, which fetches
                             it over HTTPS through a short-lived presigned URL.

`_pharmacy_documents` below explains the mechanics; the "why" is that a file
message is delivered *through* the carrier network with Google RCS for Business
in the chain, so the transport has to match the sensitivity of the document.

Triggers: `Start: Rx_Refill`, or dashboard push.
Postback prefix: rx_
"""

import common as c


def on_start(phone, phone_hash):
    return _refill_reminder()


def on_trigger(phone, phone_hash, vignette):
    return _refill_reminder()


def _refill_reminder():
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "Time to Refill Your Prescription",
                    "Description": (
                        "Magic Medicine 10mg — 30-day supply\n"
                        "Last filled: June 8, 2026\n"
                        "Refills remaining: 4\n\n"
                        "Your prescription is ready for refill at "
                        "Walnut St Pharmacy, Philadelphia."
                    ),
                    "Media": {"FileUrl": c.resolve_media("media/rx-refill.png"), "Height": "MEDIUM"},
                    "Suggestions": [
                        {"Reply": {"Text": "Refill Now", "PostbackData": "rx_refill_now"}},
                        {"DialPhone": {"Text": "Talk to Pharmacist", "PostbackData": "rx_call_pharm", "PhoneNumber": c.member_services_phone()}},
                    ],
                },
            }
        },
        "Suggestions": [
            {"Reply": {"Text": "Change Pharmacy", "PostbackData": "rx_change_pharmacy"}},
            {"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}},
        ],
        # SMS fallback for the vignette's entry message; inactive unless the
        # stack was deployed with -c smsFallbackNumber=+1…. See common.send_rcs.
        # Deliberately does not name the drug in the SMS beyond what the RCS
        # card already says — this is the one vignette whose fallback carries
        # health information, and an SMS has none of RCS's carrier-verified
        # sender identity to vouch for who sent it.
        "_fallback_body": (
            f"{c.brand_name()}: your prescription is ready for refill at "
            "Walnut St Pharmacy, Philadelphia. "
            f"To refill or speak to a pharmacist, call {c.member_services_phone()}."
        ),
    }]


def _refill_confirmed():
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "Refill Confirmed",
                    "Description": (
                        "Magic Medicine 10mg — 30-day supply\n\n"
                        "Ready for pickup:\n"
                        "Tomorrow after 10:00 AM\n"
                        "Walnut St Pharmacy\n\n"
                        f"Copay: $10.00 ({c.brand_name()} PPO)"
                    ),
                    "Suggestions": [
                        {"OpenUrl": {
                            "Text": "View Rx Details", "PostbackData": "rx_details_wv",
                            "Url": c.webview_url("rx-details"),
                            "Application": "WEBVIEW", "WebviewViewMode": "HALF",
                        }},
                        {"ShowLocation": {
                            "Text": "Get Directions", "PostbackData": "rx_directions",
                            "Latitude": 39.9526, "Longitude": -75.1652, "Label": "Walnut St Pharmacy",
                        }},
                        {"CreateCalendarEvent": {
                            "Text": "Remind Me", "PostbackData": "rx_remind",
                            "Title": "Pick up Magic Medicine", "Description": "Walnut St Pharmacy, Philadelphia",
                            "StartTime": 1752066000, "EndTime": 1752069600,
                        }},
                        # Answers with both documents (see _pharmacy_documents),
                        # so the label is not "Medication Guide" any more. This
                        # card is at the 4-suggestion maximum, which is why the
                        # secure-record chip rides on that reply's own message
                        # rather than being added here.
                        {"Reply": {"Text": "Rx Documents", "PostbackData": "rx_leaflet"}},
                    ],
                },
            }
        },
        "Suggestions": [{"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}}],
    }]


def _pharmacy_documents(phone_hash):
    """Both document paths in one exchange: a PDF as a `FileMessage`, and a
    `WEBVIEW` chip to a document that must not be one.

    Worth knowing about the file-message content type:

    * `FileMessage` is not just for images. Image, video, audio and PDF all
      travel the same way, and a PDF is the one that has no rich-card
      equivalent — a card can show a picture, but only a file message can hand
      the member a document they keep.
    * The file is referenced by `s3://` URI, not uploaded in the request. AWS
      downloads it from your bucket, rehosts it, and presigns it for the
      aggregator, so the bucket needs no public access — see the bucket policy
      in cdk/lib/anyhealth-stack.ts.
    * A file message carries no title, description or caption. Anything the
      member needs to read has to be a separate message, which is why the text
      below is sent first.
    * `Content` is a tagged union: this message can hold the file *or* a card,
      never both. Message-level `Suggestions` still apply, though, so the chips
      below ride along with the file.

    And the consequence of that second bullet, which is the reason this function
    sends what it sends: **that rehosting step is the compliance boundary.** The
    bytes leave your account, travel the RCS/carrier network, and Google RCS for
    Business is in the delivery chain, under its own terms of service. So the
    file message here is the fact sheet — the same document for every member,
    with no name, address, prescriber or directions in it, so nothing about an
    individual crosses that boundary.

    The member's own prescription record goes the other way. The `OpenUrl`
    suggestion opens lambda/webviews/rx-patient-info.html inside the
    conversation; that page calls `GET /api/secure-doc`, which presigns
    `secure-docs/rx-patient-info.pdf` for 300 seconds, and the browser fetches it
    from S3 over HTTPS. Nothing about the member enters the message stream. The
    bucket policy and the channel adapter's role (the access log of a test
    deployment's bucket shows its session behind each accepted media send) are
    meant to make that structural rather than a matter of discipline: the EUM
    service principal has `s3:GetObject` on `media/*` and the inbound prefixes
    only, and the role has it on `media/`, `inbound/rcs/` and `converted-inbound/`
    only. On a test deployment a `FileMessage` naming the `secure-docs/` key was
    refused with a `ValidationException` (`RESOURCE_NOT_ACCESSIBLE`), as was one
    naming a member photo under `converted-uploads/`, while one naming
    `media/rx-medication-facts.pdf` succeeded. The channel adapter's
    `s3:GetObject` grant is what lets the service read the object for a send: a
    temporary Deny on the role made an image card and a PDF send fail with
    `RESOURCE_NOT_ACCESSIBLE`, and sends worked again once it was removed.

    Transport is one control, not the whole of compliance — the webview in this
    demo is unauthenticated, and `common.hash_phone` is unsalted. See
    `dashboard_handler.get_secure_doc` for what a real deployment still owes.

    https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-file-messages.html
    """
    return [
        {
            "Content": {"TextMessage": {"Body": (
                "Two things for you. The Magic Medicine fact sheet is attached "
                "below — it's the same general information we send everyone. "
                "Your own prescription record has your details on it, so tap "
                "\"My Rx Record\" to view it securely instead.\n\n"
                "Sample documents — fictitious content for this demo."
            )}},
        },
        {
            "Content": {"FileMessage": {
                "FileUrl": c.resolve_media("media/rx-medication-facts.pdf"),
                # Optional. Without it the messaging app shows whatever generic
                # file icon it prefers; with it, the member sees a preview
                # before deciding to open a document.
                "ThumbnailUrl": c.resolve_media("media/rx-refill.png"),
            }},
            # Message-level, not card-level: a file message has no card to hang
            # chips on. The cap here is 11, not the 4 a card allows.
            "Suggestions": [
                {"OpenUrl": {
                    "Text": "My Rx Record", "PostbackData": "rx_patient_info_wv",
                    # ph scopes the document to this conversation; the webview
                    # reads it from the query string.
                    "Url": c.webview_url("rx-patient-info", ph=phone_hash),
                    # FULL rather than HALF: this one is a document to read, not
                    # a detail panel to glance at.
                    "Application": "WEBVIEW", "WebviewViewMode": "FULL",
                }},
                {"DialPhone": {
                    "Text": "Talk to Pharmacist", "PostbackData": "rx_call_pharm",
                    "PhoneNumber": c.member_services_phone(),
                }},
                {"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}},
            ],
        },
    ]


def _change_pharmacy():
    return [{
        "Content": {"TextMessage": {"Body": f"Here are {c.brand_name()} in-network pharmacies near you:"}},
        "Suggestions": [
            {"Reply": {"Text": "Broad St Pharmacy", "PostbackData": "rx_pharm_broad"}},
            {"Reply": {"Text": "Chestnut Pharmacy", "PostbackData": "rx_pharm_chestnut"}},
            {"Reply": {"Text": "Market St Pharmacy", "PostbackData": "rx_pharm_market"}},
            {"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}},
        ],
    }]


def _pharmacy_updated(name):
    return [{
        "Content": {"TextMessage": {"Body": f"Pharmacy updated to {name}. Your next refill will be sent there. We'll notify you when it's ready."}},
        "Suggestions": [
            {"Reply": {"Text": "Refill Now", "PostbackData": "rx_refill_now"}},
            {"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}},
        ],
    }]


_PHARM = {
    "rx_pharm_broad": "Broad St Pharmacy — 234 Broad St",
    "rx_pharm_chestnut": "Chestnut Pharmacy — 567 Chestnut St",
    "rx_pharm_market": "Market St Pharmacy — 1200 Market St",
}


def on_postback(phone, phone_hash, postback_data):
    if postback_data == "rx_refill_now":
        return _refill_confirmed()
    if postback_data == "rx_leaflet":
        return _pharmacy_documents(phone_hash)
    if postback_data == "rx_change_pharmacy":
        return _change_pharmacy()
    if postback_data in _PHARM:
        return _pharmacy_updated(_PHARM[postback_data])
    return None
