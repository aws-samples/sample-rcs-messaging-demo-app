# AWS End User Messaging RCS Demo Catalog: instructions for AI coding assistants

This demo ships a **catalog of independent, fictitious brands** covering various
industries and use cases, which demonstrate AWS End User Messaging Rich Communication
Services (RCS) messaging. This version includes **AnyHealth** (healthcare), **AnyTravel**
(travel and hospitality), **AnyWealth** (financial services), **AnyHR** (HR and workforce
self-service) and **AnyBuild** (residential construction). The `brands:` keys in
`content/brand.md` are the authoritative list. The brands are independent siblings:
none is a parent or umbrella over the others. The user deploys **one or more** of them;
each brand is its own stack with its own RCS agent. This file is the playbook for an AI
coding assistant (Kiro, Cursor, OpenAI Codex, Claude Code) that sets up the
demo for a user. It covers the prerequisite checks and steps 2 to 5 of
[SETUP.md](SETUP.md): set up an RCS agent per brand, deploy each brand's stack with AWS
Cloud Development Kit (AWS CDK), and wire up the dashboard. **The normal path is
"Deploy one or more brands" below**, which runs `scripts/deploy.mjs`; the sections after
it are the same work one command at a time, for when a step needs doing by hand. SETUP.md explains each step. This file keeps the
commands, the questions to ask the user and the conditions on which to stop.

If you are a human, follow [SETUP.md](SETUP.md). Its step 2 sends you to the command sections in this file; read "the user" there as you. If you are a coding agent, read on.

