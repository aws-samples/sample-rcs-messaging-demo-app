# Keeping this sample's RCS content current

AWS End User Messaging adds RCS capabilities over time, so check the limits and
capabilities this project documents against the AWS user guide periodically.
This page is that procedure — short, human-paced, and not an automated job.

## The durable principle

Every RCS limit and AWS doc link that the code or the dashboard uses lives in
`content/rcs-features.json`. Everything that needs one reads it from there:

- `lambda/common.py` exposes it through `rcs_registry()` and `rcs_limit()`, so
  validation limits come from the registry.
- `lambda/dashboard_handler.py` resolves the `VIGNETTES[*].features` keys
  against it.
- The dashboard's Instructions tab reads it over `GET /api/vignettes/features`,
  and the feature tags on the Interactive Demos cards get the resolved entries
  from `GET /api/vignettes`.
- `cdk/lib/config.ts` bundles the file into every Lambda at synth and hard-fails
  the build if it is missing.

Read every limit with `rcs_limit()`. `scripts/check-rcs-registry.py` fails if a
distinctive limit value (1,000 or more, other than 2,000) appears as a literal in
`lambda/`. Small limits such as 4, 10, 11 or 25 are too common to scan for, so for
those the rule is a convention. The narrative docs (`docs/tutorial.md`,
`docs/architecture.md`) repeat some numbers and links in prose, so check them by
hand during the same read.

## The one check that runs

A single offline check keeps the registry wired to the code. It needs no
network access and no AWS credentials:

```bash
python3 scripts/check-rcs-registry.py
```

It verifies that every use case example's feature key exists, every `limitRefs` names a
real limit, every entry carries its required fields, every vignette's `brand` is
a brand defined in `content/brand.md`'s catalog, every brand has a usable
`homeMenu` (one to ten tiles, labels within the chip limit, postbacks the
channel adapter routes) and the adapter still handles the `reset_conversation`
Start Over postback, nothing hardcodes a documented
limit or a brand display-name literal in `lambda/`, and no `surfaces` claim has
gone stale. It also keeps each brand to its own content: a brand's `vignettes`
list equals the catalog entries tagged with that brand, every listed id is a
flow or an AI assistant, `defaultVignette` is empty or an AI assistant the brand
lists, the four member fields are set in the brand's own block and name no other
brand, no grounding file names another brand, and every `homeMenu` tile opens a
vignette the brand owns. It also checks the brands' registration fields and
contact pairs, the fictional phone-number range, `accentColor` contrast, the
room photo files, that every native-action chip is in `ACTION_ONLY_POSTBACKS`,
and the reserved AI chip ids. A run that would check nothing is treated as a failure.

Then the ordinary build verification:

```bash
python3 -m py_compile lambda/*.py lambda/flows/*.py
(cd web && npm run typecheck)
node --test 'scripts/test/*.test.mjs'
(cd cdk && npx cdk synth --quiet -c brand=<id> -c rcsAgentId=rcs-00000000000000000000000000000000 -c region=us-east-1 -c skipAgentCheck=true)
```

## Keeping the facts current (a periodic human read)

This is deliberately **not** a scheduled job, and nothing compares the registry
with the AWS user guide automatically: the offline check above only compares the
registry with this sample's code. The read described here is the only check on
the values themselves. Every so often — or whenever you hear RCS gained a
capability — read the AWS user guide against the registry.

The doc base is `content/rcs-features.json`'s `docBaseUrl`
(`https://docs.aws.amazon.com/sms-voice/latest/userguide/`), and each limit and
feature carries a `doc` path relative to it. Open the pages the registry cites
and compare.

- **A changed limit** is a one-line edit: update the `value` in the matching
  `limits` entry.
- **A new capability** is a new feature entry with `status: "not-demonstrated"`
  and a `statusNote` saying what a builder should do instead. The Instructions
  tab lists it with no code change.
- **When you finish the read**, set `reviewedOn` at the top of the file to that
  day's date (`YYYY-MM-DD`), even if nothing needed to change. The Instructions
  tab shows it beside the limits, so a reader can tell how current they are, and
  the registry check fails if it is missing, malformed or in the future. Nothing
  fails when it gets old, so the date is only as current as the last person who
  read the guide.

### What a limit entry holds

Each entry under `limits` has four required fields, and the registry check fails
without them:

