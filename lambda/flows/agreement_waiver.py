"""Agreement/Waiver -- signable-document webview, deterministic flow (AnyBuild).

The same read-and-sign pattern as AnyWealth's Loan Agreement
(flows/loan_agreement.py), with a generic agreement and waiver in place of the
loan: the business sends a document OUT to be read, initialed and signed. The
document is a self-contained HTML page (lambda/webviews/agreement-waiver.html)
opened in an in-app WEBVIEW -- a sample 3-page agreement and waiver (parties,
scope, assumption of risk, waiver and release, responsibilities, term) with
per-page initials and a drawn signature. On submit it shows a signing receipt
(timestamp, reference id, masked token, SHA-256 document fingerprint). Nothing
is sent or stored; the page makes no network calls of its own.

The document and the signature stay in the webview, so only the link rides the
RCS channel. As with the other webviews in this demo, the page is NOT
authenticated: the `token` below is a demo-level gate (the page only checks it
is long enough), not a real signed URL or session. See flows/loan_agreement.py
for the full caveat, which applies unchanged.

The waiver text is generic sample wording, not a reviewed legal document. A real
waiver needs counsel's wording for the jurisdiction, and a real signer brings
electronic-signature requirements (in the US, the ESIGN Act and UETA) that this
demo does not implement.

Triggers: `Start: Agreement_Waiver`, or the `home_agreement` postback.
Postback prefix: waiver_ (unused -- the work happens in the webview).
"""

import common as c


def on_start(phone, phone_hash):
    return _agreement_card(phone_hash)


def on_trigger(phone, phone_hash, vignette):
    return _agreement_card(phone_hash)


def _waiver_url(phone_hash):
    # The page requires a token of at least 8 characters (demo gate only); the
    # conversation phone_hash is long enough, and the "waiver-" prefix keeps it
    # so if a hash were ever shortened. name= personalizes "Prepared for" and
    # "Signed by"; tester_name falls back to the brand's sample member.
    token = f"waiver-{phone_hash}" if phone_hash else "waiver-demo-token"
    return c.webview_url(
        "agreement-waiver",
        token=token,
        name=c.tester_name(phone_hash, c.member_name()),
    )


def _agreement_card(phone_hash):
    url = _waiver_url(phone_hash)
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "Agreement and Waiver - Signature Required",
                    "Description": (
                        "Your agreement and waiver is ready to review and sign. Open it "
                        "to read all three pages, initial each one, and add your "
                        "signature.\n\n"
                        "The document opens in a secure page -- it is never sent "
                        "through this text conversation."
                    ),
                    "Media": {"FileUrl": c.resolve_media("media/insurance-upload.png"), "Height": "MEDIUM"},
                    "Suggestions": [
                        {"OpenUrl": {
                            "Text": "Review & Sign", "PostbackData": "waiver_open",
                            "Url": url,
                            "Application": "WEBVIEW", "WebviewViewMode": "TALL",
                        }},
                    ],
                },
            }
        },
        # SMS fallback for the entry message; inactive unless deployed with
        # -c smsFallbackNumber=+1... (see common.send_rcs). The link is the whole
        # point of this vignette and survives as SMS.
        "_fallback_body": (
            f"{c.brand_name()}: your agreement and waiver is ready to review and sign "
            f"on our secure page. {url}"
        ),
    }]


def preview_message():
    """Dashboard-only phone preview. Same shape as a real send; no side effects."""
    return _agreement_card("")


def on_postback(phone, phone_hash, postback_data):
    return None
