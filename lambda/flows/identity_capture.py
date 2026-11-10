"""Identity Capture — ID photo via a secure webview upload, deterministic (AnyBuild).

At onboarding a builder or a supplier may need to show identification: a
driver's license, or a passport for someone outside the US. This is the
compliance-forward counterpart to Site Evidence. Instead of sending the photo
through the RCS thread, the person taps a chip that opens an in-app browser
(lambda/webviews/id-capture.html). The image goes from that page straight to
private S3 over a presigned URL, so it never crosses the carrier network, and
only the link rides the RCS channel.

The card asks which ID the person will use (construction.md `idQuestion`): a
passport, front only, or a USA driver's license, front and back. Each answer is
a chip that opens the page for that ID type, and the page photographs one side
or two in order. Once an image is converted and described by media_convert.py,
the page shows what the document is. It deliberately shows no preview of the
image: a captured ID is not left on screen. Each upload is filed with the use
case, the ID type, the side and the page visit, so the dashboard's Identity
Capture card can show the operator the one or two sides captured in the latest
visit (dashboard_handler.get_latest_media_for_demo).

What this demo does NOT do: verify the document. Nothing checks that the ID is
real, unexpired or matches the person. A real onboarding flow would send the
image to an identity-verification service and keep the result, not the image.

The webview is NOT authenticated in this demo, the same as Secure Document
Upload (see flows/insurance_upload.py for the full caveat). Do not upload a real
ID to it.

Triggers: `Start: Identity_Capture`, or the `home_idcap` postback.
Postback prefix: idcap_ (the chips are native actions; the work is in the webview)
"""

import common as c

# One chip per document in content/construction.md `idDocuments`. Each chip's
# PostbackData is written out as a literal below (not looked up) because a tap on
# an action chip must be recognized as "the handset already did the work"
# (channel_adapter.ACTION_ONLY_POSTBACKS), and scripts/check-rcs-registry.py
# keeps that list in step with the literals it finds in the flows.
_DOC_IDS = ("license", "passport")


def on_start(phone, phone_hash):
    return _prompt(phone_hash)


def on_trigger(phone, phone_hash, vignette):
    return _prompt(phone_hash)


def preview_message():
    return _prompt("")


def _url(doc, phone_hash):
    steps = doc.get("steps", [])
    return c.webview_url(
        "id-capture", ph=phone_hash, type=doc["id"], doc=doc.get("name", ""),
        steps="|".join(s["label"] for s in steps),
        sides="|".join(s["side"] for s in steps),
    )


def _chips(docs, phone_hash):
    chips = []
    for d in docs:
        text = d.get("chip", d.get("name", ""))[:25]
        if d["id"] == "license":
            chips.append({"OpenUrl": {
                "Text": text, "PostbackData": "idcap_open_license", "Url": _url(d, phone_hash),
                "Application": "WEBVIEW", "WebviewViewMode": "TALL",
            }})
        elif d["id"] == "passport":
            chips.append({"OpenUrl": {
                "Text": text, "PostbackData": "idcap_open_passport", "Url": _url(d, phone_hash),
                "Application": "WEBVIEW", "WebviewViewMode": "TALL",
            }})
    return chips


def _prompt(phone_hash):
    docs = [d for d in c.id_documents() if d["id"] in _DOC_IDS]
    if not docs:
        return [{"Content": {"TextMessage": {"Body": (
            "No identity documents are set up yet. Add `idDocuments` in content/construction.md."
        )}}}]
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "Verify Your Identity",
                    "Description": (
                        f"{c.builder_name()} needs to see identification to finish setting you "
                        f"up.\n\n{c.id_question()}\n\n"
                        "The photos are uploaded on a secure page and never travel through "
                        "this conversation.\n\n"
                        "Demo only: use a sample image, not a real ID."
                    ),
                    "Media": {"FileUrl": c.resolve_media("media/anybuild/identity.png"), "Height": "MEDIUM"},
                    "Suggestions": _chips(docs, phone_hash),
                },
            }
        },
        # SMS fallback for the entry message; inactive unless deployed with
        # -c smsFallbackNumber=+1… (see common.send_rcs). The links are the
        # point of this vignette and survive as SMS: one per ID type, since a
        # text message has no chips to answer the question with.
        "_fallback_body": (
            f"{c.brand_name()}: to finish setup, photograph your ID on our secure page. "
            "It never travels through this text conversation. "
            + " ".join(f"{d.get('chip', d.get('name', ''))}: {_url(d, phone_hash)}" for d in docs)
        ),
    }]


def on_postback(phone, phone_hash, postback_data):
    return None
