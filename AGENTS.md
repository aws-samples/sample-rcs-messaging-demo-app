# AnyHealth: instructions for AI coding assistants

AnyHealth is a **fictitious** healthcare brand that demonstrates AWS End User Messaging Rich Communication
Services (RCS) messaging. This file is the playbook for an AI
coding assistant (Kiro, Cursor, OpenAI Codex, Claude Code) that sets up the
demo for a user. It covers the prerequisite checks and steps 2 to 5 of
[SETUP.md](SETUP.md): set up an RCS agent, deploy the stack with AWS Cloud Development
Kit (AWS CDK), and wire up the dashboard. SETUP.md explains each step. This file keeps the
commands, the questions to ask the user and the conditions on which to stop.

If you are a human, follow [SETUP.md](SETUP.md). Its step 2 sends you to the command sections in this file; read "the user" there as you. If you are a coding agent, read on.

> **Attribution:** "RCS Agent Setup" is adapted from
> [`aws-samples/sample-rcs-agent-setup-and-send-messages`](https://github.com/aws-samples/sample-rcs-agent-setup-and-send-messages)
> (MIT-0). See [NOTICE](NOTICE).

## Ground rules

- **Terms.** An *RCS agent* is the AWS resource that sends the messages; you are the AI
  coding assistant. `<prefix>` is the brand name in lowercase, with each run of other
  characters replaced by `-`, leading and trailing `-` removed and the result cut to 20
  characters (`anyhealth` by default, and when nothing is left); the stack is
  `<prefix>-rcs-demo`.
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
  the API key in the chat, and do not read `web/.env` back.
- **Time-outs.** Your shell tool can time out before a long wait ends (the test device
  invitation takes 2 to 20 minutes; `cdk deploy` takes several). Poll in short commands
  or run the long command in the background, and check
  `aws cloudformation describe-stacks --stack-name <prefix>-rcs-demo` before you re-run
  a command that might still be running.

---

## Single source of truth: `content/brand.md`

The brand values for the agent registration (name, accent color, contact details, URLs,
use case) live in the YAML frontmatter of `content/brand.md`. **Read that file first** and
use its values throughout. Do not invent a brand, and do not ask the user for details that
are already present there. If a required value is missing or invalid, ask the user to fix
`content/brand.md`, then continue.

Brand assets are committed in `media/logo.png` (224×224) and `media/banner.png`
(1440×448). The user can replace them: check a replacement against the format, size and
file-size limits in [SETUP.md step 1](SETUP.md#1-configure-your-brand-optional) before
you upload it.

---

## Prerequisites (check these before you start)

Check each item before you create anything; a missing item fails a later step, except
Amazon Bedrock access, which only the AI use case examples and the photo descriptions
need. Report what is missing and stop
instead of working around it. [SETUP.md](SETUP.md#prerequisites) explains each item.

| Need | Check | If missing |
|---|---|---|
| AWS credentials | `aws sts get-caller-identity` | The user signs in (see "Authentication") |
| AWS Command Line Interface (AWS CLI) v2 with the RCS commands | `aws pinpoint-sms-voice-v2 set-rcs-message-spend-limit-override help > /dev/null 2>&1 && echo ok` (offline; tests for the operation itself) | Ask the user to upgrade to AWS CLI v2 2.35.12 or later ([AWS CLI with the RCS commands](SETUP.md#aws-cli-with-the-rcs-commands)) |
| RCS monthly spend limit | "Getting started" step 2 | `MaxLimit` of 1: see step 2 |
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

## RCS Agent Setup

You help the user create an AnyHealth RCS agent on AWS End User Messaging (a testing
agent, which delivers only to registered test devices), add the user's phone as a test
device, and record the agent ID for the deploy. You run every command yourself. The user
provides inputs and confirms results. Follow the ground rules on every error.

### Session state (track as you go)

- `REGION`: the Region chosen under "Region choice" (suggest `us-east-1` if the user has no preference)
- `AGENT_ID` and `REG_ID`: the RCS agent ID (`rcs-XXXX`) and the registration ID
- `PHONE`: the user's phone number (E.164)

### Getting started

When the user asks to set up the RCS agent or the demo, start here.

1. Run `aws sts get-caller-identity`. When it succeeds, send the ground-rules
   confirmation message (account ID, Region, sandbox confirmation, request for the phone
   number) and wait for the reply. Then walk the rest of the "Prerequisites" table,
   including the RCS capability check, and run the Bedrock smoke test only after that reply.
2. Check the RCS spend limit before you create anything (step 3 then confirms RCS
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
3. Check for an existing RCS agent before you create one:

   ```bash
   aws pinpoint-sms-voice-v2 describe-rcs-agents --region <REGION> \
     --query "RcsAgents[].{Id:RcsAgentId,Status:Status,Testing:TestingAgent.Status,TwoWay:TwoWayChannelArn}"
   ```

   - `Status: TESTING` with `Testing: ACTIVE` is the finished state for a testing agent
     ([SETUP.md step 2](SETUP.md#2-set-up-your-rcs-agent)). Tell the user that you found
     it, that creating a new agent is the recommended path, and that
     [reusing it](SETUP.md#use-an-existing-agent) is possible if no other work depends on
     it; the handset then shows that agent's registered brand, not `content/brand.md`.
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
4. Read `content/brand.md` frontmatter. Confirm the brand summary (`brandName`,
   `useCase`, `accentColor`) with the user before you create anything; the account and
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

Paths are under `agentDetails.`. Every value comes from the `content/brand.md`
frontmatter key with the same name, except where noted:

- `REQUIRED`, TEXT: `brandName`, `serviceName`, `senderDisplayName`, `agentDescription`,
  `accentColor` (must pass 4.5:1 contrast against white), `privacyPolicyUrl`,
  `termsAndConditionsUrl`, `monthlyRcsVolume`.
- `REQUIRED`, SELECT: `useCase` (`MULTI_USE`), `averageMonthlyRcsFrequency`,
  `billingCategory` (`CONVERSATIONAL`).
- `REQUIRED`, ATTACHMENT: `logoImage` (upload `media/logo.png`) and `bannerImage` (upload
  `media/banner.png`).
- `CONDITIONAL`, TEXT: `contactPhoneNumber`, `contactPhoneLabel`, `contactEmailAddress`,
  `contactEmailLabel`, `contactWebsite`, `contactWebsiteLabel`.
- `OPTIONAL`, TEXT: `privacyPolicyLabel` ("Privacy Policy") and `termsAndConditionsLabel`
  ("Terms and Conditions").

**Keyword replies.** The testing registration has no keyword fields: `cdk deploy`
registers the `HELP`, `STOP` and `UNSTOP` replies as keywords on the RCS agent (see
"Register the keyword replies"). A country launch registration's `complianceKeywords`
values must match them ([Launching RCS in countries](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-country-launch.html)).

### Create the agent

Run the commands in order, replace the placeholders, and save each ID that the output
returns. The brand comes from the registration, so `create-rcs-agent` takes no display
name.

```bash
aws pinpoint-sms-voice-v2 create-rcs-agent --region <REGION>
aws pinpoint-sms-voice-v2 update-rcs-agent --rcs-agent-id <AGENT_ID> --deletion-protection-enabled --region <REGION>
aws pinpoint-sms-voice-v2 create-registration --registration-type TEST_RCS_LAUNCH_REGISTRATION --region <REGION>
aws pinpoint-sms-voice-v2 create-registration-association --registration-id <REG_ID> --resource-id <AGENT_ID> --region <REGION>
aws pinpoint-sms-voice-v2 create-registration-attachment --attachment-body fileb://media/logo.png --region <REGION>
aws pinpoint-sms-voice-v2 create-registration-attachment --attachment-body fileb://media/banner.png --region <REGION>
```

1. `create-rcs-agent` returns `RcsAgentId` (`AGENT_ID`) and `create-registration` returns
   `RegistrationId` (`REG_ID`). Each `create-registration-attachment` returns an
   attachment ID: save the logo ID and the banner ID (`--attachment-body` and
   `--attachment-url` are mutually exclusive).
2. Set every `REQUIRED` field, the contact fields and the two `OPTIONAL` labels with
   `put-registration-field-value` (see "Registration field reference"), taking every
   value from `content/brand.md`.
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

If `.deploy/agent.json` already exists, show it to the user and ask before you overwrite
it: pointing the deploy at a different agent leaves the old agent with two-way messaging
on. Otherwise write the agent ID and Region into the CDK's local, gitignored config so
that `cdk deploy` picks them up with nothing hardcoded:
```bash
mkdir -p .deploy
cat > .deploy/agent.json <<'JSON'
{ "rcsAgentId": "<AGENT_ID>", "region": "<REGION>" }
JSON
```
Then tell the user: **"The RCS agent is ready. Next I add your phone as a test device,
then deploy the demo."**

### Add a test device
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

Start here after `TestingAgent.Status` is `ACTIVE` and `.deploy/agent.json` exists.
[SETUP.md step 3](SETUP.md#3-deploy-the-infrastructure) describes what the deploy creates
and the `-c` options. `cdk deploy` asks for confirmation before it applies changes that
broaden AWS Identity and Access Management (IAM) permissions, and a shell with no
interactive terminal cannot answer (CDK stops with
`terminal (TTY) is not attached so we are unable to get a confirmation from the user`),
so show the user the IAM changes in the diff first:

```bash
(cd cdk && npm ci)
(cd cdk && npx cdk bootstrap)
(cd cdk && npx cdk diff)
```

Run this only after the user approves the diff:

```bash
(cd cdk && npx cdk deploy --require-approval never)
```

1. `cdk bootstrap` runs once per account and Region. The first run creates the
   CDKToolkit stack (an Amazon Simple Storage Service (Amazon S3) bucket, an Amazon
   Elastic Container Registry (Amazon ECR) repository and IAM roles), so tell the user
   first, and ask before you run it if the organization customized CDK bootstrapping.
2. Repeat every `-c` option that the user chose (for example `bedrockRegion`,
   `bedrockModelId`, `registerKeywords` or `smsFallbackNumber`) on `diff` and `deploy`.

The deploy prints several outputs. Note three: **`ApiUrl`**, **`ApiKeySecretName`** and
**`KeywordsStatus`**.
`KeywordsStatus` should start with `ok` (or `skipped` if you turned the keyword step
off). `error (...)` means the replies were not all registered; the deploy itself still
succeeded (see "Register the keyword replies").

### Wire up the dashboard

An API key gates every route except the few that are open on purpose
([SECURITY.md](SECURITY.md#routes-that-need-the-api-key)), so the dashboard needs both
the URL and the key. Write both to `web/.env` with one command that never prints the
key, and do not read `web/.env` back:

```bash
(umask 077; KEY=$(aws secretsmanager get-secret-value --secret-id <ApiKeySecretName> --query SecretString --output text --region <REGION>) && printf 'VITE_API_URL=%s\nVITE_API_KEY=%s\n' '<ApiUrl>' "$KEY" > web/.env)
(cd web && npm ci)
```

`web/.env` is gitignored; never commit it. Run the dashboard only with `npm run dev` on
the user's own machine: `npm run build` compiles `VITE_API_KEY` into the bundle, so do
not host or share a `web/dist` build
([Why the dashboard is local-only](SECURITY.md#why-the-dashboard-is-local-only)).
`npm run dev` does not exit. Start it in the background, or ask the user to run
`(cd web && npm run dev)` in a second terminal, and read the URL from Vite's output
(<http://localhost:5173> unless that port is busy).

Then hand over to the user: they open the dashboard, find their phone on the
**Recipients** tab (**Add recipient** registers a new number as a test device and sends
the invitation; for a number that is already registered it only saves the name), confirm
`VERIFIED`, set the target and send a use case example. Do not call
the dashboard API or send a use case example yourself.

---

## Reference: optional steps, teardown, troubleshooting

Use these sections when a step calls for them.

### Register the keyword replies

**`cdk deploy` registers them for you.** The wiring custom resource
(`lambda/custom_resources/eum_wiring.py`) writes three keywords on the agent right after
it enables two-way messaging, with text built from `content/brand.md`: `HELP` (action
`AUTOMATIC_RESPONSE`), `STOP` (`OPT_OUT`) and `UNSTOP` (`OPT_IN`). The service answers these keywords itself, and the deployed bot
stays silent for them
([Keywords, and where a keyword is answered](docs/architecture.md#21-keywords-and-where-a-keyword-is-answered)).

**What the deploy overwrites.** The deploy writes `HELP` or `STOP` only while the keyword
is empty, still the AWS default, or still the text the previous deploy wrote, and it
creates `UNSTOP` only when it is absent (or refreshes it the same way). A reply identical
to the one it would write is `unchanged`; any other reply stays, and `KeywordsStatus`
says `kept (set by you)`. Other keywords are never touched. A new stack has no record
of what an earlier stack wrote: after a
`brandName` change that alters the prefix ([Editing the demo](README.md#editing-the-demo))
or after `cdk destroy` and a fresh deploy, it treats the replies already on the agent as
the user's, and the same rules apply to them.

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

`<brandName>`, `<contactPhoneNumber>` and `<contactEmailAddress>` come from
`content/brand.md`. The Settings tab shows `HELP` and `STOP` read-only, so use the CLI to
set their text by hand.

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
tell the user that `npx cdk destroy` deletes the stack `<prefix>-rcs-demo` and, once the
user approves, run:

```bash
(cd cdk && npx cdk destroy --force)
```

[SETUP.md](SETUP.md#teardown) explains what the destroy leaves behind and the two-way
caveat. Ask the user whether this RCS agent was created for this demo and whether
anything else uses it. If it was reused or is shared, stop here unless the user asks you
to delete it. Otherwise delete the RCS agent resources in this order, each command only
after the user approves it. If you no longer have `REG_ID`, read it from
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
| `ACCENT_COLOR_CONTRAST_INSUFFICIENT` | `accentColor` in `content/brand.md` is too light. Use a darker shade (at least 4.5:1 against white), then follow the `REQUIRES_UPDATES` row. |
| `DESTINATION_COUNTRY_BLOCKED_BY_PROTECT_CONFIGURATION` | Ask the user first. Find the protect configuration with `describe-protect-configurations`, then allow the destination country with `update-protect-configuration-country-rule-set --protect-configuration-id <ID> --number-capability RCS --country-rule-set-updates '{"US":{"ProtectStatus":"ALLOW"}}'` (use the capability of the failing send, and the country of the destination). |
| Registration `REQUIRES_UPDATES` | `describe-registration-field-values --registration-id <REG_ID>` → find `DeniedReason`. Fix the cause, then run `create-registration-version --registration-id <REG_ID>`. A new version does not inherit values, so set every `REQUIRED` and `CONDITIONAL` field again (and any `OPTIONAL` field you set before), including the denied one, and run `submit-registration-version` again. |
| No test device invitation | `TestingAgent.Status` must be `ACTIVE` and at least 120 seconds old when you add the device. Wait up to 20 minutes and check iOS Unknown Senders. If nothing arrives, delete the number (`delete-verified-destination-number --verified-destination-number-id <Id>`, with the `Id` from the "Add a test device" check), wait two minutes, and add it again with `--rcs-agent-id` (see "Add a test device"). |
| Agent shows `Status: TESTING`, or `describe-rcs-agent-country-launch-status` returns an empty list | Expected for a testing agent (see "Getting started" step 3). Top-level `ACTIVE` appears only after a country launch, a separate per-carrier registration that takes months, and messages to verified test devices do not need one. |
| `UnrecognizedClientException` | A credentials problem, not a CLI version problem: expired or invalid keys or the wrong profile. Re-run `aws sts get-caller-identity`. |

For `DESTINATION_PHONE_NUMBER_OPTED_OUT`, see "Clear an opt-out entry". For
`Found invalid choice`, see
[AWS CLI with the RCS commands](SETUP.md#aws-cli-with-the-rcs-commands). For Bedrock
errors, see the notes after the Bedrock smoke test under "Prerequisites".
