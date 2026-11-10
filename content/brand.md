---
# ─────────────────────────────────────────────────────────────
# Brand catalog — the single source of truth.
#
# This demo ships a catalog of independent, standalone brands. Each
# key under `brands:` below is one brand; add a block to add a brand.
# Each brand deploys as its own stack with its own RCS agent, selected
# with the CDK context flag `-c brand=<id>` (default: the
# `defaultBrand` below); scripts/deploy.mjs deploys several in one run.
# There is no umbrella or parent brand — the brands are unrelated
# siblings and none groups or owns the others.
#
# Edit this file to re-theme any brand (brand name, colors, copy) AND
# to drive that brand's RCS testing-agent registration.
#
# Consumed by:
#   • AGENTS.md agent setup    → RCS testing registration fields
#   • cdk/lib/config.ts        → resource-name prefix (from brandName)
#   • lambda/* (bundled)       → in-message branding + AI prompts
#   • web/ (via GET /api/brand) → dashboard theming
#
# NOTHING here is hardcoded elsewhere. Change it here, redeploy.
# ─────────────────────────────────────────────────────────────

# Which brand to stand up when the deployer names none (-c brand=<id>).
# Must be a key under `brands:` below.
defaultBrand: "anyhealth"

# The brand catalog. Each entry is a stable id -> complete identity block.
# Every accentColor MUST pass WCAG 4.5:1 contrast vs white or the RCS
# registration rejects it.
#
# `homeMenu` (per brand): the reply chips of the home menu (the welcome
# message a Reset lands on), in display order. Each entry is
# `{ label, postback }`. At most 10 entries; each label at most 25
# characters; each postback must be one that lambda/channel_adapter.py
# routes. Adding, renaming or removing a tile is an edit here only.
#
# `vignettes` (per brand): the vignette ids the brand owns. A brand opens
# only its own vignettes; every id must match an id in the dashboard
# catalog (VIGNETTES in lambda/dashboard_handler.py), and that entry's
# `brand` tag must be this brand. `welcome` and `handover` are allowed on
# every brand, so a brand may list them or leave them out.
#
# `defaultVignette` (per brand): the id of the AI assistant vignette that
# answers typed text no other rule matches. Empty ("") means the brand has
# no such assistant: unmatched text gets the home menu instead.
#
# `memberName`, `memberPlan`, `memberIdMasked`, `memberCity` (per brand):
# the sample profile carried in that brand's AI prompt. An empty value is
# left out of the prompt. The top-level member keys below are the shared
# fallback for a brand block that omits them.
brands:

  anyhealth:
    displayName: "AnyHealth"
    lineOfBusiness: "Healthcare — appointments, prescriptions, benefits, wellness store."
    # Registration fields (used by the RCS testing registration).
    # These map 1:1 to agentDetails.* fields required by AWS EUM RCS.
    brandName: "AnyHealth"                       # 2–100 chars
    serviceName: "AnyHealth Member Services"     # 1–100 chars
    senderDisplayName: "AnyHealth"               # 1–40 chars
    useCase: "MULTI_USE"                         # OTP | TRANSACTIONAL | PROMOTIONAL | MULTI_USE
    agentDescription: "Appointments, prescriptions, benefits, and the AnyHealth wellness store." # 5–100 chars
    accentColor: "#0B6E6F"                       # hex, drives message cards + dashboard. MUST pass WCAG 4.5:1 vs white (dark teal ~6:1 here).
    logoImage: "media/anyhealth/logo.png"        # 224x224 PNG
    bannerImage: "media/anyhealth/banner.png"    # 1440x448 PNG or JPEG
    cardImage: "media/anyhealth/card.png"         # 1440x480, wordmark centred: welcome / check-in card media (not a registration field)
    privacyPolicyUrl: "https://anyhealth.example.com/privacy"
    termsAndConditionsUrl: "https://anyhealth.example.com/terms"
    averageMonthlyRcsFrequency: "100"            # one of: 10 | 100 | 1000+
    monthlyRcsVolume: "1000"                     # digits only, 1–999999
    # At least one contact method + its label is required.
    contactWebsite: "https://anyhealth.example.com"
    contactWebsiteLabel: "Visit AnyHealth"
    contactPhoneNumber: "+18005550100"
    contactPhoneLabel: "Member Services"
    contactEmailAddress: "support@anyhealth.example.com"
    contactEmailLabel: "Email Support"
    # App-level branding (dashboard + message copy).
    tagline: "Your health, one message away."
    # Pre-populated message body for the agent's inbound deep link (console →
    # your RCS agent → Testing → Inbound deep link). A member who scans that QR
    # code sends this text, and the channel adapter opens the welcome message.
    deepLinkKeyword: "Get started"
    memberServicesPhone: "+18005550100"          # used by AI + flows for "Call Member Services"
    liveAgentRole: "care advocate"            # the human on a live-agent handover, per brand
    # AI grounding files for this brand (under content/).
    groundingFiles: ["benefits.md", "providers.md", "store.md"]
    # Vignette ownership (see the header comment).
    vignettes: [welcome, rx_refill, appt_reminder, appt_reschedule, verification, store, benefits_qa, find_care, handover, photo_submission, insurance_upload, media_probe, video_visit, ivs_experiment, ivs_fitness]
    defaultVignette: "benefits_qa"
    # Sample member profile carried in the AI prompt.
    memberName: "Sarah Mitchell"
    memberPlan: "AnyHealth Complete PPO"
    memberIdMasked: "****7842"
    memberCity: "Philadelphia, PA"
    # Home menu: the reply chips of the welcome message a Reset lands on.
    homeMenu:
      - { label: "Prescriptions", postback: "home_rx" }
      - { label: "Appointments", postback: "home_appt" }
      - { label: "Ask About Benefits", postback: "home_benefits" }
      - { label: "Find Care", postback: "home_find_care" }
      - { label: "Wellness Store", postback: "home_store" }
      - { label: "Verify Login", postback: "home_verify" }
      - { label: "Send a Photo", postback: "home_photo" }
      - { label: "Upload Securely", postback: "home_upload" }

  anytravel:
    displayName: "AnyTravel"
    lineOfBusiness: "Travel and hospitality — hotels, flights, bags and travel offers."
    brandName: "AnyTravel"
    serviceName: "AnyTravel Traveler Services"
    senderDisplayName: "AnyTravel"
    useCase: "MULTI_USE"
    agentDescription: "Book your trip, check in from your phone, and get travel offers — straight from chat."
    accentColor: "#1266A1"                       # deep ocean blue, WCAG ~6.1:1 vs white
    logoImage: "media/anytravel/logo.png"
    bannerImage: "media/anytravel/banner.png"
    cardImage: "media/anytravel/card.png"
    privacyPolicyUrl: "https://anytravel.example.com/privacy"
    termsAndConditionsUrl: "https://anytravel.example.com/terms"
    averageMonthlyRcsFrequency: "100"
    monthlyRcsVolume: "1000"
    contactWebsite: "https://anytravel.example.com"
    contactWebsiteLabel: "Visit AnyTravel"
    contactPhoneNumber: "+18005550102"
    contactPhoneLabel: "Traveler Services"
    contactEmailAddress: "support@anytravel.example.com"
    contactEmailLabel: "Email Support"
    tagline: "Your trip, one message away."
    deepLinkKeyword: "Get started"
    memberServicesPhone: "+18005550102"
    liveAgentRole: "booking concierge"
    groundingFiles: ["hotels.md", "flights.md"]
    vignettes: [trip_assistant, room_booking, express_checkin, travel_offers, flight_checkin, flight_status, flight_rebooking, bag_tracking]
    defaultVignette: "trip_assistant"
    memberName: "Alex Rivera"
    memberPlan: "AnyTravel Rewards Gold"
    memberIdMasked: "****3150"
    memberCity: "Chicago, IL"
    homeMenu:
      - { label: "Book a Room", postback: "home_booking" }
      - { label: "Express Check-In", postback: "home_checkin" }
      - { label: "Travel Offers", postback: "home_offers" }
      - { label: "Flight Check-In", postback: "home_flight_checkin" }
      - { label: "Flight Status", postback: "home_flight_status" }
      - { label: "Rebook a Flight", postback: "home_rebooking" }
      - { label: "Track My Bag", postback: "home_bags" }
      - { label: "Ask About My Trip", postback: "home_ask_trip" }

  anywealth:
    displayName: "AnyWealth"
    lineOfBusiness: "Financial services — fraud alerts, transactional, account servicing."
    brandName: "AnyWealth"
    serviceName: "AnyWealth Account Services"
    senderDisplayName: "AnyWealth"
    useCase: "MULTI_USE"
    agentDescription: "Fraud alerts, transaction confirmations, and account servicing you can trust."
    accentColor: "#146B4A"                       # deep green, WCAG ~6.5:1 vs white
    logoImage: "media/anywealth/logo.png"
    bannerImage: "media/anywealth/banner.png"
    cardImage: "media/anywealth/card.png"
    privacyPolicyUrl: "https://anywealth.example.com/privacy"
    termsAndConditionsUrl: "https://anywealth.example.com/terms"
    averageMonthlyRcsFrequency: "100"
    monthlyRcsVolume: "1000"
    contactWebsite: "https://anywealth.example.com"
    contactWebsiteLabel: "Visit AnyWealth"
    contactPhoneNumber: "+18005550103"
    contactPhoneLabel: "Account Services"
    contactEmailAddress: "support@anywealth.example.com"
    contactEmailLabel: "Email Support"
    tagline: "Your money, one message away."
    deepLinkKeyword: "Get started"
    memberServicesPhone: "+18005550103"
    liveAgentRole: "financial services specialist"
    groundingFiles: ["wealth.md"]
    vignettes: [account_assistant, wealth_fraud_alert, loan_agreement]
    defaultVignette: "account_assistant"
    memberName: "Priya Raman"
    memberPlan: "AnyWealth Everyday Checking"
    memberIdMasked: "****5190"
    memberCity: "Austin, TX"
    homeMenu:
      - { label: "Fraud Alert", postback: "home_fraud" }
      - { label: "Loan Agreement", postback: "home_loan" }
      - { label: "Ask About My Account", postback: "home_ask_account" }

  anyhr:
    displayName: "AnyHR"
    lineOfBusiness: "HR and employee-management software — workforce self-service: clock in/out, schedule, PTO, shift swap."
    brandName: "AnyHR"
    serviceName: "AnyHR Workforce Services"
    senderDisplayName: "AnyHR"
    useCase: "MULTI_USE"
    agentDescription: "Clock in/out, view your schedule, request PTO, and swap shifts — straight from chat."
    accentColor: "#5B3FA6"                       # deep violet, WCAG ~7.8:1 vs white
    logoImage: "media/anyhr/logo.png"
    bannerImage: "media/anyhr/banner.png"
    cardImage: "media/anyhr/card.png"
    privacyPolicyUrl: "https://anyhr.example.com/privacy"
    termsAndConditionsUrl: "https://anyhr.example.com/terms"
    averageMonthlyRcsFrequency: "100"
    monthlyRcsVolume: "1000"
    contactWebsite: "https://anyhr.example.com"
    contactWebsiteLabel: "Visit AnyHR"
    contactPhoneNumber: "+18005550104"
    contactPhoneLabel: "People Team"
    contactEmailAddress: "support@anyhr.example.com"
    contactEmailLabel: "Email Support"
    tagline: "Your workday, one message away."
    deepLinkKeyword: "Get started"
    memberServicesPhone: "+18005550104"
    liveAgentRole: "people team specialist"
    groundingFiles: ["workplace.md"]
    vignettes: [hr_assistant, clock_in_out, my_schedule, pto_request, shift_swap]
    defaultVignette: "hr_assistant"
    memberName: "Jordan Blake"
    memberPlan: "Store Associate, Operations"
    memberIdMasked: "****4821"
    memberCity: "Chicago, IL"
    homeMenu:
      - { label: "Clock In / Out", postback: "home_clock" }
      - { label: "My Schedule", postback: "home_schedule" }
      - { label: "Request PTO", postback: "home_pto" }
      - { label: "Swap a Shift", postback: "home_swap" }
      - { label: "Ask HR", postback: "home_ask_hr" }

  anybuild:
    displayName: "AnyBuild"
    lineOfBusiness: "Residential construction software — field messaging between builders, suppliers and trades: evidence, deliveries, schedules and job readiness."
    brandName: "AnyBuild"
    serviceName: "AnyBuild Field Services"
    senderDisplayName: "AnyBuild"
    useCase: "MULTI_USE"
    agentDescription: "Jobsite updates for builders and suppliers: deliveries, crew plans, job readiness and photo proof."
    accentColor: "#9A3F12"                       # burnt clay, WCAG ~6.9:1 vs white
    logoImage: "media/anybuild/logo.png"
    bannerImage: "media/anybuild/banner.png"
    cardImage: "media/anybuild/card.png"
    privacyPolicyUrl: "https://anybuild.example.com/privacy"
    termsAndConditionsUrl: "https://anybuild.example.com/terms"
    averageMonthlyRcsFrequency: "100"
    monthlyRcsVolume: "1000"
    contactWebsite: "https://anybuild.example.com"
    contactWebsiteLabel: "Visit AnyBuild"
    contactPhoneNumber: "+18005550105"
    contactPhoneLabel: "Field Support"
    contactEmailAddress: "support@anybuild.example.com"
    contactEmailLabel: "Email Support"
    tagline: "Your jobsite, one message away."
    deepLinkKeyword: "Get started"
    memberServicesPhone: "+18005550105"
    liveAgentRole: "field support specialist"
    groundingFiles: ["construction.md"]
    vignettes: [jobsite_assistant, hello_builder, hello_supplier, site_evidence, identity_capture, arrival_alert, delivery_location, field_schedule, job_readiness, agreement_waiver]
    defaultVignette: "jobsite_assistant"
    memberName: "Sam Okafor"
    memberPlan: "Site crew lead, Lot 42"
    memberIdMasked: "****0742"
    memberCity: "Raleigh, NC"
    homeMenu:
      - { label: "Hello: Builder App", postback: "home_hello_builder" }
      - { label: "Hello: Supplier App", postback: "home_hello_supplier" }
      - { label: "Site Evidence", postback: "home_evidence" }
      - { label: "Verify Identity", postback: "home_idcap" }
      - { label: "Arrival Alert", postback: "home_arrival" }
      - { label: "Delivery Location", postback: "home_delivery" }
      - { label: "Field Schedule", postback: "home_plan" }
      - { label: "Job Readiness", postback: "home_ready" }
      - { label: "Agreement/Waiver", postback: "home_agreement" }
      - { label: "Ask About the Site", postback: "home_ask_site" }

