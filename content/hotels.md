---
# AnyTravel — hotel portfolio, rates, and member offers (sample knowledge).
#
# This file is the single source of truth for AnyTravel's three hotel vignettes
# (the four airline vignettes read content/flights.md):
#   • Room Booking     (AI-driven)     — grounded by the PROSE BODY below plus a
#                                        rate table generated from this frontmatter.
#   • Express Check-In (deterministic) — reads `properties` + `upgrades`.
#   • Travel Offers    (deterministic) — reads `offers` (+ `properties`).
#
# PRICING RULE (one rule, no other price source):
#   • The standard nightly rate for a stay is `properties[].rates[roomId]`.
#   • `roomTypes[].nightly` is only the portfolio "from" price. It is never a
#     quote source.
#   • A member rate exists only on a Travel Offer (`offers[].memberRate`), and
#     only for a stay the guest started from that offer, in that offer's
#     property and `roomId`. Every other stay or room is quoted at the standard
#     rate. The offer's `checkIn` / `checkOut` roll forward a year at a time when
#     they pass, so they need no yearly edit.
#
# Illustrative sample data for a fictitious hotel group. Every property name,
# address, rate and event below is invented for this demo — do not substitute
# real hotel, venue, or event names, which are trademarks of their owners.
# Edit freely.

# Check-in and check-out times, 24-hour HH:MM, hotel-local. The booking
# confirmation and its Add to Calendar event use these.
checkInTime: "15:00"
checkOutTime: "11:00"

# `id` values must be unique and postback-safe (lowercase, no spaces): they end
# up inside PostbackData (e.g. "offers_book_seattle_concert",
# "checkin_up_suite_upgrade"), which the channel adapter routes on.
properties:
  - id: "harbor"
    name: "AnyTravel Harbor"
    city: "Seattle, WA"
    address: "500 Alaskan Way, Seattle"
    lat: 47.6050
    lng: -122.3400
    blurb: "Waterfront rooms over Elliott Bay, 10 min from downtown venues."
    nightlyFrom: 219.00
    # Standard nightly rates (USD) by room type id. nightlyFrom equals the king rate.
    rates: { king: 219.00, double: 249.00, suite: 379.00 }
    image: "media/anytravel/hotels/anytravel-harbor.png"
    photo: "media/anytravel/hotels/property-harbor.jpg"
  - id: "midtown"
    name: "AnyTravel Midtown"
    city: "New York, NY"
    address: "140 W 42nd St, New York"
    lat: 40.7550
    lng: -73.9870
    blurb: "Steps from the theater district and the arena — ideal for event nights."
    nightlyFrom: 289.00
    # Standard nightly rates (USD) by room type id. nightlyFrom equals the king rate.
    rates: { king: 289.00, double: 319.00, suite: 429.00 }
    image: "media/anytravel/hotels/anytravel-midtown.png"
    photo: "media/anytravel/hotels/property-midtown.jpg"
  - id: "riverwalk"
    name: "AnyTravel Riverwalk"
    city: "Austin, TX"
    address: "98 San Jacinto Blvd, Austin"
    lat: 30.2640
    lng: -97.7420
    blurb: "On the river, a short walk from the stadium and live-music district."
    nightlyFrom: 199.00
    # Standard nightly rates (USD) by room type id. nightlyFrom equals the king rate.
    rates: { king: 199.00, double: 229.00, suite: 349.00 }
    image: "media/anytravel/hotels/anytravel-riverwalk.png"
    photo: "media/anytravel/hotels/property-riverwalk.jpg"
# Room types offered across the portfolio. `nightly` is the portfolio "from"
# price only; it is NOT a quote source. The rate for a stay is
# properties[].rates[roomId]. A member rate exists only on a Travel Offer
# (offers[].memberRate, for that offer's roomId on its dates).
# `photos` is exactly two repo paths, in order: photo 1 is the card in the room
# carousel, photo 2 is the detail card sent after the guest taps Choose.
roomTypes:
  - id: "king"
    name: "King Room"
    sleeps: 2
    nightly: 219.00
    blurb: "One king bed, work desk, city or courtyard view."
    photos: ["media/anytravel/rooms/room-king-1.jpg", "media/anytravel/rooms/room-king-2.jpg"]
  - id: "double"
    name: "Double Queen"
    sleeps: 4
    nightly: 249.00
    blurb: "Two queen beds — good for families or a group heading to an event."
    photos: ["media/anytravel/rooms/room-double-1.jpg", "media/anytravel/rooms/room-double-2.jpg"]
  - id: "suite"
    name: "Executive Suite"
    sleeps: 3
    nightly: 379.00
    blurb: "Separate living area, lounge access, late checkout included."
    photos: ["media/anytravel/rooms/room-suite-1.jpg", "media/anytravel/rooms/room-suite-2.jpg"]

