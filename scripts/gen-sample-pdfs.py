#!/usr/bin/env python3
"""Generate the two sample PDFs the pharmacy vignette sends, one per transport.

The pair exists to make one point on a handset: **the delivery path has to match
the sensitivity of the document.**

  media/rx-medication-facts.pdf   generic drug information, identical for every
                                  member. Sent as an RCS `FileMessage`, so AWS
                                  fetches it from S3, rehosts it, and it travels
                                  the RCS/carrier network to the device.
  secure-docs/rx-patient-info.pdf a patient record: name, address, prescriber,
                                  directions. Never sent as a message. It is
                                  fetched over HTTPS by the webview at
                                  lambda/webviews/rx-patient-info.html through a
                                  short-lived presigned URL, so it stays inside
                                  the account's own boundary.

Both are fictitious. The patient in the second one does not exist, and the phone
number is in the 555 range reserved for fiction.

The patient record is PHI-*shaped* sample data for demonstration only. It is not
real Protected Health Information, and this demo is not a HIPAA-compliant system.
A real deployment handling PHI is responsible for its own compliance controls
(AWS Business Associate Addendum, encryption at rest and in transit, audit
logging, access controls). See https://aws.amazon.com/compliance/hipaa-compliance/.

Written as raw PDF rather than with a library so the repo needs no extra
dependency to regenerate a demo asset, and so the bytes stay small enough
(single figures of KB) to be an unremarkable attachment.

Usage:  python3 scripts/gen-sample-pdfs.py
"""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Page layout, in PDF points (72 per inch) on US Letter.
LEFT = 72
TOP = 720
BOTTOM = 60


def esc(text):
    r"""Escape a string for a PDF literal. `(`, `)` and `\` are the delimiters
    of the literal itself; a hyphen is written as its octal escape because
    Helvetica renders the ASCII hyphen fine but some viewers reflow a bare `-`
    at a line break."""
    out = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    return out.replace("-", r"\055")


def render(lines):
    """Turn (size, text) pairs into a content stream, one text object per line.

    A `None` text is vertical space. Lines are laid out top-down and stop at the
    bottom margin rather than overflowing onto an invisible second page.
    """
    y = TOP
    parts = []
    for size, text in lines:
        if text is None:
            y -= size
            continue
        if y < BOTTOM:
            raise ValueError("content overflows one page - shorten it or add paging")
        parts.append(f"BT /F1 {size} Tf {LEFT} {y} Td ({esc(text)}) Tj ET")
        y -= size + 6
    return "\n".join(parts) + "\n"


def build_pdf(content):
    """Assemble a one-page PDF with a correct xref table.

    Byte offsets in the xref have to be exact, so the objects are serialized
    first and measured, rather than computed from assumed lengths.
    """
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(content)} >>\nstream\n{content}endstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    out = "%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n"
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    )
    return out.encode("latin-1")


# ── The document that may travel over the carrier network ───────────────────
# Nothing here identifies a member: no name, no address, no prescriber, no
# directions for an individual. That is the whole reason it is allowed on the
# FileMessage path, and the closing line says so inside the artifact so the
# distinction survives being screenshotted out of context.
MEDICATION_FACTS = [
    (20, "Magic Medicine Facts"),
    (11, "SAMPLE DOCUMENT - fictitious content for an AWS End User Messaging RCS demo."),
    (11, "Not medical advice. Not a real medication guide. No real product exists."),
    (18, None),
    (14, "Why members love it"),
    (11, "Magic Medicine is the little tablet with the big personality. Nine out of ten"),
    (11, "imaginary members report a pleasant sense of wonderment within the hour, and"),
    (11, "a lingering awe that lasts right through to the next imaginary refill."),
    (14, None),
    (14, "The general idea"),
    (11, "One tablet, twice a day, with or without a snack. Store it somewhere cool,"),
    (11, "dry and slightly mysterious. Keep the cap on. Keep the wonder in."),
    (14, None),
    (14, "Things that may happen"),
    (11, "Mild whimsy. Occasional humming. A sudden urge to describe a sunset in"),
    (11, "unnecessary detail. None of these are real, because none of this is real."),
    (14, None),
    (14, "Questions?"),
    (11, "Tap Talk to Pharmacist in the message thread and a person will answer."),
    (11, "Bring your prescription number; we will not ask for it over the message."),
    (24, None),
    (10, "Why this document is allowed in the message thread: it is the same file for"),
    (10, "every member. It contains no patient name, address, prescriber or directions,"),
    (10, "so nothing about any individual crosses the carrier network when it is sent."),
    (10, "Anything that does identify a member goes through the secure webview instead."),
]

# ── The document that must NOT ─────────────────────────────────────────────
# Every line below is the sort of thing that makes a document a patient record.
# It is deliberately vivid so the contrast lands: this is what you must not
# hand to a FileMessage.
PATIENT_INFO = [
    (20, "Patient Prescription Record"),
    (11, "SAMPLE DOCUMENT - fictitious patient, fictitious prescriber, fictitious drug."),
    (11, "Generated for an AWS End User Messaging RCS demo. Not medical advice."),
    (18, None),
    (14, "Patient"),
    (11, "Name:            Jordan A. Vasquez"),
    (11, "Date of birth:   11 March 1984"),
    (11, "Member ID:       AH-PPO-00427-3"),
    (11, "Address:         1420 Walnut Street, Apt 6C, Philadelphia, PA 19102"),
    (11, "Phone:           +1 215 555 0147"),
    (14, None),
    (14, "Prescriber"),
    (11, "Dr. Amara Reyes, MD - Walnut Street Family Medicine"),
    (11, "NPI 1234567890   Direct: +1 215 555 0182"),
    (14, None),
    (14, "Prescription"),
    (11, "Rx number:       8842119"),
    (11, "Medication:      Magic Medicine 10 mg tablet (30-day supply)"),
    (11, "Directions:      Take 2 tablets by mouth daily for wonderment and awe."),
    (11, "Refills:         4 remaining, through 12 December 2026"),
    (11, "Indication:      Persistent under-appreciation of small things"),
    (11, "Allergies:       Penicillin (documented rash, 2019)"),
    (14, None),
    (14, "Pharmacy notes"),
    (11, "Counselled on taking both tablets at the same time each day. Member asked"),
    (11, "about the humming; reassured it passes. Follow up at next refill."),
    (24, None),
    (10, "Why this document is NOT sent into the message thread: every line above"),
    (10, "identifies an individual. It is served only to this conversation, over HTTPS,"),
    (10, "through a short-lived presigned URL requested by the in-conversation webview,"),
    (10, "so the bytes never enter the RCS/carrier delivery chain."),
    (10, None),
    (10, "HIPAA: this is fictitious sample data. Real Protected Health Information"),
    (10, "requires HIPAA-compliant handling (an AWS Business Associate Addendum,"),
    (10, "encryption, audit logging, access controls) that this demo does not provide;"),
    (10, "compliance is the customer's responsibility. See aws.amazon.com/compliance/hipaa-compliance/"),
]


def write(rel_path, lines):
    path = os.path.join(ROOT, rel_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = build_pdf(render(lines))
    with open(path, "wb") as fh:
        fh.write(data)
    print(f"  {rel_path:38s} {len(data):,} bytes")


if __name__ == "__main__":
    print("Generating sample PDFs")
    write("media/rx-medication-facts.pdf", MEDICATION_FACTS)
    write("secure-docs/rx-patient-info.pdf", PATIENT_INFO)
    print("Done.")