# Sample member profile (illustrative demo data, shared fallback).
memberName: "Sarah Mitchell"          # fallback only — the AI uses the recipient's Recipients-tab name
memberPlan: "AnyHealth Complete PPO"
memberIdMasked: "****7842"
memberCity: "Philadelphia, PA"

# ─────────────────────────────────────────────────────────────
# Legacy flat fallback (documented default — R11.3).
#
# These top-level keys mirror the AnyHealth identity block above.
# They exist ONLY as a fallback so an un-migrated file (one that has
# no `brands:` map) still deploys as AnyHealth alone: consumers that
# find no `brands` map synthesize a one-entry catalog from these keys
# under `defaultBrand`. When the `brands:` map is present (as it is
# here), these flat keys are ignored. Keep them in sync with
# brands.anyhealth, or delete them once every consumer reads the map.
# ─────────────────────────────────────────────────────────────
brandName: "AnyHealth"
serviceName: "AnyHealth Member Services"
senderDisplayName: "AnyHealth"
useCase: "MULTI_USE"
agentDescription: "Appointments, prescriptions, benefits, and the AnyHealth wellness store."
accentColor: "#0B6E6F"
logoImage: "media/anyhealth/logo.png"
bannerImage: "media/anyhealth/banner.png"
privacyPolicyUrl: "https://anyhealth.example.com/privacy"
termsAndConditionsUrl: "https://anyhealth.example.com/terms"
averageMonthlyRcsFrequency: "100"
monthlyRcsVolume: "1000"
contactWebsite: "https://anyhealth.example.com"
contactWebsiteLabel: "Visit AnyHealth"
contactPhoneNumber: "+18005550100"
contactPhoneLabel: "Member Services"
contactEmailAddress: "support@anyhealth.example.com"
contactEmailLabel: "Email Support"
tagline: "Your health, one message away."
deepLinkKeyword: "Get started"
memberServicesPhone: "+18005550100"
liveAgentRole: "care advocate"
---

