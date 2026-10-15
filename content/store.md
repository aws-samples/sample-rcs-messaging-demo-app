---
# AnyHealth Wellness Store — product catalog.
#
# Drives the conversational cart/catalog vignette (RCS carousel + cart).
# Edit, add, or remove products here. `id` must be unique and postback-safe
# (lowercase, no spaces). `image` is an object key under the demo's media
# S3 bucket (uploaded automatically at deploy time).
storeName: "AnyHealth Wellness Store"
currency: "USD"
products:
  - id: "mega_ice_pack"
    name: "Mega Ice Pack"
    price: 24.99
    blurb: "Oversized reusable therapy ice pack. Flexible when frozen, covers back or knees."
    image: "media/store/mega-ice-pack.png"
    category: "Recovery"
  - id: "calming_book"
    name: "Coffee Table Book of Calming"
    price: 34.99
    blurb: "120 pages of serene landscapes and breathing prompts. A little calm on every table."
    image: "media/store/calming-book.png"
    category: "Mindfulness"
  - id: "medicine_spoon"
    name: "Medicine Spoon"
    price: 8.99
    blurb: "Dual-marked dosing spoon (2.5ml / 5ml). Dishwasher safe, easy-read markings."
    image: "media/store/medicine-spoon.png"
    category: "Home Care"
  - id: "sleep_sound_machine"
    name: "Sleep Sound Machine"
    price: 49.99
    blurb: "20 soothing sounds and a soft night light. Timer and memory settings."
    image: "media/store/sleep-sound-machine.png"
    category: "Sleep"
  - id: "herbal_tea_sampler"
    name: "Herbal Tea Sampler"
    price: 19.99
    blurb: "Caffeine-free sampler: chamomile, peppermint, lemon balm, and rooibos."
    image: "media/store/herbal-tea-sampler.png"
    category: "Wellness"
---

# AnyHealth Wellness Store

A small, illustrative catalog of self-care products used by the conversational
cart vignette. Members browse a carousel, add items to a persistent cart, and
check out — all inside the RCS conversation. Prices and products are sample
data; edit the frontmatter above to change the store.

**No payment is taken.** "Checkout" only clears the cart and sends an
"Order Confirmed" card; the sample never asks for, receives or stores payment
card data. If you adapt this flow to take real payments, PCI DSS applies to how
card data is collected and handled: keep card entry out of the message thread,
send the member to a payment page or service that is PCI DSS compliant, and
treat compliance as a shared responsibility between you and your providers
(see [AWS PCI DSS compliance](https://aws.amazon.com/compliance/pci-dss-level-1-faqs/)).
