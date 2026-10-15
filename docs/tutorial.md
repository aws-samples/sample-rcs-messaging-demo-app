# AnyHealth: An RCS Tutorial

*A walkthrough for readers who are new to AWS End User Messaging RCS (herein "RCS"). It explains what RCS is, how
this demo is built, and why it's built that way. For exhaustive diagrams and
per-use-case-example flow charts, see [architecture.md](architecture.md); for
setup/run instructions, see the [README](../README.md) and [SETUP](../SETUP.md).*

## 0. What (or who) is AnyHealth?
AnyHealth itself is a **fictitious** healthcare brand. It's a stand-in so the
demo has a plausible, relatable set of use cases — refill a prescription,
confirm an appointment, ask a benefits question — but nothing about it is
healthcare-specific under the hood. Swap the four `content/*.md` files and
the same code demonstrates a retail loyalty program or a logistics tracking
line just as well.

## 1. What RCS is, and why AnyHealth uses it

RCS (Rich Communication Services) is often described as "SMS, upgraded."
That's the right mental model. It rides in the same native messaging app your
recipient already uses for texting — there's no separate app to install — but
it adds a verified brand identity (your logo, name, and colors), the
recipient's read receipts and typing indicators as events your code can receive,
and interactive content: buttons, image carousels, and rich cards, instead of
just a wall of text.

As of this writing (October 2026) AWS End User Messaging RCS is available in **22 countries** (against 200+ for SMS), and not every phone or carrier supports it: older Android devices, and iPhones on iOS below
18, don't.

[[What is RCS?]](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-overview.html)