# Brand catalog

This demo ships a catalog of **fictitious**, independent brands covering various
industries and use cases, used to demonstrate AWS End User Messaging RCS. Each
brand deploys as its own stack with its own RCS agent (`-c brand=<id>`,
defaulting to AnyHealth); you can deploy one or several. None of them is a real
company, and they are unrelated — there is no parent or umbrella brand. This
version includes:

- **AnyHealth** — healthcare (appointments, prescriptions, benefits, wellness store)
- **AnyTravel** — travel and hospitality (hotel booking, mobile check-in, travel offers; room for more travel use cases such as airlines)
- **AnyWealth** — financial services (fraud alerts, transactional, account servicing)
- **AnyHR** — HR and employee-management software (workforce self-service)
- **AnyBuild** — residential construction software (field messaging for builders, suppliers and trades)

All plan details, providers, prices, products, and sample data referenced by the
grounding files are illustrative — edit them freely to adapt this demo to any
brand or industry.

The frontmatter above is the machine-readable brand catalog. The prose in the
sibling content files is loaded into the messaging Lambda at runtime to ground
the AI assistant and the deterministic flows; each brand's own grounding files
are named in its `groundingFiles` list:

- **AnyHealth** → `benefits.md`, `providers.md`, `store.md`
- **AnyHR** → `workplace.md`
- **AnyTravel** → `hotels.md`
- **AnyWealth** → `wealth.md`
- **AnyBuild** → `construction.md`
