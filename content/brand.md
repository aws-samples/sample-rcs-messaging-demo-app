---
# ─────────────────────────────────────────────────────────────
# AnyHealth brand identity — the single source of truth.
#
# Edit this file to re-theme the entire demo (brand name, colors,
# copy) AND to drive the RCS testing-agent registration.
#
# Consumed by:
#   • AGENTS.md agent setup    → RCS testing registration fields
#   • cdk/lib/config.ts        → resource-name prefix (from brandName)
#   • lambda/* (bundled)       → in-message branding + AI prompts
#   • web/ (via GET /api/brand) → dashboard theming
#
# NOTHING here is hardcoded elsewhere. Change it here, redeploy.
# ─────────────────────────────────────────────────────────────

# Registration fields (used by the RCS testing registration).
# These map 1:1 to agentDetails.* fields required by AWS EUM RCS.
brandName: "AnyHealth"                       # 2–100 chars
serviceName: "AnyHealth Member Services"     # 1–100 chars
senderDisplayName: "AnyHealth"               # 1–40 chars
useCase: "MULTI_USE"                         # OTP | TRANSACTIONAL | PROMOTIONAL | MULTI_USE
agentDescription: "Appointments, prescriptions, benefits, and the AnyHealth wellness store." # 5–100 chars
accentColor: "#0B6E6F"                        # hex, drives message cards + dashboard. MUST pass WCAG 4.5:1 vs white or RCS registration rejects it (dark teal ~6:1 here).
logoImage: "media/logo.png"                   # 224x224 PNG
bannerImage: "media/banner.png"               # 1440x448 PNG or JPEG
privacyPolicyUrl: "https://anyhealth.example.com/privacy"
termsAndConditionsUrl: "https://anyhealth.example.com/terms"
averageMonthlyRcsFrequency: "100"             # one of: 10 | 100 | 1000+
monthlyRcsVolume: "1000"                      # digits only, 1–999999

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

# Sample member profile (illustrative demo data).
memberName: "Sarah Mitchell"          # fallback only — the AI uses the recipient's Recipients-tab name
memberPlan: "AnyHealth Complete PPO"
memberIdMasked: "****7842"
memberCity: "Philadelphia, PA"
---

# AnyHealth

AnyHealth is a **fictitious** healthcare brand used to demonstrate AWS End User
Messaging RCS. It is not a real company. All plan details, providers, prices,
and products below are illustrative sample data — edit them freely to adapt this
demo to any brand or industry.

The frontmatter above is the machine-readable brand config. The prose in this
and the sibling content files (`benefits.md`, `providers.md`, `store.md`) is
loaded into the messaging Lambda at runtime to ground the AI assistant and the
deterministic flows.
