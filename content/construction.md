---
# AnyBuild — residential construction field messaging (sample knowledge).
#
# Grounds the nine AnyBuild vignettes. AnyBuild is construction software that
# connects home builders, their suppliers and the trades in the field; this
# sample models one fictitious builder, Quillfeather Homes, one supplier,
# Brindlewood Supply Co., and one jobsite:
#   • Hello: Builder app / Hello: Supplier app (`hello`) — welcome and opt-out.
#   • Site Evidence      (`evidenceKinds`)  — photo or video proof from the field.
#   • Identity Capture   (`idQuestion`, `idDocuments`) — asks which ID, then
#                        captures each side of a license or passport in a webview.
#   • Arrival Alert      (`arrival`)        — a geofence event, then a reply.
#   • Delivery Location  (`delivery`)       — where the load was left.
#   • Field Schedule     (`fieldPlan`)      — tomorrow's crew plan.
#   • Job Readiness      (`readiness`)      — dependencies and hand-offs.
#   • Agreement/Waiver   (no key here)      — the document is the webview page
#                        lambda/webviews/agreement-waiver.html; edit it there.
#
# Illustrative sample data only. Every builder, supplier, trade company, street
# and person below is invented for this demo — do not substitute real company
# names, which belong to their owners. Edit freely.
#
# Dates are NOT written here: each `dayOffset` counts days from today (UTC,
# negative = in the past), so every upcoming date stays upcoming. Times are
# 24-hour HH:MM, site-local.

builder: "Quillfeather Homes"

supplier:
  name: "Brindlewood Supply Co."
  driver: "Marcus Hale"
  dispatch: "Brindlewood dispatch"

site:
  community: "Larkmoor Commons"
  lot: "Lot 42"
  planName: "The Aster"
  address: "142 Fernhollow Lane, Raleigh, NC"
  lat: 35.8436
  lng: -78.6460
  superintendent: "Renee Alcott"

# Welcome messages, one per app side. `{brand}` is replaced with the brand name.
# These are the first message a person gets, so each says who is writing, what
# kind of messages to expect, and how to stop them.
hello:
  builder:
    title: "{brand} for Builders"
    intro: "Hi, this is {brand}. We'll message you here about your jobsites: crew plans, deliveries, inspections and what's ready for the next trade."
    bullets:
      - "Crew plans and job readiness"
      - "Delivery arrivals and drop locations"
      - "Photo and video evidence from the field"
  supplier:
    title: "{brand} for Suppliers"
    intro: "Hi, this is {brand}. We'll message you here about your orders: where to deliver, who to meet at the gate, and any delivery problems reported on site."
    bullets:
      - "Delivery locations and gate instructions"
      - "Arrival alerts as your truck nears a site"
      - "Damage reports with photos"

# Site Evidence: what the person is documenting. `outcome` is what happens next,
# shown after the photo or video arrives. `{supplier}` and `{lot}` are filled in.
evidenceKinds:
  - id: "inspection"
    name: "Inspection photos"
    chip: "Inspection"
    prompt: "Send photos or a short video of the work you want inspected."
    outcome: "Added to the {lot} inspection record. The inspector has been notified."
  - id: "work_ready"
    name: "Work is ready"
    chip: "Work Ready"
    prompt: "Send a photo or short video that shows the finished work."
    outcome: "The superintendent has been told the work is ready to check. The next trade is cleared once it's approved."
  - id: "damaged"
    name: "Damaged delivery"
    chip: "Damaged Delivery"
    prompt: "Send photos or a short video of the damage, and the label on the load if you can."
    outcome: "A damage claim is open with {supplier}, and they'll reply here with a replacement time."

# Identity Capture: the ID types the card asks the recipient to choose between,
# in the order the question names them. `steps` are the sides to photograph, in
# order: `side` is the fixed key each upload is filed under ("front" or "back";
# the upload API accepts only the sides listed here) and `label` is what the
# capture page shows. `question` is the card's ID-type question. The page never
# shows a preview of the image back; it shows what the document is, so a
# captured ID is not left on screen. The dashboard's Identity Capture card shows
# the operator the sides that were captured.
idQuestion: "Which ID will you use: a passport (front only) or a USA driver's license (front and back)?"
idDocuments:
  - id: "passport"
    name: "Passport"
    chip: "Passport (front only)"
    steps:
      - side: "front"
        label: "Front (photo page)"
  - id: "license"
    name: "USA driver's license"
    chip: "USA Driver's License"
    steps:
      - side: "front"
        label: "Front of license"
      - side: "back"
        label: "Back of license"