# Paid/complimentary upgrades offered at express check-in (Express Check-In
# flow). `price` of 0 renders as "Complimentary".
upgrades:
  - id: "none"
    name: "Keep my room"
    price: 0.00
    blurb: "No change — proceed with the room on your reservation."
  - id: "high_floor"
    name: "High floor"
    price: 0.00
    blurb: "Complimentary for members — a higher floor, same room type."
  - id: "suite_upgrade"
    name: "Suite upgrade"
    price: 90.00
    blurb: "Move up to an Executive Suite with lounge access and late checkout."
  - id: "late_checkout"
    name: "Late checkout (2 PM)"
    price: 25.00
    blurb: "Hold your room until 2 PM on departure day."

# Event-tie-in marketing offers (Travel Offers flow). Each offer pairs a public
# event with a nearby property and a member rate. Promotional content is kept
# clean: brand present, no prohibited content. These are opt-in member offers
# for a demo.
#
# `offersIntro` is the text message sent just before the offers carousel, so the
# guest knows what they are about to swipe through. `{brand}` is replaced with
# the brand name. Keep it under 300 characters so the first card stays on screen.
offersIntro: "Hi, and welcome to {brand}! We've lined up member offers around upcoming events in our cities, each with a special nightly rate on a nearby stay. Swipe through to see what's on, then tap Book This Stay on any card to start your reservation."
offers:
  - id: "seattle_concert"
    headline: "Summer Concert Weekend"
    event: "Harbor Lights Music Festival — Aug 15–16"
    propertyId: "harbor"
    memberRate: 189.00
    # The room the memberRate is priced for. Other rooms use the standard rate.
    roomId: "king"
    perk: "Late checkout + 2 festival shuttle passes"
    image: "media/anytravel/hotels/offer-concert.jpg"
    # Stay dates implied by the event. Passed straight into the booking flow
    # when a guest selects this offer, so they never re-enter dates. ISO
    # YYYY-MM-DD; checkIn is the night before/of the event, checkOut the morning
    # after. Keep these consistent with the human `event` string above.
    checkIn: "2026-08-15"
    checkOut: "2026-08-17"
  - id: "nyc_game"
    headline: "Game Night in Midtown"
    event: "Metros vs. Capitals — Sept 7, 7:30 PM"
    propertyId: "midtown"
    memberRate: 259.00
    # The room the memberRate is priced for. Other rooms use the standard rate.
    roomId: "king"
    perk: "Arena-view room + early check-in"
    image: "media/anytravel/hotels/offer-game.jpg"
    checkIn: "2026-09-07"
    checkOut: "2026-09-08"
  - id: "austin_marathon"
    headline: "Riverwalk Marathon Stay"
    event: "Austin City Marathon — Oct 19"
    propertyId: "riverwalk"
    memberRate: 179.00
    # The room the memberRate is priced for. Other rooms use the standard rate.
    roomId: "king"
    perk: "5 AM breakfast + guaranteed late checkout for runners"
    image: "media/anytravel/hotels/offer-marathon.jpg"
    checkIn: "2026-10-18"
    checkOut: "2026-10-19"

# Tone for AI-assisted copy (the Room Booking assistant).
tone: "Warm, efficient concierge. Confirm dates, city, party size and room type before quoting. Never invent a property or event that isn't listed below."
---

# Booking & Stays (sample knowledge)

This grounds the **Room Booking** AI assistant and the two deterministic hotel
vignettes (Express Check-In, Travel Offers). Everything here is illustrative
sample data for a fictitious hotel group — edit the frontmatter above to change
properties, rates, times, upgrades, or offers.

## Properties

- **AnyTravel Harbor** — Seattle, WA. Waterfront rooms over Elliott Bay, about
  ten minutes from downtown venues.
- **AnyTravel Midtown** — New York, NY. In the theater district, steps from the
  arena — the natural choice for an event night.
- **AnyTravel Riverwalk** — Austin, TX. On the river, a short walk from the
  stadium and the live-music district.

## Room types

- **King Room** — one king bed, sleeps 2.
- **Double Queen** — two queen beds, sleeps 4. Good for families or a group
  heading to an event.
- **Executive Suite** — separate living area, lounge access, late checkout,
  sleeps 3.

## Rates & member offers

You are given a generated rate table with the nightly rate for every property
and room type. Quote a nightly rate only from that table, and never state a
price from memory or from this prose. Only a Travel Offer carries a member rate;
every other stay is quoted at the standard nightly rate from the table. Members
also get complimentary high-floor placement at check-in when available.

## How to help a guest book

1. Confirm the **city or property**, **check-in and check-out dates**, and
   **number of guests**.
2. Suggest a suitable **room type** from the list above and quote the nightly
   rate from the rate table.
3. Summarize the stay (property, dates, nights, room, total estimate) using the
   rate from the rate table, and ask the guest to confirm before "booking".
4. Offer natural next steps as suggestion chips — change dates, change room,
   confirm booking, or talk to a person.

Never invent a property, room type, or price that is not in the rate table. If
the guest asks for a city that is not served, say so plainly and name the three
cities that are available.

## Tone

Warm and efficient, like a good concierge. Keep replies short and skimmable on a
phone.