| Field | Meaning |
|---|---|
| `value` | The number, as an integer |
| `label` | The name shown on the Instructions tab |
| `unit` | `characters`, `cards`, `seconds` and so on |
| `doc` | The user guide page, and anchor, the number comes from, relative to `docBaseUrl` |

`note` is optional text shown beside the number. Nothing reads any other field.

## Where content lives

| Change | Edit |
|---|---|
| A documented limit changed | `content/rcs-features.json` → `limits` |
| You finished a read of the user guide | `content/rcs-features.json` → `reviewedOn` |
| A feature explanation, caveat (the `gotcha` field) or doc link | `content/rcs-features.json` → `features` |
| Which features a use case example claims | `lambda/dashboard_handler.py` → `VIGNETTES[*].features` (keys into the registry) |
| Which brand a use case example belongs to | `lambda/dashboard_handler.py` → `VIGNETTES[*].brand` (a brand id defined in `content/brand.md`; the dashboard shows only the selected brand's vignettes), and the same id in `content/brand.md` → `brands.<id>.vignettes`, which decides what the phone opens; the check fails if the two differ |
| A brand's home-menu tiles (the chips a Start Over lands on) | `content/brand.md` → `brands.<id>.homeMenu` |
| Narrative explanation of *why* | `docs/tutorial.md`, `docs/architecture.md` |
| Operator-facing dashboard copy | `web/src/views/Guide.tsx`, `web/src/components/FeatureTag.tsx`, `web/src/components/PiiGuidanceTooltip.tsx` |

Adding a feature to the registry needs no React or Python change: give it a
`key`, wire that key into a use case example's `features` (or give it `surfaces`,
for something like delivery receipts that shows up on the Recipients tab rather
than on a card — see
[`surfaces`](#surfaces--for-features-no-use-case-example-claims) for the shape),
and the dashboard renders it.

## Adding a new feature entry

```jsonc
{
  "key": "message_feedback",           // referenced from VIGNETTES[*].features
  "name": "Message feedback",          // shown as the tag label
  "kind": "rcs-api",                   // rcs-api | demo-pattern | caveat
  "blurb": "One or two sentences a builder can act on.",
  "gotcha": "A caveat the builder should know about before using the feature. Optional.",
  "apiShape": "OpenUrl.Application = WEBVIEW; OpenUrl.WebviewViewMode = FULL | HALF | TALL",
                                       // the request fields involved, shown as code in the
                                       // feature's popover. Optional; free text, never checked
  "limitRefs": ["postbackDataChars"],  // keys from `limits`
  "doc": "rcs-rich-messaging.html#rcs-rich-messaging-api",
  "status": "not-demonstrated",        // demonstrated | not-demonstrated | planned-by-aws
  "statusNote": "Required unless status is demonstrated: say what to do instead."
}
```

### `surfaces` — for features no use case example claims

A feature no use case example claims must account for itself: either its `status`
says the demo does not show it, or `surfaces` names where in the demo it does.
Delivery receipts show up on the Recipients tab, not on a use case example card, so
`surfaces` exists to let such a feature still be marked `demonstrated`. Each
entry has to be checkable, not prose:

```jsonc
"surfaces": [
  {"where": "Recipients tab — Delivered column",           // human-readable
   "file": "web/src/views/Recipients.tsx",                 // must exist
   "evidence": "label=\"Delivered\""}                      // must be in that file
]
```

The registry check fails if the file is gone or the `evidence` string is no
longer in it. This is not cosmetic: `surfaces` was free text until
`verified_identity` was found sitting marked `demonstrated` while claiming a
surface — "Your handset — the agent header on every message" — that was true of
RCS but no part of this demo. Any non-empty string passed, so the one escape
hatch in the check could never fail. Pick `evidence` that would actually change
if the surface were removed: a heading string, a column label, a function name.
A `file` outside `web/src` is fine when the surface is a code path rather than a
screen.

## CI

`.github/workflows/rcs-content-checks.yml` runs on every push and pull request.
The `registry` job runs the registry check, which needs no network access and no
AWS credentials. The other jobs run the offline script tests, typecheck the CDK
app and the dashboard, and run `cdk synth` for every catalog brand with a
placeholder agent id and `-c skipAgentCheck=true`; those need the network for
npm and pip, and none uses AWS credentials. No job checks the limit values or
doc links against AWS: that is the human read described above.
