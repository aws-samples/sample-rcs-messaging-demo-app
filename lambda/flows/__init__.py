"""Flow registry — maps vignette keys to deterministic flow modules."""

from flows import (
    welcome, appointment, pharmacy, otp, store, handover,
    clock_in_out, my_schedule, pto_request, shift_swap,
    photo_submission, insurance_upload,
    media_probe, video_visit, ivs_experiment, ivs_fitness_experiment,
    loan_agreement,
)

FLOW_MAP = {
    "welcome": welcome,
    "rx_refill": pharmacy,
    "appt_reminder": appointment,
    "appt_reschedule": appointment,
    "verification": otp,
    "store": store,
    "handover": handover,
    # Internal staff vignettes (employee/staff use cases, not member-facing).
    "clock_in_out": clock_in_out,
    "my_schedule": my_schedule,
    "pto_request": pto_request,
    "shift_swap": shift_swap,
    # Rich-media demos — native RCS inbound media vs. compliance-forward
    # webview upload. See each module's docstring for the PII trade-off.
    "photo_submission": photo_submission,
    "insurance_upload": insurance_upload,
    # Signable document delivered OUT to be read and signed in a webview.
    "loan_agreement": loan_agreement,
    # Diagnostic, not a demo vignette — see the module docstring. Reports whether
    # an RCS webview can reach getUserMedia on a given handset; the result decides
    # whether a Chime SDK video call runs inside the conversation or in the device
    # browser.
    "media_probe": media_probe,
    # Experimental: a WebRTC video call (Chime SDK JS) inside the RCS webview.
    "video_visit": video_visit,
    # Experimental: opens a live Amazon IVS video stream in an RCS webview.
    # Opens the external https://icasino.ivsdemos.com/ demo as a top-level
    # webview. Diagnostic/experiment, surfaced in the Settings tab, not the
    # member-facing Use Case Examples list.
    "ivs_experiment": ivs_experiment,
    # Same experiment, IVS Interactive Fitness demo (https://fitness.ivsdemos.com/).
    "ivs_fitness": ivs_fitness_experiment,
}

# Vignettes handled by the Bedrock AI assistant rather than deterministic flows.
AI_DRIVEN_VIGNETTES = {"benefits_qa", "find_care"}


def get_flow(vignette: str):
    return FLOW_MAP.get((vignette or "").lower().replace(" ", "_"))
