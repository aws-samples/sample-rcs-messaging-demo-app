---
# AnyTravel — flights for the airline vignettes (sample knowledge).
#
# The single source of truth for AnyTravel's four airline vignettes:
#   • Flight Check-In     (`flight`, `seatOptions`) — check in, pick a seat, get a
#                         boarding pass in a webview.
#   • Flight Status       (`flight`, `statusChange`) — a gate change and delay alert.
#   • Disruption Rebooking (`disruption`)            — a cancelled flight and the next
#                         options in a carousel; an overnight option hands off to
#                         Room Booking for a hotel near the airport.
#   • Bag Tracking        (`bag`)                    — a delayed bag and where to
#                         deliver it.
#
# Illustrative sample data only. The airline is AnyTravel itself (one brand, not
# a sub-brand); every flight number, gate, seat, confirmation code and bag tag is
# invented. The airports are real public airports, named for realism; the
# terminals and gates given for them are not their real ones. Edit freely.
#
# Dates are NOT written here: each `dayOffset` counts days from today (UTC), so
# every flight stays upcoming. Times are 24-hour HH:MM, local to the airport
# they belong to (departure times at the origin, arrival times at the
# destination). `tz` is the airport's IANA time zone, used for calendar events;
# `utcOffsetHours` is the fallback when the runtime has no time zone database.

confirmation: "K7QZ4M"
cabin: "Main Cabin"

airports:
  ORD:
    name: "Chicago O'Hare International"
    city: "Chicago, IL"
    tz: "America/Chicago"
    utcOffsetHours: -6
    lat: 41.9786
    lng: -87.9048
  SEA:
    name: "Seattle-Tacoma International"
    city: "Seattle, WA"
    tz: "America/Los_Angeles"
    utcOffsetHours: -8
    lat: 47.4435
    lng: -122.3016
  JFK:
    name: "John F. Kennedy International"
    city: "New York, NY"
    tz: "America/New_York"
    utcOffsetHours: -5
    lat: 40.6413
    lng: -73.7781

# Flight Check-In and Flight Status: the traveler's next flight.
flight:
  number: "AT 482"
  from: "ORD"
  to: "SEA"
  dayOffset: 1
  departTime: "08:15"
  arriveTime: "10:55"
  terminal: "1"
  gate: "B14"
  boardingTime: "07:35"
  group: "4"
  seat: "14C"

# Seats offered at check-in. `price` of 0 renders as "No charge". The first entry
# is the seat already assigned. `id` ends up in PostbackData, so keep it
# lowercase with no spaces. Labels are chip text: 25 characters at most.
seatOptions:
  - { id: "14c", seat: "14C", label: "Keep 14C (aisle)", price: 0 }
  - { id: "9a", seat: "9A", label: "9A (window)", price: 0 }
  - { id: "3c", seat: "3C", label: "3C extra legroom", price: 49 }

# Flight Status: the same flight, moved to another gate and pushed back.
statusChange:
  newGate: "C22"
  newDepartTime: "08:45"
  newBoardingTime: "08:05"
  reason: "a late-arriving aircraft"

# Disruption Rebooking: tonight's connection is cancelled; these are the next
# options, shown as a carousel (2 to 10 cards). `dayOffset` on an option is days
# after the cancelled flight's day; `arriveDayDelta` is days after its departure.
# An option with `overnight: true` leaves tomorrow, so its confirmation offers a
# hotel tonight near the airport: `overnightPropertyId` is a property id in
# hotels.md, handed to Room Booking for tonight only.
disruption:
  dayOffset: 0
  cancelled: { number: "AT 1127", from: "SEA", to: "JFK", departTime: "19:40" }
  reason: "weather in the New York area"
  overnightPropertyId: "harbor"
  options:
    - { id: "a1131", number: "AT 1131", dayOffset: 0, departTime: "21:10", arriveTime: "05:35", arriveDayDelta: 1, stops: "Nonstop", seatsLeft: 6 }
    - { id: "a1145", number: "AT 1145 + AT 318", dayOffset: 0, departTime: "22:05", arriveTime: "08:50", arriveDayDelta: 1, stops: "1 stop, ORD", seatsLeft: 12 }
    - { id: "a1159", number: "AT 1159", dayOffset: 1, departTime: "07:00", arriveTime: "15:20", arriveDayDelta: 0, stops: "Nonstop", seatsLeft: 20, overnight: true }

# Bag Tracking: one checked bag that missed the flight above. Delivery goes to a
# hotel in hotels.md (`deliveryPropertyId`) or to a location the traveler shares.
bag:
  tag: "AT 482917"
  flightNumber: "AT 482"
  airport: "SEA"
  description: "Black hard-shell suitcase"
  nextFlight: "AT 486"
  nextArriveTime: "15:40"
  office: "Baggage Service Office, Carousel 12"
  deliveryWindow: "6–10 PM today"
  deliveryPropertyId: "harbor"
---

# AnyTravel flights (sample)

AnyTravel also flies. The sample traveler's next trip is flight AT 482 from
Chicago O'Hare (ORD) to Seattle-Tacoma (SEA), with a confirmation code of
K7QZ4M. Check-in, seat changes, rebooking and bag delivery are done in their
own dedicated messages. The trip assistant answers questions about the flights
and bags from the facts it is given. The hotel booking assistant does not: if a
guest asks it about a flight, say that the trip assistant (Ask About My Trip on
the menu) can help, and offer to help with a hotel instead.
