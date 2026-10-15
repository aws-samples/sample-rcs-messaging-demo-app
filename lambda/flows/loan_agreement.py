"""Loan Agreement -- signable-document webview, deterministic flow.

A finance counterpart to the Secure Document Upload vignette: instead of the
member sending a document IN, the business sends a document OUT to be read and
signed. The agreement is a self-contained HTML page
(lambda/webviews/loan-agreement.html) opened in an in-app WEBVIEW -- a fake
3-page installment-loan agreement with per-page initials and a drawn signature.
On submit it shows a signing receipt (timestamp, reference id, masked token,
SHA-256 document fingerprint). Nothing is sent or stored; the page makes no
network calls of its own.

Why a webview rather than a FileMessage: a signable document is interactive
(you initial and sign it), and -- like the insurance upload -- keeping it in a
webview means the document and the signature never transit the RCS/carrier
network. The RCS channel carries only the link. That is the right transport for
anything containing personal or financial detail. As with the other webviews in
this demo, the page is NOT authenticated: the `token` below is a demo-level
gate (the page only checks it is long enough), not a real signed-URL or session.
A production signer must validate the token server/edge side and bind it to the
recipient -- see docs/architecture.md and the page's own header comments.

Compliance: the agreement is fictional and nothing is stored, but a real loan
signer handles consumer financial information. Depending on where you operate
that brings financial-privacy and safeguards rules (in the US, GLBA), electronic
signature requirements (in the US, the ESIGN Act and UETA), and PCI DSS if payment
card data is ever collected. This demo implements none of them; treat the pattern
as a transport example and have your compliance team review a real deployment.

The page reads three query params: `token` (required, >= 8 chars), `name`
(personalizes "Prepared for"/"Signed by"), and `initials` (draw|stamp|type --
left at the page default here).

Triggers: `Start: Loan_Agreement`, or dashboard push.
Postback prefix: loan_ (unused -- the work happens in the webview).
"""

import common as c


def on_start(phone, phone_hash):
    return _agreement_card(phone_hash)


def on_trigger(phone, phone_hash, vignette):
    return _agreement_card(phone_hash)


def _loan_url(phone_hash):
    # The page requires a token of at least 8 characters (demo gate only). The
    # conversation phone_hash is a hash, so it is long enough and is the same
    # per-recipient identifier the other webviews use. A "loan-" prefix
    # guarantees the >= 8 length even if a hash were ever shortened. name=
    # personalizes the document; tester_name falls back to the brand's sample
    # member when the recipient has no name set on the Recipients tab.
    token = f"loan-{phone_hash}" if phone_hash else "loan-demo-token"
    return c.webview_url(
        "loan-agreement",
        token=token,
        name=c.tester_name(phone_hash, c.member_name()),
    )


def _agreement_card(phone_hash):
    url = _loan_url(phone_hash)
    return [{
        "Content": {
            "RichCard": {
                "CardOrientation": "VERTICAL",
                "CardContent": {
                    "Title": "Loan Agreement - Signature Required",
                    "Description": (
                        "Your personal installment loan agreement is ready to review "
                        "and sign. Open it to read all three pages, initial each one, "
                        "and add your signature.\n\n"
                        "The document opens in a secure page -- it is never sent "
                        "through this text conversation."
                    ),
                    "Media": {"FileUrl": c.resolve_media("media/insurance-upload.png"), "Height": "MEDIUM"},
                    "Suggestions": [
                        {"OpenUrl": {
                            "Text": "Review & Sign", "PostbackData": "loan_open",
                            "Url": url,
                            "Application": "WEBVIEW", "WebviewViewMode": "TALL",
                        }},
                    ],
                },
            }
        },
        "Suggestions": [{"Reply": {"Text": "Main Menu", "PostbackData": "home_menu"}}],
        # SMS fallback for the entry message; inactive unless deployed with
        # -c smsFallbackNumber=+1... (see common.send_rcs). The link is the whole
        # point of this vignette and survives as SMS fine, so the fallback loses
        # little here -- unlike the card-and-chips vignettes.
        "_fallback_body": (
            f"{c.brand_name()}: your loan agreement is ready to review and sign "
            f"on our secure page. {url}"
        ),
    }]


def preview_message():
    """Dashboard-only phone preview. Same shape as a real send; no side effects."""
    return _agreement_card("")


def on_postback(phone, phone_hash, postback_data):
    return None