# Delivery Location: a load that was dropped, and where.
delivery:
  po: "PO-7741"
  items: "24 bundles of framing lumber"
  droppedLabel: "Driveway, north side"
  droppedTime: "7:42 AM"
  droppedLat: 35.84375
  droppedLng: -78.64585

# Arrival Alert: a truck has crossed the geofence around the community.
arrival:
  po: "PO-7742"
  items: "14 roof trusses"
  etaMinutes: 10
  geofenceName: "Larkmoor Commons"
  geofenceMiles: 2
  dropLabel: "Driveway, north side"

# Field Schedule: tomorrow's plan for the people in the trailer. The first task
# is the recipient's own (a name set on the Recipients tab replaces `lead`).
fieldPlan:
  dayOffset: 1
  meetTime: "07:00"
  endTime: "15:30"
  meetPoint: "Site trailer, Larkmoor Commons"
  backup: "Leo Ferraro"
  tasks:
    - { task: "Framing punch list", lead: "Sam Okafor", start: "07:00", confirmed: false }
    - { task: "Rough electrical, kitchen", lead: "Dana Whitfield", start: "07:30", confirmed: true }
    - { task: "Truss delivery, unload", lead: "Leo Ferraro", start: "09:00", confirmed: true }
    - { task: "Site cleanup", lead: "Priya Nandakumar", start: "13:00", confirmed: false }

# Job Readiness: a chain of steps where each waits on the ones it `needs`. The
# demo starts with the lower cabinets pending; marking them done unlocks the
# countertop install and sends that crew a ready message. A step with a
# `startDayOffset` is the one the ready message proposes a start for.
readiness:
  # What the countertop crew can tell us when it pushes back on a hand-off. Each
  # is a reply chip (25 characters at most).
  issues: ["Cabinets not level", "Wrong dimensions", "Site not clean"]
  chain:
    - id: "cabinets"
      name: "Lower cabinets installed"
      trade: "Alder & Oak Cabinetry"
      doneChip: "Cabinets Done"
    - id: "countertops"
      name: "Countertop install"
      trade: "Harrowgate Countertops"
      needs: ["cabinets"]
      startDayOffset: 3
      startTime: "08:00"
      durationDays: 1
      altStartDayOffsets: [4, 5]
    - id: "backsplash"
      name: "Backsplash tile"
      trade: "Wrenfield Tile Co."
      needs: ["countertops"]

# Tone for AI-assisted copy touching this content: the jobsite assistant's
# replies (common.assistant_facts passes it on).
tone: "Plain-spoken and brief, like a good site superintendent. Concrete places, times and quantities. No jargon without a quick explanation."
---

# AnyBuild — Quillfeather Homes (sample knowledge)

Sample data for eight RCS vignettes about running a jobsite. The builder,
**Quillfeather Homes**, is building **The Aster** on **Lot 42** in **Larkmoor
Commons**. Materials come from **Brindlewood Supply Co.** Two apps share one
sender identity: a builder app and a supplier app, each with its own welcome.

- **Hello: Builder app / Hello: Supplier app** — a short welcome that says who
  is writing, what to expect and how to opt out.
- **Site Evidence** — send a photo or video as an inspection record, as proof
  that work is ready, or to report a damaged delivery.
- **Identity Capture** — photograph a driver's license or a passport on a secure
  upload page. The image never travels through the conversation.
- **Arrival Alert** — a truck crosses the geofence and the site is told, with a
  reply to open the gate or hold the delivery. The geofence is detected by your
  own system; RCS carries the message.
- **Delivery Location** — "where is the framing lumber?" The drop spot is a map
  pin with a photo, and either side can correct it by sharing a location.
- **Field Schedule** — tomorrow's crew plan, with confirm or can't-make-it and a
  roll call.
- **Job Readiness** — the countertop crew is cleared the moment the lower
  cabinets are marked done, and the hand-off goes to them.

Everything here is illustrative: the companies, people, address, quantities and
times are invented. Edit the frontmatter to change them. No real customer data is
used and nothing is ordered, billed or scheduled.
