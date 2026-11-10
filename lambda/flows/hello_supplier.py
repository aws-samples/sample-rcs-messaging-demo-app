"""Hello: Supplier app — the welcome for the supplier side of AnyBuild.

A short transactional welcome for a supplier's dispatcher or driver: who is
writing, what to expect, how to opt out, and chips into the vignettes a supplier
uses. See flows/_hello.py for the card and content/construction.md (`hello`)
for the copy.

Triggers: `Start: Hello_Supplier`, or the `home_hello_supplier` postback.
"""

from flows import _hello

_CHIPS = [
    ("Arrival Alert", "home_arrival"),
    ("Delivery Location", "home_delivery"),
    ("Damage Report", "home_evidence"),
]


def on_start(phone, phone_hash):
    return _hello.hello_card("supplier", _CHIPS)


def on_trigger(phone, phone_hash, vignette):
    return _hello.hello_card("supplier", _CHIPS)


def preview_message():
    return _hello.hello_card("supplier", _CHIPS)


def on_postback(phone, phone_hash, postback_data):
    return None
