"""Flow registry — maps vignette keys to deterministic flow modules."""

from flows import (
    bag_tracking,
    flight_checkin,
    flight_rebooking,
    flight_status,
    welcome, appointment, pharmacy, otp, store, handover,
    clock_in_out, my_schedule, pto_request, shift_swap,
    photo_submission, insurance_upload,
    media_probe, video_visit, ivs_experiment, ivs_fitness_experiment,
    loan_agreement, express_checkin, travel_offers, wealth_fraud_alert,
    hello_builder, hello_supplier, site_evidence, identity_capture, arrival_alert,
    delivery_location, field_schedule, job_readiness, agreement_waiver,
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
    # New-brand representative vignettes, keyed by vignette id.
    # AnyTravel: deterministic, event-driven express check-in (reminder → upgrade
    # options → digital key) and a deterministic travel-offers carousel.
    "express_checkin": express_checkin,
    "travel_offers": travel_offers,
    # AnyTravel airline: check-in and boarding pass, a gate-change alert,
    # cancellation rebooking (with a hotel hand-off), and a delayed bag.
    "flight_checkin": flight_checkin,
    "flight_status": flight_status,
    "flight_rebooking": flight_rebooking,
    "bag_tracking": bag_tracking,
    # AnyWealth: verified-sender fraud alert with reply chips and expiring code.
    "wealth_fraud_alert": wealth_fraud_alert,
    # AnyBuild: field messaging between builders, suppliers and trades. Two app
    # welcomes, then photo/video evidence, ID capture (webview), a geofence
    # arrival, a delivery drop spot, tomorrow's crew plan, and a dependency chain.
    "hello_builder": hello_builder,
    "hello_supplier": hello_supplier,
    "site_evidence": site_evidence,
    "identity_capture": identity_capture,
    "arrival_alert": arrival_alert,
    "delivery_location": delivery_location,
    "field_schedule": field_schedule,
    "job_readiness": job_readiness,
    # AnyBuild's Agreement/Waiver: the same read-and-sign pattern as AnyWealth's
    # Loan Agreement, with a generic agreement and waiver document of its own.
    "agreement_waiver": agreement_waiver,
}

# Vignettes handled by the Bedrock AI assistant rather than deterministic flows.
# room_booking is AI-driven and has NO FLOW_MAP entry — membership here is what
# routes it through invoke_ai/send_ai_response.
# The four brand assistants (trip, account, hr, jobsite) are each brand's
# defaultVignette: they answer typed text no flow claims (channel_adapter
# _ASSISTANTS).
AI_DRIVEN_VIGNETTES = {
    "benefits_qa", "find_care", "room_booking",
    "trip_assistant", "account_assistant", "hr_assistant", "jobsite_assistant",
}


def get_flow(vignette: str):
    return FLOW_MAP.get((vignette or "").lower().replace(" ", "_"))
