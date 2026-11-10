"""Hello: Builder app — the welcome for the builder side of AnyBuild.

A short transactional welcome for a builder's superintendent or office: who is
writing, what to expect, how to opt out, and chips into the vignettes a builder
uses. See flows/_hello.py for the card and content/construction.md (`hello`)
for the copy.

Triggers: `Start: Hello_Builder`, or the `home_hello_builder` postback.
"""

from flows import _hello

_CHIPS = [
    ("Site Evidence", "home_evidence"),
    ("Field Schedule", "home_plan"),
    ("Job Readiness", "home_ready"),
]


def on_start(phone, phone_hash):
    return _hello.hello_card("builder", _CHIPS)


def on_trigger(phone, phone_hash, vignette):
    return _hello.hello_card("builder", _CHIPS)


def preview_message():
    return _hello.hello_card("builder", _CHIPS)


def on_postback(phone, phone_hash, postback_data):
    return None