| | SMS | RCS |
|---|---|---|
| Character limit | 160 per segment | 3,072 in one message, not split into segments |
| Media | compressed MMS | images, audio and PDF up to 100 MB; video (MP4, WebM) up to 5 MB |
| Read receipts / typing indicators | no | the recipient's, as events your code receives (§5); agent-initiated ones are documented as planned |
| Interactive buttons, carousels | no | yes |
| Branding | a plain Sender ID | logo, display name, description and brand color, rendered by the messaging app (AWS documents a verified badge on Android; this sample runs a testing agent, which shows none — see the Settings tab) |
| Delivery confirmation | carrier-level: the network acknowledges receipt, which doesn't prove the message reached the device | **device-level**: the handset itself reports back |
| Billing | on carrier acceptance | **only on confirmed delivery to the device** |
| Reach | 200+ countries, every handset | 22 countries; Android with RCS enabled, iPhone on iOS 18+ |
[[How RCS differs from SMS]](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-overview.html#rcs-overview-how-rcs-differs)

Device-level delivery receipts are a genuinely different signal from SMS's carrier acknowledgement —
and they're the basis for billing, so an RCS message that never reaches the
handset costs nothing, where an SMS accepted by the carrier and then dropped
still bills. That pairing (better evidence, and you only pay on the evidence) is
a strong argument for RCS.

Treat RCS as your primary channel and SMS as the fallback. RCS adds verified branding, rich content and
device-level delivery receipts, but it reaches a subset of your recipients. It is available in a growing list
of countries, so check [[Supported countries and regions]](https://docs.aws.amazon.com/end-user-messaging/latest/userguide/nx-supported-countries.html)
for the countries you send to, and within a supported country a message goes over RCS only when the recipient's
device and carrier support it. SMS is widely available (200+ countries, every handset), so adding an SMS
fallback is the recommended best practice. `SendTextMessage` already works for SMS, and you can treat
`SendRcsMessage` as a superset that adds the rich content types. Both send APIs can fall back to SMS, and
they are **not** the same mechanism:

- **Pool-based, automatic** — `SendTextMessage` through a **phone pool**
  containing both an RCS agent and SMS numbers. AWS tries RCS first and falls
  back to SMS automatically if delivery doesn't succeed within the TTL (~25 seconds),
  reusing the same message body. Number selection stays in configuration rather
  than in your code, which is why AWS recommends pools for all sending, not just
  RCS.
  [[RCS to SMS fallback]](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-sms-fallback.html)
- **Per-message, explicit** — `SendRcsMessage` with a `FallbackConfiguration`
  on the request. You choose the channel (`SMS` or `MMS`), write *separate*
  content for it, and name the origination identity — which must be a phone
  number or sender ID, never a pool or an agent. It triggers on immediate RCS
  failure **or** on TTL expiry, which makes it the natural partner to
  `TimeToLive`. You do need to be aware of the asymmetry between RCS and SMS: the fallback `MessageBody` of SMS caps at 1,600 characters where the RCS `TextMessage` body allows 3,072. A long RCS body
  has no automatic SMS equivalent. See [[Per-message SMS or MMS fallback]](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-fallback-per-message.html)

If you send `SendRcsMessage` directly to an agent with no `FallbackConfiguration`,
there is no safety net — the message either goes over RCS or it doesn't.
The AnyHealth sample sends directly to its RCS test agent (no pool) to show the RCS-native experience. The sample wires per-message fallback on the entry message of 13 of its 20 use case examples (§4 names the rest), off
unless you supply a fall-back SMS number at deploy time (see §4). A production system built on
this pattern should almost always sit behind a pool with SMS fallbacks.

The fallback bodies in this demo are hand-written per use case example rather than generated. A card's chips, images and map pins have no plain-text equivalent, so "degrade to SMS" is a content decision per message,
not a serialization problem: the handover use case example's fallback gives out a phone
number, because an SMS reply would never reach the dashboard operator; the
photo-submission use case points at the upload page, because inbound MMS is not
ingested here at all; the web store use case names three products, because a catalog
carousel has no shape in 1,600 characters. You'll probably want to hand write the SMS fallback messages you would have sent for RCS delivery failures.

## 2. The two-level identity model: agent vs. registration

Before any message can be sent, AWS End User Messaging needs to know who
you are. This is the part of RCS worth understanding before you start, because
there are two nested resources, not one:

- **AWS RCS Agent** — the top-level resource you create once. It's your
  brand's unified identity (`rcs-a1b2c3d4`), and it's where two-way
  messaging and keywords (`STOP`/`HELP`) are configured.
- **RCS for Business ID** — a per-*registration* identity underneath the
  agent. You configure a **testing agent** (via testing
  registration) and, later, one **country launch agent** per country in which you want to 
  go live. Brand assets — logo, banner, accent color, description — are
  attached to each registration, not to the top-level agent.
[[Managing RCS agents]](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-agents.html)

[[Testing RCS messages]](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-testing.html)

The AnyHealth demo app is designed to use an RCS test agent. The necessary testing registration
(`TEST_RCS_LAUNCH_REGISTRATION`) gives you the same API surface as
an RCS agent that has been launched in country(ies) in production. For example, with this demo app you'll use  `SendRcsMessage` to send rich cards to phones you've explicitly registered as
testers. Importantly (and conveniently), creating a RCS test agent in AWS End User Messaging does not require  carrier approval - so you can be up and running the AnyHealth demo app in literally minutes.

The `AGENTS.md` walks your AI coding assistant through the testing registration's 21 fields
(brand name, logo, accent color, contact info, etc.). The assistant uses the instructions in the repo to make your testing identity look and behave like a real one.

[[RCS billing and pricing model]](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-billing.html)

While you do not need carrier approval to create and use a RCS test agent with up to 10 verified devices, you're still billed the standard AWS End User Messaging RCS rates for test messages.

With RCS, you are charged **only for messages confirmed delivered to the device** — a failed RCS attempt costs
nothing, and if it falls back to SMS you only pay your SMS provider for the SMS that arrived, not for
the RCS that didn't. That's the opposite of SMS, where the charge lands when the
carrier accepts the message. But separately from per-message fees, launching an
agent carries carrier pass-through **registration fees** — a one-time setup fee,
an annual brand-vetting fee, and a monthly maintenance fee — and as of this writing (October 2026) those are
explicitly **excluded from Enterprise Discount Program discounts**. If you're
building a cost estimate for launching production RCS agent(s) in country(ies), consult the
[pricing page](https://aws.amazon.com/end-user-messaging/pricing/).
[[RCS billing and pricing model]](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-billing.html)

Two practical consequences of this model show up directly in the code:

- The stack's CDK deploy **does not create the RCS agent**. Setup handles that as a one-time step ([SETUP.md step 2](../SETUP.md#2-set-up-your-rcs-agent), or `AGENTS.md` when an AI coding assistant runs it) and drops the resulting agent ID into `.deploy/agent.json` for `cdk deploy` to
  read. Everything else — DynamoDB, S3, the Lambdas, the API — is one stack; the
  agent identity is deliberately outside it.
- A custom-resource Lambda in the stack (`eum_wiring.py`) calls
  `pinpoint-sms-voice-v2` directly at deploy time to create the **configuration
  set** and **event destination**, and to flip on two-way messaging and inbound
  media on your agent. Why a custom resource: this stack adopts the agent you
  registered instead of creating a new one (the `AWS::SMSVOICE::RcsAgent` type
  calls `CreateRcsAgent`), so the two-way settings are applied to your existing
  agent through the API. The configuration set and event destination are
  CloudFormation-manageable (`AWS::SMSVOICE::ConfigurationSet`, whose
  `EventDestinations` property covers the SNS destination); they live in the
  same custom resource so that one resource sets up and unwinds the whole
  wiring. On stack destroy it turns two-way messaging off and removes the event
  destination and the configuration set, unless another deployment has taken
  over the agent. See [Teardown in SETUP.md](../SETUP.md#teardown) for what
  stays on the agent.

  Two details worth exploring. First, **there are two independent event
  subscriptions and you need both, because they carry different things.** The
  configuration set's event destination carries *outbound status* events —
  delivered, read, TTL expiration, fallback. The agent's own two-way topic
  carries *inbound interaction* events — typing indicators and suggestion taps —
  and the docs are explicit that postbacks are delivered there **only**, never
  to a configuration set destination. So skip the first and you lose delivery
  receipts; skip the second and no button tap reaches your code. It also means
  they don't have to point at the same place: this demo aims both at one SNS
  topic to keep the adapter simple, but a configuration set can equally target
  Amazon Data Firehose or CloudWatch Logs.
  [[RCS message events]](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-events.html)

  Second, the event destination subscribes to `RCS_ALL` rather than `ALL`: the
  guide documents `RCS_ALL` as the way to subscribe to every RCS event type with
  one matching type instead of listing them individually, so it's the specific
  choice to make. And note the agent's `TwoWayRcsEventsEnabled` list is a
  separate setting again from either: left unset, the agent forwards nothing,
  and `DescribeRcsAgents` omits the field. On a testing agent, delivery events
  appear once the agent is launched in a country; until then your delivered
  count stays at zero while the `RCSMessagesDelivered` CloudWatch metric counts
  every delivery.

## 3. The message loop: one inbound path, everything converges

Every inbound event AWS End User Messaging can produce — a text reply, a
tapped button, a shared location, a photo, or a delivery/read status update
— arrives the same way: two-way messaging is disabled on an agent by
default, and once you enable it, inbound events land on an **SNS topic**
you configure.
[[Receiving inbound RCS messages]](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-inbound.html)

The AnyHealth demo app subscribes a single Lambda — the **Channel Adapter** — to that
topic. Every use case example, AI or deterministic, customer/member-facing or internal staff-facing,
runs through this one function. That's a deliberate design choice: it means
there's exactly one place where "log this turn to the transcript" happens,
so the dashboard's conversation history won't miss an event or record
the same one twice, no matter which flow is active.

Inside the adapter, routing happens in priority order:

1. **Status events short-circuit.** Anything carrying an `eventType` gets
   logged as a transcript event and nothing else runs — that's what powers the
   per-recipient counts in the dashboard. Discriminate on the *presence* of
   `eventType` rather than on an allow-list of names: the RCS set is
   `RCS_QUEUED`, `RCS_SENT`, `RCS_DELIVERED`, `RCS_READ`, `RCS_FAILED`,
   `RCS_TTL_EXPIRED`, `RCS_PROTECT_BLOCKED` and `RCS_FALLEN_BACK_TO_SMS`, it
   grows, and a name this code doesn't recognize must not fall through and be
   logged as inbound chat text from the member.
2. **Typed text is screened before anything can swallow it.** Four checks
   run on free text ahead of the live-agent gate, any sticky flow, the keyword
   router and the AI:
   - *Emergency language* — a short, reviewed list such as "chest pain",
     "can't breathe", "overdose", self-harm phrases, "I think I'm dying" or a
     bare "911", matched as whole words — gets one fixed reply (call 911; call
     or text 988) with a Call Member Services chip and Main Menu, in every
     mode, including live. The 911 and 988 numbers are US numbers kept in one
     constant block in `channel_adapter.py`; change them if you deploy outside
     the US. This is a safety net for common phrasings, not a triage or
     classification system. REMEMBER - THIS IS A DEMO APP AND NOT INTENDED FOR PRODUCTION USE.
   - *Service keywords* — `STOP` and `HELP` are configured out of the box, `UNSTOP` is configured by the deployment. The built-in `STOP` and `HELP` arrive with no
     `messageKeyword`, and a keyword you register arrives with one. So the
     adapter recognizes the built-ins by their text and acts on `messageKeyword`
     only when the text begins with it. For either it sends nothing, makes
     no model call, claims no account action, and records a `KEYWORD_*` marker.
   - *The opt-out list* — the service also enforces the opt-out: after `stop`,
     every send to that number will be refused with
     `DESTINATION_PHONE_NUMBER_OPTED_OUT`. So before the adapter answers
     anyone, it asks the service whether the sender is on the Default opt-out
     list (`DescribeOptedOutNumbers`), remembers the answer for 30 seconds,
     and fails open: a lookup that errors or is throttled counts as "not opted
     out", so a failed lookup won't silence a member. A sender who is
     opted out gets no reply and no model call from the adapter, only an
     `OPTED_OUT_SKIPPED` marker in the transcript, so `stop` followed by
     chatter costs nothing. Button taps and shared locations get the same
     check, and media gets it too, with one difference: only the reply is
     skipped. A photo is still converted and classified by `media_convert`,
     because the S3 upload starts that Lambda and it has no opt-out check (up
     to three vision calls). The adapter keeps no list of its own, which is
     why an admin's `delete-opted-out-number` (or an `OPT_IN` keyword) brings
     the member back within 30 seconds; a production sender should still keep
     its own record, as AWS's RCS best practices advise. A member can opt back
     in by text only if an `OPT_IN` keyword such as `UNSTOP` is registered.
     `cdk deploy` registers `UNSTOP` and real `HELP` and `STOP` replies, built
     from `content/brand.md`, in place of the service's default replies
     ("Default Help Message", "Default Stop Message"). It never overwrites a
     reply you set yourself, `-c registerKeywords=false` skips it, and the
     `KeywordsStatus` output reports the result. `AGENTS.md` ("Register the
     keyword replies") has the rules and the `put-keyword` commands for other
     wording; the full account is in
     [architecture §2.1](architecture.md#21-keywords-and-where-a-keyword-is-answered).
   - *Escape words* — exactly `menu`, `main menu`, `home` or `start over`
     clears the active flow, leaves live mode and sends the welcome; exactly
     `human`, `agent`, `representative`, or a short phrase like "talk to a
     person", starts a handover. They work from any flow, and they match the
     whole message, so a sentence that merely contains one of those words is
     left to the router.
3. **Live-agent mode gates the bot.** If a human has taken over the
   conversation (see §5), the bot goes silent — except a member can always
   tap "Back to Assistant" (or type `menu`) to escape, and an inbound photo
   still gets a one-line receipt so it isn't left hanging.
4. **The inbound turn is classified**: a tapped-button postback, a typed
   free-text message, or media (inbound media arrives as a JSON envelope inside
   `messageBody`; this sample detects it by its `mediaStatus` field).
5. **Postbacks resolve by a fallback ladder**: handover → main menu → the
   currently active flow → a *prefix* match across every flow's postback
   namespace (`rx_*`, `appt_*`, `store_*`, …) → the AI assistant. That
   prefix step matters more than it looks: flow state expires after 30
   minutes, but a button a member taps after that window should still work,
   and the prefix alone is enough to identify which flow it belongs to.
6. **Free text falls through a small keyword router** (human/agent, refill,
   appointment, store, verify, find) before landing on the Benefits Q&A
   assistant as a default. The router matches whole words, so "order" does not
   fire inside "disorder" or "person" inside "personal". There is deliberately
   no "sorry, I didn't understand that" dead end. Ahead of that router sits one
   keyword that re-opens the welcome message — the body an inbound deep link
   pre-populates, so scanning the QR code on the Recipients tab starts the
   demo from the member's side. Note that this is a keyword *your code*
   handles: a keyword registered with `put-keyword` is answered by the service
   with a fixed string, so it can't be a carousel, and the adapter treats the
   message as already answered, so the member would never see the welcome. Keep
   `put-keyword` for `STOP`/`HELP`, where a reply must go out even if your
   function is broken. The deploy registers real text for those two, plus an
   `OPT_IN` keyword (`UNSTOP`) so a member who texted `stop` can come back (see
   the opt-out list bullet above); `AGENTS.md` has the `put-keyword` commands if
   you want other wording.

Every outbound message — deterministic, AI-generated, or typed by an operator —
goes out through one `common.send_rcs` function, the one place the Lambdas call
`SendRcsMessage`. The flows' replies reach it through a `_send()` helper in the
adapter, which also logs the outbound turn, applies the per-message TTL and
fallback body a flow may set, and pauses a second between messages in a
multi-message reply so they arrive in the order you intended. AI replies and
operator replies call `common.send_rcs` directly and carry neither.

## 4. Rich content: cards, carousels, and suggestions

`SendRcsMessage` is the API that unlocks everything beyond plain text. Its
`RcsMessageContent` carries **exactly one** of four content types — you cannot
combine them in a single request:

| Content type | What it is | Limit worth remembering |
|---|---|---|
| `TextMessage` | a text body, but with suggestions attached and delivered as one message rather than SMS segments | 3,072 characters |
| `FileMessage` | a single image, video, audio file or **PDF**, by HTTPS or S3 URL | 100 MB (video: 5 MB) |
| `RichCard` | media + title + description + up to 4 suggestions | title 200 chars, description 2,000 |
| `Carousel` | a swipeable set of cards, each with its own media, text and suggestions | **2 to 10 cards** — one card is a validation error, and so is an eleventh |

[[Content types]](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-rich-messaging.html#rcs-rich-messaging-content-types)

All four are in this project. `FileMessage` is the one that is easy to skip, so
it has a deliberate home: `Rx Documents` on the Rx refill flow sends a real PDF
(`lambda/flows/pharmacy.py`) with fictitious data. Because the union is exclusive, that reply is *two*
messages — the file cannot carry a caption, so the sentence explaining it is its
own text message. The file is referenced by `s3://` URI and End User Messaging
rehosts it, so the bucket stays private.

That rehosting is worth pausing on, because it decides what you are allowed to
send this way. AWS downloads the object from your bucket and presigns it for the
aggregator, so the bytes leave your account and travel the RCS/carrier network
with Google RCS for Business in the delivery chain. The PDF on that path is
therefore *Magic Medicine Facts* — generic (fake) drug information, the same file for
every member. The member's own prescription record, with their name, address,
prescriber and directions on it, is not sent as a message at all: the same reply
carries a `WEBVIEW` suggestion that opens a page which fetches it from S3 over
HTTPS through a short-lived presigned URL. **Match the transport to the
sensitivity of the document** — see *Rx Documents* in
[architecture.md](architecture.md) for the mechanics, including which S3 grants
cover each prefix and what was observed when a send naming the secure document
was tried.

On top of the content sit **suggestions** — six types: `Reply` chips,
`DialPhone`, `ShowLocation`, `RequestLocation`, `CreateCalendarEvent`, and
`OpenUrl`. Every one of them takes a `Text` label (25 characters) and
`PostbackData` (2,048).
[[Configuring RCS suggestions]](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-suggestions.html)

Suggestions come at two levels, and the difference is not just the limit:

- **Card-level** — up to **4** per rich card or per carousel card, in
  `CardContent.Suggestions`. These are part of the card, so they stay in the
  thread with it as the conversation scrolls on.
- **Message-level** — up to **11**, in the top-level `Suggestions` array
  alongside `Content`. These render as a chip list below the whole message.
  Treat them as attached to the *latest* message: on a handset they go away
  once the recipient taps one or sends anything else.

So message-level is the right place for navigation that only matters right now
("Main Menu", "Done browsing"), and card-level is the right place for an action
the member may come back to. Designing around it the other way — collapsing a
carousel's per-card buttons into one message-level chip list to stay under a
limit — quietly turns durable buttons into ones that vanish on the member's
first reply.

`RequestLocation` is the only suggestion that asks the member for data rather
than giving them an action, and it is worth trying on a handset: the reply is a
separate inbound message carrying latitude and longitude — no street address,
no place name — and the member is free to ignore it. Find Care offers the chip
whenever it does not know where the member is, and `handle_location` in
`lambda/channel_adapter.py` feeds the coordinates back into the same Bedrock
conversation. Round them before you log them; they may be precise enough to
identify a home, for example. Every action chip the AI builds (this one, and the Call Member
Services dial chip) carries an id the adapter reserves and ignores when the tap
is reported back, whatever id the model wrote; the rule is in
[architecture §2](architecture.md#2-inbound-routing).

`OpenUrl` is the mechanism behind the feature AWS documents as **Webviews**: set `Application` to `WEBVIEW` and give it a `WebviewViewMode` of `FULL`, `HALF` or `TALL`, and the URL opens in a modal
browser *on top of the conversation* instead of redirecting the user into
their device's default browser. The `Url` must be `https://` — an `s3://` URL is
rejected. This capability is for "sessions and content that should not be
transmitted over messaging channels, like account details", which is exactly
the argument §6 makes about photos of insurance cards. Every webview in this
demo uses it, and the mode tracks what the page is for: `HALF` for a panel that
answers one question (Rx details, clock-in confirmation), `TALL` for a page the
member has to work in (the upload form, the schedule, a shift swap), and `FULL`
for a page that wants the whole screen — the prescription record in §6, which is
a document the member sits and reads, and the video visit in §7, which is a call.
[[OpenUrl]](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-suggestions.html#rcs-suggestions-openurl)

`SendTextMessage` still exists and still works for plain text — it's simpler,
it's the same API you may already use for AWS End User Messaging SMS, and it's the only one that gets
*automatic* pool-based channel selection. What it can't do is carry any of the
rich content above, set a TTL, or take a per-message fallback. The 
capability-by-capability comparison of the two is here - 
[[Choosing between SendTextMessage and SendRcsMessage]](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-rich-messaging.html#rcs-rich-messaging-choosing)

AnyHealth's welcome cards, the Rx refill card, and the wellness-store
catalog are all direct demonstrations of this API surface. The `Reply`
suggestion carries a `PostbackData` string your code defines — AWS's guidance
is to put a structured identifier in there so your Lambda can route the
response without a database lookup, and that's exactly the `rx_refill_now` /
`store_add_{id}` / `swap_offer_{shift}_{coworker}` convention every flow in
`lambda/flows/` follows.

One header parameter is worth calling out on its own: **`TimeToLive`**. Set
it on a `SendRcsMessage` call and AWS withdraws the message if it hasn't been
delivered within that window (1 second to 48 hours) — the recipient simply
never sees a stale one.
[[Configuring RCS message expiration]](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-message-expiration.html)
The **Verification Code** use case example makes this concrete: the code
stays valid for five minutes, but RCS is given a 60-second TTL to deliver it, so
a code that can't be delivered promptly disappears instead of arriving
already-expired and confusing the member. Keep those two windows as separate
numbers — because TTL expiry is what triggers SMS fallback, a delivery window as
long as the validity window would fall back at the moment the code died.

TTL has two consequences worth knowing. First, expiry is *observable*, as
exactly one event: **`RCS_TTL_EXPIRED`**. The event means no delivery
confirmation arrived before the TTL elapsed, which is not proof that the handset
never received the message, so make any replacement message safe to receive
twice. (The one-liner that reads the `EventType` values from the service model
is in `lambda/common.py` above `_EVENT_EXPLANATIONS`.) Second, TTL is the
documented trigger for per-message fallback, which is why the pairing "short TTL
+ SMS fallback" is the canonical OTP pattern: try RCS for 30–60 seconds, then
send the code as SMS instead of leaving the member with nothing. This demo wires that on the verification use case example — and a fallback body on other use cases (all but the two AI assistants, the clinic-initiated
reschedule, Video Visit, and the three diagnostics / experiments; Video Visit
has none on purpose, because a one-visit join link is a poor fit for a text
message) — but leaves it **off unless you deploy with
`-c smsFallbackNumber=+1…`**, because a fallback needs an SMS-capable
origination identity the stack can't provision for you. While it is off, no
`FallbackConfiguration` is attached at all, so `RCS_FALLEN_BACK_TO_SMS` never
fires; the Settings tab tells you which state you are in, and the adapter logs
`RCS FALLBACK SKIPPED` per send rather than dropping the request silently.
[[Per-message SMS or MMS fallback]](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-fallback-per-message.html)

## 5. Live-agent handover

RCS's two-way channel is symmetric — nothing stops a human from typing the
replies instead of a bot. AnyHealth's **Conversations** tab uses that: a
member can ask for a human at any point, which flips a `STATE` flag in
DynamoDB to `LIVE` and silences the bot for that conversation. From then on,
an operator's typed reply on the dashboard makes an authenticated call to
`POST /api/reply`, which asynchronously invokes the *same* Channel Adapter
Lambda that every bot reply goes through — so a human's message is built,
sent, and logged by identical code, and shows up in the same transcript with
no separate "human message" code path to keep in sync. Tapping "Back to
Assistant" flips `STATE` back and hands control to the bot again. Typing
`menu` does the same and sends the welcome. Apart from that, the only typed
message the bot still answers on a live thread is emergency wording: the fixed
911/988 reply goes out, labeled "Automatic safety reply" in the transcript, so
the operator can see what the member was told and follow up.

**The typing indicator from §1's table is an inbound signal.** They arrive
the same way suggestion taps and shared locations do (§3): as a JSON envelope in
`messageBody` on the two-way SNS topic, here with `type: RCS_TYPING`. The
adapter treats it as presence rather than as history — it writes a single row
under a fixed `SYSTEM` partition keyed `TYPING#{hash}`, with a 5-minute TTL,
which the next inbound message from that member deletes. A DynamoDB TTL only
deletes *approximately* on time, so the reader also ignores anything older than
12 seconds; the operator console polls `GET /api/typing` every 4 seconds and
renders "Alex is typing" with three drifting dots in the status bar. The route
returns conversation hashes and timestamps, never a number — the console already
holds the recipient list, so it does the name lookup itself.

## 6. Carrier or webview: choosing a transport for files

RCS agents can receive inbound media. When they do, AWS End User Messaging
downloads the file from the carrier network, uploads it to an S3 bucket you
configure, and publishes the location and metadata to your two-way SNS
topic — the same topic everything else in §3 flows through.
[[Receiving inbound RCS media]](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-inbound-media.html)

AnyHealth deliberately ships **two** photo-intake use case examples to make
a security trade-off visible side by side:

- **"Classify a Photo"** — the member just sends a picture in the thread using the native messaging app. This is the simple, intuitive pattern for non-confidential images.
  However, when using this method, the image's bytes physically transit the carrier/RBM network on the way
  to AWS — outside AWS's control, and outside the scope of an AWS HIPAA
  Business Associate Addendum. This use case example is scoped to a generic,
  non-sensitive photo upload for exactly that reason. A prescription-label
  photo is not indicated for this method, as they routinely carry PII/PHI.
- **"Secure Document Upload"** — the member instead taps an `OpenUrl`
  suggestion that opens a webview *inside* the RCS thread. That page asks
  AnyHealth's API for a short-lived, presigned S3 `PUT` URL, and the
  browser uploads the file **directly to S3** — the bytes never transit
  RCS. This is the pattern to reach for whenever the
  content might be PII-shaped, PHI-shaped, or confidential.

Both paths converge on one **Media Convert** Lambda, triggered by an S3
`ObjectCreated` event on either prefix. It normalizes HEIC/HEIF/JPEG/PNG into
a browser-displayable JPEG, corrects orientation (a JPEG, PNG or GIF with no
EXIF orientation, which is common for iOS in-app browser uploads, falls back to
asking Bedrock whether the image is upside down, and is turned 180 degrees only
when a second look agrees; HEIF is excluded and quarter turns are never
applied), and asks Bedrock for a one-sentence description
under an explicit instruction never to transcribe names, numbers, IDs, or
medical detail. For the native path, conversion finishes *after* the adapter
has already logged the raw inbound message, so Media Convert calls the
adapter back once it's done, rather than the adapter waiting synchronously.

**And the same decision applies on the way out.** It is easy to think of this
as an intake question, but a document *you* send faces it too, for the reason
in §4: `FileMessage` takes an `s3://` URI, and End User Messaging downloads that
object, rehosts it and presigns it for the aggregator — so those bytes leave your
account and cross the same carrier network. So the Rx refill flow's **Rx
Documents** reply sends *Magic Medicine Facts*, a generic fact sheet identical
for every member, as a file message, and offers the member's own prescription
record — name, address, prescriber, directions — through a `WEBVIEW` suggestion
that fetches it from private S3 over HTTPS with a 300-second presigned URL
instead. In this repo the two documents even live under different S3 prefixes.
Neither the bucket policy for the RCS service principal (`media/` and the
inbound prefixes) nor the channel adapter's role covers the second one's prefix.

The same argument runs in the other direction. Everything above is about a
document coming *in*; the **Loan Agreement** use case example sends one *out* to
be read and signed. It is a `Review & Sign` `OpenUrl` (`WEBVIEW`, `TALL`) to
`/webview/loan-agreement`, a self-contained three-page installment-loan
agreement the member initials on each page and signs by finger or mouse; on
submit it shows a signing receipt with a SHA-256 fingerprint of the document
text. Because the whole thing lives in the webview, the agreement and the
signature never travel through the RCS/carrier network — only the link does,
exactly as with the upload page. The token in that link is a demo gate, not a
signed session, so it carries the same "not authentication" caveat below.

Choosing the transport keeps sensitive bytes off the carrier network. 

The README is explicit that AnyHealth is not a
HIPAA-compliant system, and that adapting any of these paths to handle real PHI
requires a BAA, encryption, audit logging, and access controls beyond what a demo
provides. Importantly, the demo's webview pages have no member sign-in functions, and the conversation hash in their URLs is an unsalted hash of the phone number. Appropriate for a demo, but NOT for a production system.

## 7. A webview is a browser: the video visit (experimental)

Everything in §6 treats the webview as a place to put a form or a document. It is
a browser window, though, and an interesting question is how far that goes? The
**Video Visit** use case is an experiment - can a WebRTC video
call run *inside* the in-conversation webview, with no app to install and without
throwing the member out of the thread?

AWS documents `Application` and `WebviewViewMode` on `OpenUrl`. Camera and
microphone access is granted by the messaging app that renders the webview, not
by RCS, so this use case example is built as an experiment rather than a claim.
The invitation card carries two chips on purpose:

| Chip | `OpenUrl` | What it tells you |
|---|---|---|
| **Join video visit** | `Application: WEBVIEW`, `WebviewViewMode: FULL` | whether the in-conversation webview will give up the camera |
| **Open in browser** | no `Application` field (the documented default) | the control — permission prompts certainly work in the device browser |

If the first chip fails and the second works, the webview is what blocked you,
and the member still completes the call. That is also the shape a production
design would ship: stay in the conversation when you can, fall out to the browser
when the handset will not cooperate.

**The result so far: iOS grants both.** On iOS 18 the in-conversation webview
prompts for camera and microphone and the call connects. Android also worked, but the wider range of devices, OS and messaging app versions makes the capability more difficult to verify. For these reasons, this use case example is labelled experimental.

The video call itself (when it works!) is via the **Amazon Chime SDK for JavaScript**. The demo creates one meeting with two participants: the member in `lambda/webviews/video-visit.html` on their verified device, and the clinician in a modal in the operator dashboard. Four design points of this demo are a consequence of  demo's  webview having no way to authenticate:

- **A visit token is minted when the card is sent; the Chime meeting is created
  lazily on the first join.** An invitation nobody opens costs nothing. The token
  is a 122-bit `uuid4`, lives in DynamoDB, and expires in 30 minutes.
- **`/api/video/join`, `ping`, `status` and `end` are open on purpose, for the
  same reason `/api/uploads/presign` is** — a member's in-app browser session
  calls them and has no API key to offer
  ([Open routes](../SECURITY.md#open-routes)). The controls are therefore the token itself, its expiry, and a per-visit
  cap on how many times it can be exchanged for join material, since every Chime
  attendee is billed per minute.
- **Each side declares a role (`member` or `clinician`), and the role decides who
  can end the visit for everybody.** The clinician leaving ends it; the member
  leaving only ends it if the clinician is not there. This is not a permission
  model — the role comes from an unauthenticated caller — it exists so that the
  two clients' lifecycles do not fight. Specifically: in an iOS webview
  `pagehide` fires when the page is merely *backgrounded*, so "the member glanced
  at another app" must not tear down the clinician's call.
- **Presence comes from heartbeats, not from Chime.** Each side pings every ~15
  seconds and the dashboard polls for it, which is how the clinician's modal can
  say *"the patient is waiting"* **before** the clinician has joined — at which
  point there is no local meeting session to ask.

The Amazon Chime SDK is vendored into the repo and served from your own deployment
(`scripts/vendor-chime-sdk.mjs` → `lambda/webviews/chime-sdk.js`), not pulled
from a CDN. A page that asks for the camera should not let a third party run code
in it, and a demo should not break when a CDN is unreachable.

Two notes about Amazon Chime SDK Meetings. First, the Chime SDK is **not
available in every Region**, and the media Region is a separate choice from the
control-plane Region; both default to your deploy Region and are overridable.
Second, a live meeting bills attendee-minutes, this usage billing is different from RCS's per message sent billing model.

Two further experiments push the same question — what can you do in a RCS webview? In these experimental use cases, the webview hosts a (simulated) live **Amazon IVS** (Interactive Video
Service) app. 

One "mystery box" experimental use case opens the hosted IVS iCasino demo
(`https://icasino.ivsdemos.com/`), the other the IVS Interactive Fitness demo
(`https://fitness.ivsdemos.com/`). Two things make them different from the video
visit. First, an RCS card cannot *embed* a live page — card media is a static
image or video — so a `WEBVIEW` `OpenUrl` opening the site is the closest thing,
and it opens the URL as a *top-level* document rather than in an iframe. Second,
because it is top-level, a site's `X-Frame-Options` never applies: iCasino sends
`SAMEORIGIN` and would refuse to be framed, but opening it top-level sidesteps
that. Each still pairs the webview chip with a device-browser control, the same
A/B as the video visit. The two live in Settings → Diagnostics & experiments and,
playfully, as "Mystery Box" cards in the Use Case Examples list — a blank card
whose only affordance is a "." that opens a modal revealing what it is.

Architecture and the full lifecycle: §4.14 (video visit) and §4.15 (the IVS
experiments) of [architecture.md](architecture.md).

## 8. Everything else, briefly

A few more pieces round out the picture, covered in depth in
[architecture.md](architecture.md):

- **State** lives in one DynamoDB table, partitioned by a *hashed* phone
  number rather than the raw MSISDN, so the conversation, cart, flow and shift
  items carry no subscriber identity. Two caveats worth being precise about:
  the `TESTER#{hash}` / `PROFILE` record does store the operator-entered E.164
  number as a plain attribute, because the Recipients tab has to display it —
  which is why `/api/testers*` sits behind the API key. And the hash is an
  unsalted SHA-256 of a phone number, which is a small enough keyspace to
  reverse by brute force, so treat it as a way of keeping raw numbers out of
  keys and logs, **not** as de-identification. Conversation history expires
  after 30 days; active-flow state after 30 minutes.
- **The dashboard never sends RCS directly.** Every route that sends a
  message, edits or resets data, or returns recipient or account details
  requires an `x-api-key`, checked by a Lambda authorizer against a Secrets
  Manager secret. A small set of routes is open on purpose, such as static demo
  metadata and the routes a handset's in-app browser calls with no key to offer.
  [SECURITY.md](../SECURITY.md#routes-that-need-the-api-key) lists the gated
  routes and [Open routes](../SECURITY.md#open-routes) lists the rest. This is
  deliberately a lightweight control appropriate for a demo, not a real identity
  provider.
- **Thirteen member-facing use case examples and seven internal ones** run on
  the exact same channel and the exact same Channel Adapter — RCS doesn't care
  whether the "customer" on the other end is a patient or an employee. Four of
  the internal ones are staff self-service (Clock In/Out, My Schedule, PTO
  Request, Shift Swap); the other three are operator tooling that lives in the
  dashboard's Settings tab under **Diagnostics & experiments** — a Camera & Mic
  Probe and two IVS webview experiments (below) — rather than in the Interactive
  Demos list.
- **One status bar, on every tab.** The facts an operator needs mid-demo don't
  stop being true when they switch tabs, so they live in a strip at the top of
  all of them: whether the targeted device can receive at all (a lamp first,
  because that is what explains a demo that does nothing), which recipient is
  targeted, who is typing, the last error any view raised, whether the bot or a
  human is answering, and — far right — `fe:1.0.0.42 | be:1.0.0.57`. Those two
  are the build of the console in the browser and the build of the stack it is
  talking to: the first three segments are hand-maintained in `version.json`,
  and the fourth is the number of commits that have touched that half of the
  tree, so it advances on its own (`scripts/version.mjs`, called both by
  `web/vite.config.ts` and by the CDK stack). `+dev` means that half had
  uncommitted changes when it was built, `+nogit` that there was no history to
  count, and `be:?` that the version call itself failed — the API URL is wrong,
  or the stack isn't reachable. A commit that only touches `docs/` moves
  neither number, which is the point: the string is there to answer "is this
  browser running the same code as the Lambdas I deployed?"
- **Nothing about the healthcare theme is structural.** Four Markdown files
  under `content/` supply the brand identity, the knowledge the AI
  assistants are grounded on, the store catalog, and the staff-facing data.
  Edit them and redeploy, and the same infrastructure demonstrates a
  different brand in the cards, webviews, and dashboard. The registered agent
  identity (logo, banner, display name) is separate: the stack has no
  registration resource, so a content change does not reach it; it stays as
  registered during agent setup. Some registered brand assets cannot be changed
  after the registration is submitted, and updates to others are reviewed (see
  [Managing RCS agents](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-agents.html)). A
  `brandName` change that alters its slug also changes the stack name, so on an
  existing deployment `cdk destroy` first rather than redeploying (see
  [Editing the demo](../README.md#editing-the-demo)).

## 9. Where to go next

- Run it yourself: [README.md](../README.md) — quick start, clean up, cost.
- Full diagrams and a flow chart for all twenty use case examples:
  [architecture.md](architecture.md).
- Set up your own RCS agent: [SETUP.md](../SETUP.md#2-set-up-your-rcs-agent).
- AWS's own RCS documentation, starting point:
  [Getting started with RCS](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-getting-started.html).