> **Attribution:** "RCS Agent Setup" is adapted from
> [`aws-samples/sample-rcs-agent-setup-and-send-messages`](https://github.com/aws-samples/sample-rcs-agent-setup-and-send-messages)
> (MIT-0). See [NOTICE](NOTICE).

## Ground rules

- **Terms.** An *RCS agent* is the AWS resource that sends the messages; you are the AI
  coding assistant. The *selected brands* are the brands the user chose to stand up
  (each `<id>` one of `anyhealth`, `anytravel`, `anywealth`, `anyhr`, `anybuild`). In the
  one-command-at-a-time sections, `<id>` (or `BRAND`) is the one brand you are working on.
  `<prefix>` is a brand's name in lowercase, with each run of other characters replaced
  by `-`, leading and trailing `-` removed and the result cut to 20 characters
  (`anyhealth` for the default brand, and whenever nothing is left); its stack is
  `<prefix>-rcs-demo`.
- **One stack and one agent per brand.** Each selected brand gets exactly one agent and
  one stack, and the agent is registered as that brand. Never point one brand's stack at
  another brand's agent. Deploy only the brands the user chose; when the user names
  none, ask (suggest `anyhealth`, the default). Several brands run one after another,
  never in parallel: `scripts/deploy.mjs` does that for you. If you run `cdk` by hand,
  pass `-c brand=<id>` as its own shell word for each brand.
- **Where commands run.** Run every command from the repository root. A command that
  needs `cdk/` or `web/` runs in a subshell, for example `(cd cdk && npx cdk diff)`.
- **Profile and Region.** Add `--region <REGION>` to every `aws` command. If the user
  gave a profile, also add `--profile <PROFILE>` and set `AWS_PROFILE=<PROFILE>` for every
  `cdk` command.
- **Confirm before you create.** Tell the user the account ID (from
  `aws sts get-caller-identity`) and the Region, confirm that it is a sandbox account
  where creating and deleting resources is acceptable, and wait for approval. In the
  same message, ask for the user's phone number (E.164, no guessed country code); if the
  reply has no valid number, ask again before step 2.
- **Messages.** Send a message only to the user's own number, after the user agrees and
  the number shows `VERIFIED` for this RCS agent (the `Agent` column equals `<AGENT_ID>`).
- **Errors.** Show the user the error and the matching row of "Troubleshooting", then
  wait. Do not work around a failing command. Run a fix that installs, upgrades, changes
  or deletes something only after the user approves that exact command.
- **Secrets.** Never ask for, print or paste access keys, session tokens, passwords or
  the API key in the chat, and do not read `web/.env`, `web/.env.*` or
  `.deploy/dashboard-brands.json` back.
- **Time-outs.** Your shell tool can time out before a long wait ends (the test device
  invitation takes 2 to 20 minutes; `cdk deploy` takes several). Poll in short commands
  or run the long command in the background, and check
  `aws cloudformation describe-stacks --stack-name <prefix>-rcs-demo` before you re-run
  a command that might still be running.

---

## Single source of truth: `content/brand.md`

The YAML frontmatter of `content/brand.md` holds a **brand catalog**, not one flat brand:
a `defaultBrand` pointer and a `brands:` map keyed by stable id (in this version
`anyhealth`, `anytravel`, `anywealth`, `anyhr`, `anybuild`; read the file for the current
list). Each key maps to that brand's complete identity block — the values
for its agent registration (name, accent color, contact details, URLs, use case) plus its
media paths and grounding. The blocks are independent siblings; there is no umbrella
block. **Read that file first** and use the **selected brand's block** (`brands.<id>.*`)
throughout — never the top-level keys and never another brand's block. Do not invent a
brand, and do not ask the user for details that are already present in that block. If a
required value is missing or invalid for the selected brand, ask the user to fix that
brand's block in `content/brand.md`, then continue.

### Choosing the brands

The user picks one or more brands (each one of `anyhealth`, `anytravel`, `anywealth`,
`anyhr`, `anybuild`), or `all`. When the user names none, ask, and suggest
`defaultBrand` from the frontmatter (`anyhealth`). Validate every chosen id against the
`brands:` keys before you create anything: an unknown id stops the setup — name the
offending id and list the valid keys, and do not create an agent or any resource
(`scripts/deploy.mjs` does this check too). For each brand, the agent you register and
the stack you deploy are that one brand.

### Brand media

Each brand's assets are committed per brand at `media/<id>/logo.png` (224×224) and
`media/<id>/banner.png` (1440×448) — for example `media/anyhealth/logo.png` and
`media/anyhealth/banner.png`. Use the **selected brand's** folder for its registration
attachments. `media/<id>/card.png` (1440×480) is the picture on the welcome and
check-in cards, not a registration attachment: do not upload it. The user can
replace any of them: check a replacement against the format, size and file-size
limits in [SETUP.md step 1](SETUP.md#1-configure-your-brand-optional) before you
upload it.

---

## Prerequisites (check these before you start)

Check each item before you create anything; a missing item fails a later step, except
Amazon Bedrock access, which only the AI use case examples and the photo descriptions
need. Report what is missing and stop
instead of working around it. [SETUP.md](SETUP.md#prerequisites) explains each item.

| Need | Check | If missing |
|---|---|---|
| AWS credentials | `aws sts get-caller-identity` | The user signs in (see "Authentication") |
| AWS Command Line Interface (AWS CLI) v2 with the RCS commands | `aws pinpoint-sms-voice-v2 set-rcs-message-spend-limit-override --generate-cli-skeleton > /dev/null 2>&1 && echo ok` (offline; tests for the operation itself. Do not use `help`: some builds that have the commands fail to render it) | Ask the user to upgrade to AWS CLI v2 2.35.12 or later ([AWS CLI with the RCS commands](SETUP.md#aws-cli-with-the-rcs-commands)) |
| RCS monthly spend limit | "Getting started" step 3 | `MaxLimit` of 1: see step 3 |
| A free RCS agent slot | `aws service-quotas get-service-quota --service-code sms-voice --quota-code L-AE02F3F6 --region <REGION> --query Quota.Value` greater than `aws pinpoint-sms-voice-v2 describe-rcs-agents --region <REGION> --query 'length(RcsAgents)'` | Tell the user before you create anything; see the `RCS_AGENTS_PER_ACCOUNT` row of "Troubleshooting" |
| Amazon Bedrock access (AI use case examples and photo descriptions only) | The smoke test after this table | The notes after the smoke test |
| Node.js 22 or later | `node --version` | Ask before you install a current Node.js LTS |
| `python3` 3.10 or later (or `pip` 24.2 or later), or Docker | `python3 -m pip --version` or `docker info` | Upgrade `pip`, set `PYTHON=/path/to/python3`, or start Docker ([Node.js, python3 and Docker](SETUP.md#nodejs-python3-and-docker)) |
| RCS-capable test phone | Ask the user | Android with RCS chat enabled, or an iPhone on iOS 18 or later |

The Bedrock smoke test is a real call that costs a few tokens, and the first call can
subscribe the account to the model through AWS Marketplace. Tell the user, and run it only
after the user confirms the account, Region and phone number (ground rules). Use the
Region from "Region choice" unless `bedrockRegion` is overridden, and any `bedrockModelId` override:

```bash
aws bedrock-runtime converse --region <BEDROCK_REGION> --model-id global.anthropic.claude-sonnet-4-6 --messages '[{"role":"user","content":[{"text":"Reply with OK."}]}]' --inference-config '{"maxTokens":16}' --query 'output.message.content[0].text' --output text
```

On `AccessDeniedException`, the account has not submitted the one-time Anthropic use case
form, or the identity has no `aws-marketplace:Subscribe` permission or valid payment method
([Amazon Bedrock access and model choice](SETUP.md#amazon-bedrock-access-and-model-choice)).
If the denial comes soon after the form was submitted, wait a few minutes and run the
call again (the subscription can take up to 15 minutes). The user completes the form in
the Bedrock console; do not submit it for the user or
invent its answers (company name, website, industry, use cases). On a validation error,
the model ID or inference profile is not offered in that Region: follow "Region choice".

### Region choice

Use the Region the user gave in the prompt; if none, ask, and suggest `us-east-1`. The
RCS agent and the stack must be in the same Region, so if the user already has an RCS
agent, use the Region it lives in. The Bedrock Region defaults to that Region
(`-c bedrockRegion=<Region>` changes it). Ask about the Bedrock model only if the
user has a data-residency requirement. Then list the profiles instead of guessing the
prefix, choose one with the user as
[SETUP.md](SETUP.md#amazon-bedrock-access-and-model-choice) describes, and pass it as
`-c bedrockModelId=<id>`. Repeat every `-c` option on `cdk diff` and `cdk deploy`.

```bash
aws bedrock list-inference-profiles --region <BEDROCK_REGION> --type-equals SYSTEM_DEFINED --query "inferenceProfileSummaries[?contains(inferenceProfileId, 'anthropic')].inferenceProfileId"
```

### Authentication

The user signs in in their own terminal: `aws sso login --profile <PROFILE>` or
`aws configure`. When the user says they are done, run `aws sts get-caller-identity` to
confirm. Credentials can be short-lived, and this workflow has waits of several minutes.
If a command fails with an expired-token error (`ExpiredToken` or `ExpiredTokenException`),
ask the user to refresh the credentials and continue from where you stopped. Do not
restart: resources that were already created, such as the RCS agent and its registration,
stay in place.

`AdministratorAccess` covers everything in this file, and `cdk deploy` needs permissions
for several more services, so a scoped-down policy is not practical.
[SETUP.md](SETUP.md#required-iam-actions) lists the `sms-voice` actions that the commands
use, and [SECURITY.md](SECURITY.md#permissions-the-deploy-needs-for-the-log) lists what a
narrower AWS CloudFormation execution policy must allow for the API access log.

---

## Deploy one or more brands

This is the normal path. `scripts/deploy.mjs` runs the pre-flight checks, prints one plan,
and then, for each brand in turn, creates the agent if needed, runs `cdk deploy`, wires
the dashboard and sends the tester invitation.
[SETUP.md](SETUP.md#deploy-one-or-more-brands) describes every check and stage.

1. **Brands, account, Region, phone.** Ask which brands to deploy (or take them from the
   prompt) and validate them ("Choosing the brands"). Then run
   `aws sts get-caller-identity` and send the ground-rules confirmation message (account
   ID, Region, sandbox confirmation, the user's phone number), and wait for the reply.
2. **Install and plan.** Tell the user that pre-flight is read-only and takes about a
   minute per brand (it runs `cdk diff`), then run:

   ```bash
   (cd cdk && npm ci)
   node scripts/deploy.mjs --brands <id,id,...> --region <REGION> --phone <PHONE> --plan-only
   ```

   Add `--profile <PROFILE>` if the user gave one, and `--context key=value` for each
   deploy option the user chose (for example `--context bedrockModelId=<id>`; see
   "Region choice"). Add `--check-bedrock` only after telling the user that it makes one
   real model call that costs a few tokens and can subscribe the account to the model.
3. **Show the plan.** Show the whole output to the user. If it says **Blocked**, show
   each blocker with its fix and wait: do not work around one. Otherwise point out what
   costs money or changes something outside the stack:
   - each new agent (registration fees: [RCS pricing](https://aws.amazon.com/end-user-messaging/pricing/), [Cost](README.md#cost))
   - the IAM statement counts (the full diffs are in `.deploy/logs/<brand>-plan.diff`)
   - `cdk bootstrap` if listed
   - each warning, in particular a spend limit of $1 ("Getting started" step 3) and an
     agent whose two-way messaging points elsewhere ("Getting started" step 4)

   Then ask the user to approve the plan.
4. **Deploy.** After the user approves, run the same command with `--yes` in place of
   `--plan-only`. It takes roughly 10 minutes per new brand, so run it in the background
   and poll its output, or poll `aws cloudformation describe-stacks` for each stack.
   Do not start a second run while one is going.
5. **Report.** Show the summary. For a brand marked `FAILED`, show its `why`, `exists
   now`, `log` and `to resume` lines, and the matching "Troubleshooting" row. Run the
   resume command only after the user approves it. Tell the user to accept each "RBM
   Tester Management" invitation on the phone (2 to 20 minutes; on an iPhone, check
   **Unknown Senders**); the run does not wait for them.
6. **Dashboard.** Continue at "Wire up the dashboard" with `(cd web && npm ci)` and
   starting the dashboard; the wiring command itself already ran for each deployed brand.

The sections below are the same work one command at a time. Use them when the user asks
for that, or to finish a step that the summary says failed.

---

## RCS Agent Setup

You help the user create a brand's RCS agent on AWS End User Messaging (a testing agent,
which delivers only to registered test devices), add the user's phone as a test device,
and record the agent ID for the deploy. Work on one brand at a time; each brand gets
exactly one agent. You run every command yourself. The user provides inputs and confirms
results. Follow the ground rules on every error.

### Session state (track as you go)

- `BRAND`: the selected brand id (one of `anyhealth`, `anytravel`, `anywealth`, `anyhr`, `anybuild`; default `anyhealth`), validated against the `brands:` keys in `content/brand.md`
- `REGION`: the Region chosen under "Region choice" (suggest `us-east-1` if the user has no preference)
- `AGENT_ID` and `REG_ID`: the RCS agent ID (`rcs-XXXX`) and the registration ID
- `PHONE`: the user's phone number (E.164)

### Getting started

When the user asks to set up the RCS agent or the demo, start here.

1. **Choose the brand.** You are doing one brand by hand (for several, use "Deploy one or
   more brands" above). Take the brand you are working on from the user's list ("Choosing
   the brands"). Validate the chosen id against the `brands:` keys in
   the frontmatter: if it is not a defined key, stop here, name the offending id and list
   the valid keys, and create nothing. Record the id as `BRAND`; read the selected brand's
   identity block (`brands.<BRAND>.*`) for every value from now on.
2. Run `aws sts get-caller-identity`. When it succeeds, send the ground-rules
   confirmation message (account ID, Region, sandbox confirmation, request for the phone
   number) and wait for the reply. Then walk the rest of the "Prerequisites" table,
   including the RCS capability check, and run the Bedrock smoke test only after that reply.
3. Check the RCS spend limit before you create anything (step 4 then confirms RCS
   access):

   ```bash
   aws pinpoint-sms-voice-v2 describe-spend-limits --region <REGION> \
     --query "SpendLimits[?Name=='RCS_MESSAGE_MONTHLY_SPEND_LIMIT']"
   ```

   You need `MaxLimit` and `EnforcedLimit` greater than `1`; read the values for this
   Region (a new account often returns 1 for both). If `MaxLimit` is
   1, tell the user that the deploy and **Device preview** still work, that real sends stop
   after a few dozen messages once the $1 monthly limit is reached, and that an increase
   request can take days ([RCS monthly spend limit](SETUP.md#rcs-monthly-spend-limit)).
   Wait for the user to decide whether to continue or to request the increase first. If
   `EnforcedLimit` is less than `MaxLimit` (for example after an approved increase), or the
   user wants a lower cap as a cost guardrail (RCS only), ask for the monthly cap in
   dollars (up to `MaxLimit`), show
   `aws pinpoint-sms-voice-v2 set-rcs-message-spend-limit-override --monthly-limit <DOLLARS> --region <REGION>`
   with that value, and run it only after the user approves.
4. Check for an existing RCS agent before you create one:

   ```bash
   aws pinpoint-sms-voice-v2 describe-rcs-agents --region <REGION> \
     --query "RcsAgents[].{Id:RcsAgentId,Status:Status,Testing:TestingAgent.Status,TwoWay:TwoWayChannelArn}"
   ```

   - `Status: TESTING` with `Testing: ACTIVE` is the finished state for a testing agent
     ([SETUP.md step 2](SETUP.md#2-set-up-your-rcs-agent)). Tell the user that you found
     it, that creating a new agent is the recommended path, and that
     [reusing it](SETUP.md#use-an-existing-agent) is possible if no other work depends on
     it; the handset then shows that agent's registered brand, not the selected brand's
     block in `content/brand.md`.
     Create a new agent unless the user chooses to reuse this one. If the user reuses it,
     do the two-way and phone-number bullets below first, then
     skip to "Record the agent ID for deployment", and run "Add a test device" unless
     the user's phone is listed with `Status: VERIFIED` and `Agent` equal to `<AGENT_ID>`.
   - If an agent exists in another state (for example `CREATED`), leave it alone
     and ask the user before you create another one.
   - If the agent already has a `TwoWayChannelArn`, warn the user: `cdk deploy` repoints
     two-way messaging at this stack and `cdk destroy` turns it off instead of restoring
     the previous value ([Teardown](SETUP.md#teardown) has the command that records the
     current settings). Record them first, or use a dedicated RCS agent, and wait for the
     user to choose.
   - With the user's number (from the confirmation message), look up only that number, so
     that you do not list other people's:

     ```bash
     aws pinpoint-sms-voice-v2 describe-verified-destination-numbers --region <REGION> \
       --destination-phone-numbers <PHONE> \
       --query 'VerifiedDestinationNumbers[].{Id:VerifiedDestinationNumberId,Phone:DestinationPhoneNumber,Status:Status,Agent:RcsAgentId}'
     ```

     Pass the number in exact E.164 form, including the leading `+`. If the command
     returns `ResourceNotFoundException`, the number is not registered yet: treat that
     as an empty result. A `PENDING` number with no `Agent` was added without
     `--rcs-agent-id` and gets no invitation. Ask before you run
     `delete-verified-destination-number --verified-destination-number-id <Id> --region <REGION>`
     and add the number again with the flag. A number verified for the SMS sandbox also
     shows no `Agent`; leave it in place.
5. Read the selected brand's block in `content/brand.md` frontmatter
   (`brands.<BRAND>.*`). Confirm the brand summary (`brandName`, `useCase`, `accentColor`)
   with the user before you create anything; the brand, account and
   Region are already confirmed. Creating the agent is the first step that can cost money
   and the first that needs teardown: RCS agents can carry registration fees, billed
   separately from messages. Point the user at the
   [RCS pricing](https://aws.amazon.com/end-user-messaging/pricing/) page and at
   [Cost](README.md#cost) before you create the agent, and suggest reviewing the line
   items on the bill afterward.

### Registration field reference (TEST_RCS_LAUNCH_REGISTRATION)
`put-registration-field-value` takes `--registration-id`, `--field-path` and one value flag
that depends on the field type: TEXT `--text-value "<value>"`, SELECT
`--select-choices "<value>"`, ATTACHMENT `--registration-attachment-id "<id>"`. Do not use
`--field-values` (it does not exist). For example:

```bash
aws pinpoint-sms-voice-v2 put-registration-field-value --registration-id <REG_ID> --field-path agentDetails.brandName --text-value "<brandName>" --region <REGION>
```

The testing registration form has 21 fields: 13 `REQUIRED`, 6 `CONDITIONAL` (the contact
fields) and 2 `OPTIONAL` (labels). Set every `REQUIRED` field and, of the contact fields,
at least one value together with its label; this sample sets all three pairs.
`submit-registration-version` names any `REQUIRED` field without a value, and a
registration that the review sends back (`REQUIRES_UPDATES`) shows a `DeniedReason` (see
"Troubleshooting"). The authoritative list is one read-only call:

```bash
aws pinpoint-sms-voice-v2 describe-registration-field-definitions \
  --registration-type TEST_RCS_LAUNCH_REGISTRATION --region <REGION> \
  --query 'RegistrationFieldDefinitions[].[FieldPath,FieldRequirement,FieldType]' --output table
```

Paths are under `agentDetails.`. Every value comes from the **selected brand's block**
in the `content/brand.md` frontmatter (`brands.<BRAND>.`) under the key with the same
name — never the top-level keys and never another brand's block — except where noted:

- `REQUIRED`, TEXT: `brandName`, `serviceName`, `senderDisplayName`, `agentDescription`,
  `accentColor` (must pass 4.5:1 contrast against white), `privacyPolicyUrl`,
  `termsAndConditionsUrl`, `monthlyRcsVolume`.
- `REQUIRED`, SELECT: `useCase` (`MULTI_USE`), `averageMonthlyRcsFrequency`,
  `billingCategory` (`CONVERSATIONAL`).
- `REQUIRED`, ATTACHMENT: `logoImage` (upload `media/<BRAND>/logo.png`) and `bannerImage`
  (upload `media/<BRAND>/banner.png`) — the selected brand's own media folder, for example
  `media/anyhealth/logo.png`.
- `CONDITIONAL`, TEXT: `contactPhoneNumber`, `contactPhoneLabel`, `contactEmailAddress`,
  `contactEmailLabel`, `contactWebsite`, `contactWebsiteLabel`.
- `OPTIONAL`, TEXT: `privacyPolicyLabel` ("Privacy Policy") and `termsAndConditionsLabel`
  ("Terms and Conditions").

**Keyword replies.** The testing registration has no keyword fields: `cdk deploy`
registers the `HELP`, `STOP` and `UNSTOP` replies as keywords on the RCS agent (see
"Register the keyword replies"). A country launch registration's `complianceKeywords`
values must match them ([Launching RCS in countries](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-country-launch.html)).

### Create the agent

**One command, if the user prefers it.** `scripts/create-agent.mjs` runs this section,
"Poll until the testing agent is active", "Record the agent ID for deployment" and "Add a
test device" in one go. Before it creates anything it checks for a free agent slot, an
existing agent already registered as the brand, the spend limit, and the brand's block.
Run the dry run first and show the user its output:

```bash
node scripts/create-agent.mjs <BRAND> <REGION> --phone <PHONE> --dry-run
```

After the user approves, run the same command with `--yes` in place of `--dry-run`. It
can take about 10 minutes (the agent wait plus two minutes before the invitation), so run
it in the background or poll its output. Exit code 2 means a check refused and nothing
was created: show the message. Exit code 1 means an AWS step failed: show the error and
the matching "Troubleshooting" row, and after the fix run the same command again. It
resumes from `.deploy/agent-setup/<BRAND>.json` instead of creating a second agent. Then
continue with the device check in "Add a test device".

To run the steps one at a time instead, run the commands in order, replace the placeholders, and save each ID that the output
returns. The brand comes from the registration, so `create-rcs-agent` takes no display
name.

```bash
aws pinpoint-sms-voice-v2 create-rcs-agent --region <REGION>
aws pinpoint-sms-voice-v2 update-rcs-agent --rcs-agent-id <AGENT_ID> --deletion-protection-enabled --region <REGION>
aws pinpoint-sms-voice-v2 create-registration --registration-type TEST_RCS_LAUNCH_REGISTRATION --region <REGION>
aws pinpoint-sms-voice-v2 create-registration-association --registration-id <REG_ID> --resource-id <AGENT_ID> --region <REGION>
aws pinpoint-sms-voice-v2 create-registration-attachment --attachment-body fileb://media/<BRAND>/logo.png --region <REGION>
aws pinpoint-sms-voice-v2 create-registration-attachment --attachment-body fileb://media/<BRAND>/banner.png --region <REGION>
```

1. `create-rcs-agent` returns `RcsAgentId` (`AGENT_ID`) and `create-registration` returns
   `RegistrationId` (`REG_ID`). Each `create-registration-attachment` returns an
   attachment ID: save the logo ID and the banner ID (`--attachment-body` and
   `--attachment-url` are mutually exclusive).
2. Set every `REQUIRED` field, the contact fields and the two `OPTIONAL` labels with
   `put-registration-field-value` (see "Registration field reference"), taking every
   value from the selected brand's block (`brands.<BRAND>.*`) in `content/brand.md`. If a
   required field is missing or invalid for the selected brand, stop before creating the
   agent and name both the brand and the field for the user to fix.
3. Submit the registration:

   ```bash
   aws pinpoint-sms-voice-v2 submit-registration-version --registration-id <REG_ID> --region <REGION>
   ```

### Poll until the testing agent is active
```bash
aws pinpoint-sms-voice-v2 describe-rcs-agents --rcs-agent-ids <AGENT_ID> \
  --query "RcsAgents[].{Status:Status,TestingStatus:TestingAgent.Status}" --region <REGION>
```
Poll every 15 seconds until `TestingAgent.Status` is `ACTIVE`. If the status is not
`CREATED`, `PENDING` or `ACTIVE`, or it is not `ACTIVE` after about 5 minutes, run
`aws pinpoint-sms-voice-v2 describe-registration-field-values --registration-id <REG_ID> --region <REGION>`
and look for `DeniedReason` (see "Troubleshooting") instead of polling on.

### Record the agent ID for deployment

Record the agent for the selected brand in the CDK's local, gitignored config, so that
`cdk deploy -c brand=<BRAND>` picks it up with nothing hardcoded:
```bash
node scripts/record-agent.mjs <BRAND> <AGENT_ID> <REGION>
```
The script checks in AWS that the agent's registration carries the brand's `brandName`
and refuses one registered as another brand. It writes `agents.<BRAND>` into
`.deploy/agent.json` and keeps every other brand's entry. If it reports that the brand
already has a different agent recorded, show the user both agent IDs and ask before you
add `--replace`: pointing the deploy at a different agent leaves the old agent with
two-way messaging on. Do not write `.deploy/agent.json` by hand.

Then tell the user: **"The selected brand's RCS agent is ready. Next I add your phone as a
test device, then deploy the demo."** Remind the user that `cdk deploy` must name the same
brand you set up here (`-c brand=<BRAND>`, or nothing when the brand is `anyhealth`).

### Add a test device
A testing agent delivers only to registered test devices, and each device is added one at
a time by an invitation the person must accept on the handset — expect that per-device
friction. One agent holds at most ten test devices, which is ample for this demo, where
you register only the user's own number.

Wait two minutes after `TestingAgent.Status` is `ACTIVE` before you add a test device;
the service holds each invitation for at least 120 seconds:
```bash
aws pinpoint-sms-voice-v2 create-verified-destination-number --destination-phone-number <PHONE> --rcs-agent-id <AGENT_ID> --region <REGION>
```
Tell the user: the invitation arrives in 2 to 20 minutes from **RBM Tester Management**
(on an iPhone, check **Unknown Senders**); tap **Make me a tester**. Ask the user to tell
you when they have tapped it, then verify:
```bash
aws pinpoint-sms-voice-v2 describe-verified-destination-numbers --destination-phone-numbers <PHONE> \
  --query 'VerifiedDestinationNumbers[].{Id:VerifiedDestinationNumberId,Phone:DestinationPhoneNumber,Status:Status,Agent:RcsAgentId}' --region <REGION>
```
Wait for `Status: VERIFIED`. While it reads `PENDING`, run it again every 30 seconds for up
to 20 minutes, then follow "Troubleshooting".

### Send a quick test (optional)

Send this only after the user agrees, the user's number shows `VERIFIED` for this RCS
agent, and the RCS spend limit allows sends:
```bash
aws pinpoint-sms-voice-v2 send-text-message --destination-phone-number <PHONE> --origination-identity <AGENT_ID> \
  --message-body "Hello from <brandName>! Your RCS agent is live." --message-type TRANSACTIONAL --region <REGION>
```

---

## Deploy the demo

Start here after `TestingAgent.Status` is `ACTIVE` and the agent is recorded for `BRAND`
in `.deploy/agent.json`. Every synth prints
`[rcs-demo] brand=<BRAND> agent=<AGENT_ID> region=<REGION> (agent from ...)` on stderr:
check that it names `BRAND` and `AGENT_ID` before you show the diff. Synth stops if the
agent's registration names another brand; follow the SETUP.md troubleshooting entry, and
never add `-c skipAgentCheck=true` unless the user asks for it.
Pass each `-c` flag as its own shell word. A variable holding several flags is not split
in zsh, and CDK then falls back to the default brand.
Pass the same brand you set up with `-c brand=<BRAND>` on every `cdk` command below (omit
it only when `BRAND` is `anyhealth`, the default); the stack must provision the brand whose
agent you registered.
[SETUP.md step 3](SETUP.md#3-deploy-the-infrastructure) describes what the deploy creates
and the `-c` options. `cdk deploy` asks for confirmation before it applies changes that
broaden AWS Identity and Access Management (IAM) permissions, and a shell with no
interactive terminal cannot answer (CDK stops with
`terminal (TTY) is not attached so we are unable to get a confirmation from the user`),
so show the user the IAM changes in the diff first:

```bash
(cd cdk && npm ci)
(cd cdk && npx cdk bootstrap -c brand=<BRAND>)
(cd cdk && npx cdk diff -c brand=<BRAND>)
```

Run this only after the user approves the diff:

```bash
(cd cdk && npx cdk deploy -c brand=<BRAND> --require-approval never)
```

1. `cdk bootstrap` runs once per account and Region. The first run creates the
   CDKToolkit stack (an Amazon Simple Storage Service (Amazon S3) bucket, an Amazon
   Elastic Container Registry (Amazon ECR) repository and IAM roles), so tell the user
   first, and ask before you run it if the organization customized CDK bootstrapping.
2. Repeat every `-c` option that the user chose — `brand` (the selected brand, unless it
   is the `anyhealth` default), and for example `bedrockRegion`, `bedrockModelId`,
   `registerKeywords` or `smsFallbackNumber` — on `diff` and `deploy`.

The deploy prints several outputs. Note three: **`ApiUrl`**, **`ApiKeySecretName`** and
**`KeywordsStatus`**.
`KeywordsStatus` should start with `ok` (or `skipped` if you turned the keyword step
off). `error (...)` means the replies were not all registered; the deploy itself still
succeeded (see "Register the keyword replies").

### Wire up the dashboard

An API key gates every route except the few that are open on purpose
([SECURITY.md](SECURITY.md#routes-that-need-the-api-key)), so the dashboard needs both
the URL and the key. Wire the selected brand in with the wiring command, which reads
`ApiUrl`, `ApiKeySecretName` and the secret itself, so you pass no URL, secret name or
key. Run it from the repository root with the session values `BRAND` and `REGION`, and
add the profile as a third argument only if the user gave one:

```bash
node scripts/wire-dashboard-brand.mjs <BRAND> <REGION> [<PROFILE>]
(cd web && npm ci)
```

The command writes the brand's URL and key to `.deploy/dashboard-brands.json` (mode 600,
gitignored) and prints neither the key nor the AWS error text. It needs the CDK
dependencies from the deploy (`(cd cdk && npm ci)`). It names a bad brand id or Region
before it calls AWS. On a failure it prints a short category such as `ExpiredToken` or
`AccessDenied`: show it to the user and follow the ground rules on errors. To replace a
brand's key later, run the command for that brand again.

**More than one brand.** One `npm run dev` on one port serves every wired-up brand. When
the user deploys a further brand (a separate deploy, with its own agent), run the same
command for that brand. The dashboard then shows a brand picker, and the new brand
appears after the user reloads the page. The dashboard lists a wired brand only if it can
load that brand's agent identity (a live stack, a working key and a registered agent), so
a brand that was torn down or has no key is simply not offered. Do not start a second `npm run dev` and do not
restart the first one.

**Never print or read back the key.** Do not echo the key, paste it into a command, or
ask the user for it. Do not read `.deploy/dashboard-brands.json`, `web/.env` or any
`web/.env.*` file back, and do not `cat`, `grep` or `git diff` them. To check that a
brand is wired, ask the user to reload the dashboard and look for the brand.

For a single brand, `web/.env` still works instead of the wiring command. Existing
`web/.env.<BRAND>` files also keep working; a wiring-command entry takes precedence over
one for the same brand. Write `web/.env` with one command that never prints the key:

```bash
(umask 077; KEY=$(aws secretsmanager get-secret-value --secret-id <ApiKeySecretName> --query SecretString --output text --region <REGION>) && printf 'VITE_API_URL=%s\nVITE_API_KEY=%s\n' '<ApiUrl>' "$KEY" > web/.env)
```

`web/.env` and `.deploy/dashboard-brands.json` are gitignored; never commit them. Run
the dashboard only with `npm run dev` on the user's own machine: `npm run build` compiles `VITE_API_KEY` into the bundle, so do
not host or share a `web/dist` build
([Why the dashboard is local-only](SECURITY.md#why-the-dashboard-is-local-only)).
`npm run dev` does not exit. Start it in the background, or ask the user to run
`(cd web && npm run dev)` in a second terminal, and read the URL from Vite's output
(<http://localhost:5173> unless that port is busy).

Then hand over to the user: they open the dashboard, find their phone on the
**Recipients** tab (**Add recipient** registers a new number as a test device and sends
the invitation; for a number that is already registered it only saves the name), confirm
`VERIFIED`, set the target and send a use case example. Do not call
the dashboard API or send a use case example yourself. Tell the user they can tap the
**Start Over** chip, or type `start over` or `menu`, on the phone to restart from the
brand's home menu ([SETUP.md step 6](SETUP.md#6-try-the-demo)).

---

## Reference: optional steps, teardown, troubleshooting

Use these sections when a step calls for them.

### Register the keyword replies

**`cdk deploy` registers them for you.** The wiring custom resource
(`lambda/custom_resources/eum_wiring.py`) writes three keywords on the agent right after
it enables two-way messaging, with text built from the selected brand's block in
`content/brand.md`: `HELP` (action
`AUTOMATIC_RESPONSE`), `STOP` (`OPT_OUT`) and `UNSTOP` (`OPT_IN`). The service answers these keywords itself, and the deployed bot
stays silent for them
([Keywords, and where a keyword is answered](docs/architecture.md#21-keywords-and-where-a-keyword-is-answered)).

**What the deploy overwrites.** The deploy writes `HELP` or `STOP` only while the keyword
is empty, still the AWS default, or still the text the previous deploy wrote, and it
creates `UNSTOP` only when it is absent (or refreshes it the same way). A reply identical
to the one it would write is `unchanged`; any other reply stays, and `KeywordsStatus`
says `kept (set by you)`. Other keywords are never touched. A new stack has no record
of what an earlier stack wrote: after a
selected brand's `brandName` change that alters the prefix (or a switch to a different
brand, which does the same) ([Editing the demo](README.md#editing-the-demo)) or after
`cdk destroy` and a fresh deploy, it treats the replies already on the agent as the
user's, and the same rules apply to them.

**It never fails the deploy.** If the step errors (for example `PutKeyword` is rejected),
the stack still deploys, a reply that could not be written stays as it was, the remaining
keywords are still attempted, and the **`KeywordsStatus`** output reads `error (...)`
with the AWS error code; the detail is in the `/aws/lambda/<prefix>-eum-wiring` log
group. Fix the cause, then redeploy or register the replies by hand (see "By hand"). A
redeploy runs the step again only when a property of the wiring resource changes, such as
an edited reply in `brand.md`.
`-c registerKeywords=false` skips the step ([Deploy options](SETUP.md#deploy-options)).
[Teardown](SETUP.md#teardown) covers what `cdk destroy` and a switch to another agent
leave behind.

**By hand**, to use other wording, to have real text before the first deploy, or after a
failed step. Show the user the three reply texts first; `put-keyword` replaces an
existing keyword of the same name. A keyword is 1-30 characters and case-insensitive, and
the origination identity is the RCS agent ID. Run these once the agent exists:

```bash
aws pinpoint-sms-voice-v2 describe-keywords --origination-identity <AGENT_ID> --region <REGION>

aws pinpoint-sms-voice-v2 put-keyword --origination-identity <AGENT_ID> --keyword HELP \
  --keyword-action AUTOMATIC_RESPONSE --region <REGION> \
  --keyword-message "<brandName>: for help call <contactPhoneNumber> or email <contactEmailAddress>. Reply STOP to opt out."
aws pinpoint-sms-voice-v2 put-keyword --origination-identity <AGENT_ID> --keyword STOP \
  --keyword-action OPT_OUT --region <REGION> \
  --keyword-message "<brandName>: you are opted out and will receive no more messages. Reply UNSTOP to opt back in."
aws pinpoint-sms-voice-v2 put-keyword --origination-identity <AGENT_ID> --keyword UNSTOP \
  --keyword-action OPT_IN --region <REGION> \
  --keyword-message "<brandName>: you are opted back in to messages. Reply STOP to opt out."
```

`<brandName>`, `<contactPhoneNumber>` and `<contactEmailAddress>` come from the selected
brand's block (`brands.<BRAND>.*`) in `content/brand.md`. The Settings tab shows `HELP`
and `STOP` read-only, so use the CLI to set their text by hand.

### Clear an opt-out entry

When a test device texts `stop`, the service adds the number to the account's Default
opt-out list, and every send to it fails with `DESTINATION_PHONE_NUMBER_OPTED_OUT`. If an
`OPT_IN` keyword such as `UNSTOP` is registered, the device can text it to opt back in.
Otherwise, clear the entry only for the user's own number and only when the user asks,
because the entry records that person's `STOP`:

```bash
aws pinpoint-sms-voice-v2 describe-opted-out-numbers --opt-out-list-name Default --opted-out-numbers <PHONE> --region <REGION>
aws pinpoint-sms-voice-v2 delete-opted-out-number --opt-out-list-name Default --opted-out-number <PHONE> --region <REGION>
```

AWS allows one deletion per number per 30 days. The `Default` list belongs to the
account, not to one agent, and the sample reads only that list; if the agent uses another
one, see
[Keywords, and where a keyword is answered](docs/architecture.md#21-keywords-and-where-a-keyword-is-answered).

### Teardown

Tear the CDK stack down first: it holds the two-way wiring that points at the agent.
Note the `ApiKeySecretName` value first ([Teardown](SETUP.md#teardown) explains why). A
shell with no interactive terminal cannot answer `cdk destroy`'s confirmation prompt, so
tell the user that `npx cdk destroy` deletes the stack `<prefix>-rcs-demo` of `<BRAND>` and,
once the user approves, run:

```bash
(cd cdk && npx cdk destroy -c brand=<BRAND> --force)
```

Then take the brand off the dashboard, so its entry does not linger in
`.deploy/dashboard-brands.json` (the dashboard already leaves out a brand whose stack is
gone, so this only keeps the file tidy). It makes no AWS call and prints no key:

```bash
node scripts/wire-dashboard-brand.mjs --remove <BRAND>
```

[SETUP.md](SETUP.md#teardown) explains what the destroy leaves behind and the two-way
caveat. Ask the user whether this RCS agent was created for this demo and whether
anything else uses it. If it was reused or is shared, stop here unless the user asks you
to delete it. Otherwise run `node scripts/delete-agent.mjs <BRAND> <REGION> --dry-run`,
show the user its plan, and after the user approves, run it again with `--yes` instead of
`--dry-run`. It refuses an agent registered as another brand or one whose stack still
exists, deletes in the order below, retries `RESOURCE_NOT_EMPTY`, and removes the brand's
entry from `.deploy/agent.json`. To run the steps one at a time instead, delete the RCS
agent resources in this order, each command only after the user approves it. If you no
longer have `REG_ID`, read it from
`describe-rcs-agents --rcs-agent-ids <AGENT_ID>` (`TestingAgent.RegistrationId`).
Test devices (verified destination numbers) belong to the RCS agent, so remove them first:

```bash
aws pinpoint-sms-voice-v2 describe-verified-destination-numbers --filters Name=rcs-agent-id,Values=<AGENT_ID> --query 'VerifiedDestinationNumbers[].VerifiedDestinationNumberId' --region <REGION>
aws pinpoint-sms-voice-v2 delete-verified-destination-number --verified-destination-number-id <VDN_ID> --region <REGION>
aws pinpoint-sms-voice-v2 update-rcs-agent --rcs-agent-id <AGENT_ID> --no-deletion-protection-enabled --region <REGION>
aws pinpoint-sms-voice-v2 delete-registration --registration-id <REG_ID> --region <REGION>
aws pinpoint-sms-voice-v2 delete-rcs-agent --rcs-agent-id <AGENT_ID> --region <REGION>
```

Deleting the agent before its registration fails with
`ConflictException: RESOURCE_NOT_EMPTY`. If `delete-rcs-agent` still reports that after
the registration is gone, wait 20 to 30 seconds and run it again; if it persists,
re-check the test devices.

### Troubleshooting

This table covers the agent setup steps. For `cdk deploy`, the dashboard, Amazon Bedrock
and runtime errors, see [Troubleshooting in SETUP.md](SETUP.md#troubleshooting).

| Issue | Fix |
|---|---|
| `ACCENT_COLOR_CONTRAST_INSUFFICIENT` | The selected brand's `accentColor` (`brands.<BRAND>.accentColor`) in `content/brand.md` is too light. Use a darker shade (at least 4.5:1 against white), then follow the `REQUIRES_UPDATES` row. |
| `DESTINATION_COUNTRY_BLOCKED_BY_PROTECT_CONFIGURATION` | Ask the user first. Find the protect configuration with `describe-protect-configurations`, then allow the destination country with `update-protect-configuration-country-rule-set --protect-configuration-id <ID> --number-capability RCS --country-rule-set-updates '{"US":{"ProtectStatus":"ALLOW"}}'` (use the capability of the failing send, and the country of the destination). |
| Registration `REQUIRES_UPDATES` | `describe-registration-field-values --registration-id <REG_ID>` → find `DeniedReason`. Fix the cause, then run `create-registration-version --registration-id <REG_ID>`. A new version does not inherit values, so set every `REQUIRED` and `CONDITIONAL` field again (and any `OPTIONAL` field you set before), including the denied one, and run `submit-registration-version` again. |
| No test device invitation | `TestingAgent.Status` must be `ACTIVE` and at least 120 seconds old when you add the device. Wait up to 20 minutes and check iOS Unknown Senders. If nothing arrives, delete the number (`delete-verified-destination-number --verified-destination-number-id <Id>`, with the `Id` from the "Add a test device" check), wait two minutes, and add it again with `--rcs-agent-id` (see "Add a test device"). |
| Agent shows `Status: TESTING`, or `describe-rcs-agent-country-launch-status` returns an empty list | Expected for a testing agent (see "Getting started" step 4). Top-level `ACTIVE` appears only after a country launch, a separate per-carrier registration that takes months, and messages to verified test devices do not need one. |
| `ServiceQuotaExceededException` with `RCS_AGENTS_PER_ACCOUNT` on `create-rcs-agent` | The account is at its `RcsAgents` quota, and agents from other work count against it. Nothing was created. Tell the user; do not delete an agent to make room unless the user names it. The user can request an increase for quota `L-AE02F3F6` in Service Quotas. |
| `UnrecognizedClientException` | A credentials problem, not a CLI version problem: expired or invalid keys or the wrong profile. Re-run `aws sts get-caller-identity`. |

For `DESTINATION_PHONE_NUMBER_OPTED_OUT`, see "Clear an opt-out entry". For
`Found invalid choice`, see
[AWS CLI with the RCS commands](SETUP.md#aws-cli-with-the-rcs-commands). For Bedrock
errors, see the notes after the Bedrock smoke test under "Prerequisites".
