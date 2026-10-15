# AnyHealth — Setup Guide

Step-by-step from zero to a working, fictitious company-branded demo of AWS End User Messaging Rich Communication Services (RCS) in your own AWS account.

We recommend you review the [docs/tutorial.md](docs/tutorial.md) (what RCS is and how the demo works) and [docs/architecture.md](docs/architecture.md) (diagrams and per-use-case-example flows) before you deploy.

Clone this repository and open a terminal in its folder; that folder is the repository root. Run every command from the repository root. A command that needs `cdk/` or `web/` runs in a subshell, for example `(cd cdk && npx cdk deploy)`, so the next command still starts at the root. The commands assume bash or zsh on macOS, Linux or Windows Subsystem for Linux. The guide has these waits: the RCS registration (about 5 minutes), a two-minute pause before you add the test device, the test device invitation (2 to 20 minutes) and the deploy (several minutes).

<a id="set-this-up-using-an-ai-coding-agent"></a>
## Set this up using an AI coding assistant

You can run every step yourself, or have an AI coding assistant (recommended) run steps 2 to 5 while you review and approve each command. Both routes use the same steps and the same commands.

- **Human.** Start at [Prerequisites](#prerequisites), then follow steps 1 to 6. In step 2, you run the commands in [AGENTS.md](AGENTS.md); read "the user" there as you.
- **AI coding assistant.** [AGENTS.md](AGENTS.md) is the step-by-step playbook that the assistant follows to check your prerequisites, set up the RCS agent, deploy the stack with the AWS Cloud Development Kit (AWS CDK) and wire up the dashboard. The assistant does steps 2 to 5. You do step 1 (the optional brand edit) and step 6, and the parts only you can do: your AWS sign-in, your phone number, and tapping **Make me a tester** on the handset.

### Start your AI coding assistant

Open the repository folder in your assistant, and paste the [prompt](#the-prompt).

**Kiro**

- Install the IDE from [kiro.dev](https://kiro.dev), or the CLI with `curl -fsSL https://cli.kiro.dev/install | bash`
  (macOS and Linux), `brew install kiro-cli` (macOS), or `irm 'https://cli.kiro.dev/install.ps1' | iex`
  (Windows PowerShell), then `kiro-cli login`.
- Open the folder with `kiro .` (IDE), or `cd` into it and run `kiro-cli chat` (CLI).
- Kiro loads `AGENTS.md` from the repository root automatically as
  [steering](https://kiro.dev/docs/steering), and this repository also ships `.kiro/steering/anyhealth.md`. Trust
  the folder when Kiro asks, so that the project's steering files load.
- Keep Kiro asking before it runs commands: do not use `--trust-all-tools` or `/tools trust-all`
  (see [Kiro CLI permissions](https://kiro.dev/docs/cli/v3/permissions/)). A `cdk deploy`
  can take several minutes. In the IDE, the `kiroAgent.terminalCommandTimeout` setting sets how long an
  assistant-run terminal command can run (the default is 120000 ms, two minutes); raise it before the deploy.

**Claude Code**

- Install with `curl -fsSL https://claude.ai/install.sh | bash` (macOS, Linux and WSL),
  `irm https://claude.ai/install.ps1 | iex` (Windows PowerShell), or `brew install --cask claude-code`.
- `cd` into the folder and run `claude --permission-mode default`, so that Claude asks before most actions that
  edit files, run shell commands or reach the network.
- Claude Code reads `AGENTS.md` when there is no `CLAUDE.md`, `.claude/CLAUDE.md` or `CLAUDE.local.md` in the
  folder or in any parent folder (your own `~/.claude/CLAUDE.md` does not count); see
  [Claude Code memory documentation](https://code.claude.com/docs/en/memory#agents-md). This repository has none. It needs version 2.1.277 or
  later, or 2.1.281 or later for some sessions, such as those on Amazon Bedrock or with telemetry disabled;
  `claude --version` shows yours. If you add a `CLAUDE.md` of your own, start it with the line `@AGENTS.md` so the
  playbook still loads. From version 2.1.280, `/memory` and `/context` list the `AGENTS.md` that Claude read, so you
  can confirm that it loaded.

**Other assistants**

AGENTS.md is an open format ([agents.md](https://agents.md)) that many AI coding assistants read from the
repository root. For the following assistants, the vendor's page is linked.

| Assistant | Picks up AGENTS.md | Start it | Keep approval on |
|---|---|---|---|
| Cursor | Yes, in the editor ([Cursor rules documentation](https://cursor.com/docs/rules)) and the CLI ([using the Cursor CLI](https://cursor.com/docs/cli/using)) | Open the folder and use Agent, or run `agent` in the folder (CLI) | In **Settings** > **Agents** > **Approvals & Execution**, choose **Allowlist** (a command that is not on your allowlist asks first) or **Auto-review** (a classifier approves some commands without a prompt), not **Run Everything** ([Cursor run modes](https://cursor.com/docs/agent/security/run-modes)). In the CLI, avoid `--force` and `--yolo` ([Cursor CLI parameters](https://cursor.com/docs/cli/reference/parameters)) |
| OpenAI Codex | Yes, from the repository root ([AGENTS.md guide](https://learn.chatgpt.com/docs/agent-configuration/agents-md)) | Run `codex` in the folder | Do not use full access. Its default sandbox keeps the network off, so expect approval prompts for the AWS and CDK commands ([approvals and security](https://learn.chatgpt.com/docs/agent-approvals-security)) |
| GitHub Copilot | Yes: VS Code agent mode (setting [`chat.useAgentsMdFile`](https://code.visualstudio.com/docs/agents/reference/ai-settings), on by default; [custom instructions](https://code.visualstudio.com/docs/agent-customization/custom-instructions)) and [Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/use-copilot-cli/overview) | Open the folder in VS Code, or run `copilot` in the folder | Keep the permission level on **Manual permissions** and do not select the Autopilot mode; avoid **Allow all**, `--allow-all` and `--yolo` ([VS Code approvals](https://code.visualstudio.com/docs/agents/run/approvals)) |
| Devin Desktop (formerly Windsurf) | Yes, Devin Local reads it ([Devin Local documentation](https://docs.devin.ai/desktop/devin-local)) | Open the folder in Devin Desktop | Keep command approvals on (Ask rules) and avoid allow-everything permission rules |
| Gemini CLI | Yes, once `context.fileName` lists it: add `"context": {"fileName": ["AGENTS.md", "GEMINI.md"]}` to `~/.gemini/settings.json` ([Gemini CLI GEMINI.md documentation](https://geminicli.com/docs/cli/gemini-md/)) | Run `gemini` in the folder | Use `--approval-mode default`; avoid `--approval-mode yolo` and `--yolo` ([Gemini CLI reference](https://geminicli.com/docs/cli/cli-reference/)) |
| Antigravity CLI | Yes ([Antigravity rules documentation](https://antigravity.google/docs/rules)) | Run `agy` in the folder | Leave shell commands on Ask (`/permissions`) and avoid `--dangerously-skip-permissions` ([execution modes](https://antigravity.google/docs/cli/modes)) |

An assistant that does not read `AGENTS.md` by itself works as well: open the file in the session and paste the prompt.

### The prompt

Replace `<PROFILE>` with your AWS Command Line Interface (AWS CLI) profile name and `<REGION>` with the Region you deploy to. If you do not use a named profile, replace the profile line with "Use my default AWS credentials." AGENTS.md suggests `us-east-1`; use another Region only if you have a data-residency requirement or an existing RCS agent there.

```text
Read AGENTS.md in full, then set up my AnyHealth RCS demo by following it step by step.
Use my AWS profile <PROFILE>.
Use Region <REGION>.
Follow the ground rules in AGENTS.md, and ask me before anything it tells you to ask me about.
```

### Who does what

| Step | The AI coding assistant | You |
|---|---|---|
| Prerequisites | Checks your AWS credentials, a CLI that has the RCS commands, the RCS spend limit, Amazon Bedrock access, Node.js, and `python3` or Docker | Fix what is missing. Request the spend-limit increase if `MaxLimit` is 1, and complete the Anthropic use case form if the Bedrock check is denied |
| RCS agent | Reads `content/brand.md`, lists your existing RCS agents and tells you about a finished one, creates a new RCS agent and its registration unless you choose to reuse that one, waits until `TestingAgent.Status` is `ACTIVE`, and records `.deploy/agent.json`. Before it creates anything, it points you to the RCS pricing page, and sets a monthly RCS spend cap if you want one, after you approve the command | Confirm the AWS account, the brand summary and the Region before it creates anything. Use a dedicated RCS agent if you can (see [Teardown](#teardown)) |
| Test device | Adds your phone as a test device, two minutes after `TestingAgent.Status` is `ACTIVE` | Accept the invitation from RBM Tester Management on the phone. It arrives within 2 to 20 minutes; on an iPhone, check **Unknown Senders** |
| Deploy | Runs `cdk bootstrap`, shows the `cdk diff`, runs `cdk deploy`, and reports `ApiUrl`, `ApiKeySecretName` and `KeywordsStatus` | Review the `cdk diff` and approve the deploy command. The deploy takes several minutes. Check the `KeywordsStatus` output ([Keyword replies](#keyword-replies)) |
| Dashboard | Writes the API key to `web/.env` (gitignored) with a command that does not print it, and starts the dashboard (or tells you to run `npm run dev` in a second terminal) | Open <http://localhost:5173> and find your phone on the **Recipients** tab (if the assistant added it, you can name it by editing its **User** cell). Confirm the status is **VERIFIED**, set it as the target, and send a use case example |

### Keep it safe

- Read each command before you approve it, especially anything that contains `delete`, `destroy`, `put-keyword`, `update-rcs-agent`, `update-protect-configuration-country-rule-set` or `set-rcs-message-spend-limit-override`.
- Use a dedicated RCS agent if you can. The deploy repoints an existing agent's two-way messaging inside `cdk deploy`, so no `update-rcs-agent` command is shown for you to approve; see the two-way caveat in [Teardown](#teardown).
- Keep your assistant's approval mode on, and avoid its approve-everything modes for this task.
- Keep credentials out of the chat. `web/.env` is gitignored; never commit it.
- To tear everything down, ask the assistant to follow [Teardown](#teardown) here and [Teardown in AGENTS.md](AGENTS.md#teardown).

### If a step fails

The assistant stops at a failing command. [AGENTS.md](AGENTS.md#troubleshooting) has a troubleshooting table for the RCS agent setup steps, and [Troubleshooting](#troubleshooting) covers the deploy and the dashboard. If a command times out in your assistant, the AWS CloudFormation update might still be running: check the stack status before you run it again. If a command fails with an `ExpiredToken` or `ExpiredTokenException` error, refresh your credentials and tell the assistant to continue; it does not need to start over.

## Prerequisites

Check these before you create anything. Each missing item fails a later step, except Amazon Bedrock access, which only the AI use case examples and the photo descriptions need. Start two things first, because they need you and can take time: request an RCS monthly spend limit increase if `MaxLimit` is 1, and complete the one-time Anthropic use case form if you want the AI use case examples.

- An AWS account that you own and use for sandbox or development work, with credentials and a Region: [Credentials, profile and Region](#credentials-profile-and-region).
- AWS CLI v2 with the RCS commands: [AWS CLI with the RCS commands](#aws-cli-with-the-rcs-commands).
- An RCS monthly spend limit with `MaxLimit` above 1, so that you can send more than a few dozen messages (the deploy and **Device preview** work at $1): [RCS monthly spend limit](#rcs-monthly-spend-limit).
- Amazon Bedrock access to the default model (AI use case examples and photo descriptions only): [Amazon Bedrock access and model choice](#amazon-bedrock-access-and-model-choice).
- Node.js, and `python3` with `pip` or Docker: [Node.js, python3 and Docker](#nodejs-python3-and-docker).
- An RCS-capable test phone: Android with RCS chat enabled, or an iPhone on iOS 18 or later.

### Credentials, profile and Region

- **Use an account you own for sandbox or development work.** The commands in this guide create and delete resources, so use an account where that is acceptable. The guide needs `AdministratorAccess` or an equivalent identity, including permissions for the `sms-voice` actions that the RCS commands call ([Required IAM actions](#required-iam-actions)).
- **Configure credentials.** `aws sts get-caller-identity` should print your account. Use whichever method your account is set up for: `aws configure` for AWS Identity and Access Management (IAM) keys, or `aws sso login --profile <PROFILE>` for AWS IAM Identity Center. Prefer short-lived credentials. If you use a named profile, export `AWS_PROFILE=<PROFILE>` once; it applies to `aws` and `cdk`. Otherwise append `--profile <PROFILE>` to every `aws` command and set `AWS_PROFILE` for `cdk`.
- **Credentials can expire.** This guide has waits of up to 20 minutes. If a command fails with an `ExpiredToken` or `ExpiredTokenException` error, refresh your credentials and pick up where you left off. Do not restart the guide, because the RCS agent and registration already exist.
- **Set your Region once.** An RCS agent is a Regional resource, and the stack deploys to the Region in `.deploy/agent.json`, not to your CLI default. Use `us-east-1` unless you have a data-residency requirement or an existing RCS agent in another Region, and make sure that RCS in AWS End User Messaging and Amazon Bedrock are both available there. The optional Video Visit example also calls Amazon Chime SDK Meetings in the deploy Region, which is not available in every Region (see [Video Visit](docs/architecture.md#414-video-visit--webrtc-in-the-webview-experimental)). Run the following once, or append `--region <REGION>` to every command:

  ```bash
  export AWS_REGION=<REGION>
  ```

### AWS CLI with the RCS commands

Install AWS CLI v2 2.35.12 or later. The RCS commands were added to `pinpoint-sms-voice-v2` in 2026 (the agent commands in 2.34.21, and the rich-message and RCS spend-limit commands in 2.35.12). This offline check tests for the operation itself and needs no credentials and no permissions:

```bash
aws pinpoint-sms-voice-v2 set-rcs-message-spend-limit-override help > /dev/null 2>&1 \
  && echo "OK: this CLI has the RCS commands" \
  || echo "Upgrade the AWS CLI: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
```

A build without the commands reports `argument operation: Found invalid choice 'describe-rcs-agents'` when you run an RCS command; the message is about the CLI version, not about your credentials. The commands in this guide are written for AWS CLI v2.

### RCS monthly spend limit

RCS sends stop when the account reaches its monthly RCS spend limit, so confirm that the limit covers your testing before you create anything ([RCS billing and pricing model](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-billing.html)):

```bash
aws pinpoint-sms-voice-v2 describe-spend-limits --region <REGION> \
  --query "SpendLimits[?Name=='RCS_MESSAGE_MONTHLY_SPEND_LIMIT']"
```

A new account often reports `EnforcedLimit: 1, MaxLimit: 1`, which is $1 per month, but the value varies by account and Region, so read yours. `MaxLimit` is the ceiling that AWS sets: the override operation sets a cap at or below it, and raising `MaxLimit` takes a request. At $1 you can send a few dozen messages (rich cards and media cost more than plain text), and then every send fails with `ServiceQuotaExceededException` and the reason `MONTHLY_SPEND_LIMIT_REACHED_FOR_RCS`. A $1 limit was observed whether the Region reported `SANDBOX` or `PRODUCTION` as its account tier.

**If `MaxLimit` is 1, request an increase before you start**, for the Region you deploy to (the limit and its quota are per Region). Use Service Quotas (choose that Region, then **AWS End User Messaging SMS**, `RcsMessageMonthlySpend`, which is adjustable) or an AWS Support case that names the Region. Requests above what AWS can approve automatically go to AWS Support for review, so allow days. After the increase, run the command again. `describe-spend-limits` shows the new `MaxLimit`; if `EnforcedLimit` is still lower, set it with `aws pinpoint-sms-voice-v2 set-rcs-message-spend-limit-override --monthly-limit <DOLLARS> --region <REGION>`. The deploy, the dashboard and **Device preview** work while the limit is $1; only real sends fail.

**Cost guardrail.** The same override can lower the cap: set it to the most you are willing to spend on RCS in a month (at or below `MaxLimit`), and the service stops sending RCS messages when it reaches the enforced limit. `delete-rcs-message-spend-limit-override` resets it to `MaxLimit`. The override covers RCS only (SMS, MMS and voice have separate limits) and applies to every RCS agent in the account and Region. For what RCS bills and for the registration fees that RCS agents can carry, see [Cost](README.md#cost).

### Amazon Bedrock access and model choice

Only the AI use case examples (Benefits & Coverage Q&A, Find a Provider and the photo description in Classify a Photo and Secure Document Upload) need Amazon Bedrock access to `bedrockModelId` (default `global.anthropic.claude-sonnet-4-6`) in `bedrockRegion`; without it the rest of the demo works and the photo description is left out.

Bedrock serverless models are available by default, so there is no Model access page to enable. Anthropic models add a **one-time use case form**, per account or once at the AWS Organizations management account, which has to be submitted before the first invocation. The form applies across commercial Regions, except opt-in Regions, where you submit it again. To submit it, open an Anthropic model from the model catalog in the Amazon Bedrock console playground, or call `PutUseCaseForModelAccess` (`aws bedrock put-use-case-for-model-access --form-data ...`, with the form as base64 JSON). See [Request access to models](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html). The form asks for company name, website, industry and use cases, and you submit it yourself. The first invocation also subscribes the account to the model through AWS Marketplace, which needs `aws-marketplace:Subscribe` and a valid payment method. This stack's AWS Lambda roles have no Marketplace permissions, so make that first call yourself with your admin credentials. Verify with a real invocation, because listing inference profiles only proves that a profile exists in the Region, not that your account can call it:

```bash
aws bedrock-runtime converse --region <BEDROCK_REGION> \
  --model-id global.anthropic.claude-sonnet-4-6 \
  --messages '[{"role":"user","content":[{"text":"Reply with OK."}]}]' \
  --inference-config '{"maxTokens":16}' \
  --query 'output.message.content[0].text' --output text
```

`<BEDROCK_REGION>` is your deploy Region unless you override `bedrockRegion`; substitute your `bedrockModelId` override too if you set one. A reply means the request succeeded. Amazon Bedrock completes the AWS Marketplace subscription in the background (up to 15 minutes), so run the command again after a few minutes before you deploy. An `AccessDeniedException` is covered in [Troubleshooting](#troubleshooting).

The default is the **`global.`** cross-Region inference profile. You can call it from every Region in which Amazon Bedrock offers Claude Sonnet 4.6 (see the [model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-sonnet-4-6.html)), so you do not need a model override because you deploy outside the US. `bedrockRegion` defaults to the deploy Region; to call Amazon Bedrock in another Region, pass `-c bedrockRegion=<BEDROCK_REGION>`.

Override the model only if you have a **data-residency requirement**: use your geography's profile instead of `global.`, and list what your Region offers instead of guessing the prefix:

```bash
aws bedrock list-inference-profiles --region <BEDROCK_REGION> --type-equals SYSTEM_DEFINED \
  --query "inferenceProfileSummaries[?contains(inferenceProfileId, 'anthropic')].inferenceProfileId"
```

For this model, `us.`, `eu.`, `au.` and `jp.` profiles exist and `apac.` does not. `au.` is available from ap-southeast-2, ap-southeast-4 and ap-southeast-6, and `jp.` from ap-northeast-1 and ap-northeast-3. In a Region that no geography profile lists (for example ap-southeast-1), `global.` is the available profile. The `us.` profile can also be called from `ca-central-1` and `ca-west-1`, but it routes requests to US Regions as well as the calling Canadian Region, so confirm that a North America geography meets your requirement. Pass the profile as `-c bedrockModelId=<id from that list>` on both `cdk diff` and `cdk deploy`. A profile with no source Region in `bedrockRegion` still deploys cleanly and then fails the AI use case examples at runtime with a validation error, so `cdk synth` prints a warning if it spots that combination.
### Node.js, python3 and Docker

- **Node.js 22 or later.** The AWS CDK requires Node.js 22.x or later ([AWS CDK prerequisites](https://docs.aws.amazon.com/cdk/v2/guide/prerequisites.html)), and recommends a version in active long-term support, so choose the newest LTS release. If you use nvm, run `nvm use` in the repository root: `.nvmrc` selects 22.
- **`python3` with `pip`, or Docker.** The AWS CDK builds the two Lambda dependency layers with local `pip`, which downloads Linux wheels, and falls back to Docker bundling if the local build fails. The functions and layers target the Python 3.14 Lambda runtime, and `pip` selects wheels for that version (`--python-version 3.14`), so your local `python3` does not need to be 3.14. The local build needs `python3` 3.10 or later, or `pip` 24.2 or later (`python3 -m pip --version` shows both); on the Python 3.9 that ships with the Xcode command line tools, it fails with `Package 'boto3' requires a different Python`. If neither holds, upgrade `pip`, set `PYTHON=/path/to/python3` to a newer interpreter, or use Docker.

### Required IAM actions

`AdministratorAccess` covers everything in this guide. `cdk deploy` also needs AWS CloudFormation, IAM, AWS Lambda, Amazon Simple Storage Service (Amazon S3), Amazon DynamoDB, Amazon Simple Notification Service (Amazon SNS), AWS Key Management Service (AWS KMS), Amazon API Gateway, AWS Secrets Manager and Amazon CloudWatch Logs permissions, so a scoped-down policy is not practical here. These `sms-voice` actions (the actions behind the `pinpoint-sms-voice-v2` AWS CLI commands) cover the commands in this guide and the registration recovery steps: `CreateRcsAgent`, `UpdateRcsAgent`, `DeleteRcsAgent`, `DescribeRcsAgents`, `DescribeRcsAgentCountryLaunchStatus`, `CreateRegistration`, `CreateRegistrationVersion`, `DeleteRegistration`, `CreateRegistrationAssociation`, `CreateRegistrationAttachment`, `PutRegistrationFieldValue`, `SubmitRegistrationVersion`, `DescribeRegistrationFieldValues`, `DescribeRegistrationFieldDefinitions`, `CreateVerifiedDestinationNumber`, `DescribeVerifiedDestinationNumbers`, `DeleteVerifiedDestinationNumber`, `SendTextMessage`, `PutKeyword`, `DescribeKeywords`, `DescribeProtectConfigurations`, `UpdateProtectConfigurationCountryRuleSet`, `DescribeOptedOutNumbers`, `DeleteOptedOutNumber`, `DescribeSpendLimits`, `SetRcsMessageSpendLimitOverride` and `DeleteRcsMessageSpendLimitOverride`, plus `DescribePhoneNumbers` for the optional `-c smsFallbackNumber` check and `DeleteEventDestination` and `DeleteConfigurationSet` for the leftover cleanup in [Teardown](#teardown). If you narrow CloudFormation's execution role, see [Permissions the deploy needs for the log](SECURITY.md#permissions-the-deploy-needs-for-the-log).

<a id="1-configure-your-brand-optional"></a>
## 1. Configure your brand (optional - replaces the demo fictitious branding)

This step is optional, as the demo deploys as-is with well-formed, fictitious branding and assets for AnyHealth. However, if you wish to change any of the default fictitious branding, follow these instructions before setting up your RCS test agent (step 2).

Edit `content/brand.md` frontmatter (name, `accentColor`, contact info, URLs) and the other `content/*.md` files. Replace the placeholder art in `media/` if you like. Registration checks the images, so keep `media/logo.png` a PNG with transparency at 224×224 pixels and 50 KB or smaller, and `media/banner.png` at 1440×448 pixels and 200 KB or smaller, and keep `accentColor` dark enough to pass a 4.5:1 contrast ratio against white. To restore the AnyHealth placeholder art, run `scripts/gen-placeholder-assets.sh`. It rewrites the images in `media/` and `web/public/favicon.png` with the AnyHealth wordmark and accent color, and it does not read `content/brand.md`, so it replaces art that you changed. It needs `rsvg-convert` (`brew install librsvg`).

Four design guidelines, confirmed on real handsets. See
[Managing RCS agents](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-agents.html)
for the transparency and Android-only points, and
[RCS best practices](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-best-practices.html)
for rendering differences between Android and iOS. The **Settings** tab restates them next
to your live assets:

- **The logo must be a PNG with transparency, and is rendered circular** in the
  thread and on the agent profile, on both platforms. A square logo loses its
  corners, so design inside the inscribed circle.
- **The banner appears on the Android agent profile only.** It is absent from the
  iOS info sheet entirely, so it is not the place for anything a recipient must see.
- **The circular logo avatar is overlaid on the banner's bottom-center.** Keep
  that third clear, because a centered wordmark gets covered by your own logo. The
  placeholder banner is left-anchored for exactly this reason.
- **Check how your handsets show the agent before a demo.** In this sample's tests with a testing agent, the iOS agent info sheet showed "Verified by Google" and Android added "This is an RCS for Business chat." to the thread; Android showed no verified-badge graphic. Your logo and display name rendered on both platforms. This sample did not test a country-launched agent.

`senderDisplayName` is the string that appears on the handset. The console's friendly
name is a console-only label stored as a tag, and recipients do not see it
([Managing RCS agents](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-agents.html)).
Some registered brand assets are fixed once the registration is submitted
([Editing the demo](README.md#editing-the-demo)), so settle the assets first.

Card and product tiles in `media/` are deliberately **wordless**; the hero image on the
welcome cards (`media/welcome-hero.png`) is the one branded exception. Card media renders
directly above the card's `Title`, so a label baked into a tile shows up twice
on the handset, and Android aggregates every tile into a media gallery on the
agent profile, where captioned images crowd the page. If you replace
the art, keep the text in the payload rather than in the pixels.

<a id="2-create-your-rcs-test-agent"></a>
## 2. Set up your RCS agent

This step ends with an RCS agent whose `TestingAgent.Status` is `ACTIVE`, your phone registered as a test device, and `.deploy/agent.json` written. A testing agent delivers only to registered test devices and needs no carrier approval, which is all this demo needs. If you use an AI coding assistant, it does this step ([Set this up using an AI coding assistant](#set-this-up-using-an-ai-coding-assistant)). RCS agents can carry registration fees that are billed separately from messages; check [Cost](README.md#cost) before you create one.

<a id="use-an-existing-agent"></a>
> **Already have an RCS testing agent in this account and Region?** Most people do not, and creating a new agent (next) is the recommended path. To reuse an existing agent instead, first check what you have:
>
> ```bash
> aws pinpoint-sms-voice-v2 describe-rcs-agents --region <REGION> \
>   --query "RcsAgents[].{Id:RcsAgentId,Status:Status,Testing:TestingAgent.Status}"
> ```
>
> A reusable agent shows `"Status": "TESTING"` and `"Testing": "ACTIVE"`, which **is the finished state** for this demo: the testing registration is approved and no country launch has been completed ([Managing RCS agents](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-agents.html#rcs-agents-lifecycle)). An empty `CountryLaunchStatus: []` from `describe-rcs-agent-country-launch-status` is the expected result for a testing agent. Country launch is a separate, per-carrier process that can take weeks to months, and this demo does not need it to operate with up to 10 test devices ([Launching RCS in countries](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-country-launch.html)).
>
> Then check which test devices the agent already has:
>
> ```bash
> aws pinpoint-sms-voice-v2 describe-verified-destination-numbers --region <REGION> \
>   --query 'VerifiedDestinationNumbers[].{Id:VerifiedDestinationNumberId,Phone:DestinationPhoneNumber,Status:Status,Agent:RcsAgentId}'
> ```
>
> A `PENDING` number with no `Agent` value that you added as an RCS test device was created without `--rcs-agent-id`, so no invitation is sent for it. Delete it with `aws pinpoint-sms-voice-v2 delete-verified-destination-number --verified-destination-number-id <ID> --region <REGION>`, then add it again with the agent ID (the `create-verified-destination-number` command in [AGENTS.md](AGENTS.md#add-a-test-device)). Numbers that you verified for the SMS sandbox also show no `Agent` value; leave those in place.
>
> To reuse the agent, write its ID and Region into `.deploy/agent.json`, then go to [step 3](#3-deploy-the-infrastructure). Both keys are required, and `<REGION>` must be the Region the agent lives in. Edit the placeholders in the following block by hand, because the heredoc delimiter is quoted:
>
> ```bash
> mkdir -p .deploy
> cat > .deploy/agent.json <<'JSON'
> { "rcsAgentId": "<AGENT_ID>", "region": "<REGION>" }
> JSON
> ```
>
> Or pass both with `-c` (see [Deploy options](#deploy-options), which also covers `cdk bootstrap`): `-c rcsAgentId=<AGENT_ID> -c region=<REGION>`. `cdk deploy` stops with an error instead of falling back to your CLI default Region, because a stack deployed to a different Region than its agent looks healthy and then fails on every send.
>
> The handset shows the reused agent's registered display name, logo and colors, not the values in `content/brand.md`. **Read the two-way caveat in [Teardown](#teardown) first** if the agent is used for anything else, because this stack reconfigures two-way messaging on it. If your phone is not listed with Status `VERIFIED` in the check above, add it first: run the commands under "Add a test device" in [AGENTS.md](AGENTS.md#add-a-test-device), or choose **Add recipient** on the **Recipients** tab in step 6.

### Create a new agent

Paste the [prompt](#the-prompt) into your AI coding assistant. The assistant follows [AGENTS.md](AGENTS.md) and:

- creates the RCS agent and submits a `MULTI_USE` testing registration using your `content/brand.md` values and `media/` assets,
- polls until `TestingAgent.Status` is `ACTIVE`,
- writes `{"rcsAgentId": "...", "region": "..."}` to `.deploy/agent.json`,
- adds your phone as a test device (accept the invitation on your device; on an iPhone, check **Unknown Senders**).

To run these commands yourself instead, read "the user" in [AGENTS.md](AGENTS.md) as you, skip its "Ground rules" and "Getting started" sections, and run the sections in this order. The sequence is about 30 commands, 21 of them `put-registration-field-value` calls:

1. [Registration field reference](AGENTS.md#registration-field-reference-test_rcs_launch_registration)
2. [Create the agent](AGENTS.md#create-the-agent)
3. [Poll until the testing agent is active](AGENTS.md#poll-until-the-testing-agent-is-active)
4. [Record the agent ID for deployment](AGENTS.md#record-the-agent-id-for-deployment)
5. [Add a test device](AGENTS.md#add-a-test-device)

Replace every `<PLACEHOLDER>` in those commands by hand before you run them: the `.deploy/agent.json` heredoc uses a quoted delimiter, so a pasted placeholder is written literally.

The prompt covers the whole guide, so the assistant carries on through steps 3 to 5 (deploy and dashboard) after this step. To stop after this step, add "stop after step 2" to the prompt; otherwise skip to step 6 when it finishes.

### HELP, STOP and UNSTOP replies

A new agent answers `Help` and `stop` itself with the service's default text. The deploy in [step 3](#3-deploy-the-infrastructure) registers real replies ([Keyword replies](#keyword-replies)), so you do not need to do anything now. If you want other wording on the handset from the first message, run the `put-keyword` commands in [Register the keyword replies](AGENTS.md#register-the-keyword-replies) before you add the test device; the deploy leaves alone a reply that you wrote yourself.

## 3. Deploy the infrastructure

```bash
(cd cdk && npm ci)
(cd cdk && npx cdk bootstrap)
(cd cdk && npx cdk deploy)
```

`npm ci` installs the exact versions in `package-lock.json`. `cdk bootstrap` runs once per account and Region; a fresh account has no bootstrap stack, and `cdk deploy` then fails with `SSM parameter /cdk-bootstrap/hnb659fds/version not found`. The first run creates the CDKToolkit stack (an Amazon S3 bucket, an Amazon Elastic Container Registry (Amazon ECR) repository and IAM roles). If your organization customized CDK bootstrapping, ask your administrator before you run it. On a first deploy, `cdk deploy` shows the IAM changes and asks for approval before it applies them; a later redeploy asks only if the changes broaden permissions.

`cdk deploy` reads `.deploy/agent.json` and creates the backend described in [What the stack creates](docs/architecture.md#what-the-stack-creates), plus a custom resource that enables two-way messaging on your RCS agent and registers its `HELP`, `STOP` and `UNSTOP` keyword replies. The stack is named `<prefix>-rcs-demo`, where `<prefix>` is your brand name in lowercase, with each run of other characters replaced by a hyphen, leading and trailing hyphens removed, and the result cut to 20 characters (`anyhealth` by default, and when nothing is left; see [Editing the demo](README.md#editing-the-demo)). This guide uses `<prefix>` for the names of the stack, the secret, the log groups and the roles. Note the outputs **`ApiUrl`**, **`ApiKeySecretName`** (step 4 uses it) and **`KeywordsStatus`**. To read them again, run `aws cloudformation describe-stacks --stack-name <prefix>-rcs-demo --region <REGION> --query "Stacks[0].Outputs"`.

### Deploy options

Pass an option with `-c <key>=<value>` on `cdk diff` and `cdk deploy`. If you pass `rcsAgentId` and `region` with `-c` instead of `.deploy/agent.json`, add the same `-c` flags to `cdk bootstrap` as well:

| Option | Default | Notes |
|---|---|---|
| `rcsAgentId`, `region` | from `.deploy/agent.json` | Both are required, and `-c` overrides the file per key. `region` must be the RCS agent's Region |
| `registerKeywords` | `true` | `true` or `false` (any case); any other value stops synth. `false` skips the keyword replies (the wiring role then gets no keyword permissions), and `KeywordsStatus` reads `skipped`. Turning it off later does not undo what an earlier deploy wrote |
| `bedrockModelId` | `global.anthropic.claude-sonnet-4-6` | A geography prefix (`us.`, `eu.`, `au.`, `jp.`, `apac.`) that does not match `bedrockRegion` in the sample's built-in table triggers a synth warning; confirm with `list-inference-profiles` as shown in [Amazon Bedrock access and model choice](#amazon-bedrock-access-and-model-choice) |
| `bedrockRegion` | the deploy Region | The Region that the AI use case examples call |
| `smsFallbackNumber` | off | An E.164 number; see [Optional: per-message SMS fallback](#optional-per-message-sms-fallback) |

### Keyword replies

The same custom resource writes the `HELP`, `STOP` and `UNSTOP` replies, which adds a few seconds to the deploy (the keyword calls are limited to about one request per second). AWS's keyword guidance is that a `HELP` reply includes support contact information and a `STOP` reply confirms that messages will stop ([Keywords in AWS End User Messaging SMS](https://docs.aws.amazon.com/sms-voice/latest/userguide/keywords.html)). The `HELP` reply names the phone number and the email address from `content/brand.md`; with only one it names that one, and with neither it uses `contactWebsite`. Synth stops with a message if `brand.md` has no contact method at all (set `contactPhoneNumber`, `contactEmailAddress` or `contactWebsite`) or a reply would pass 1000 characters. `KeywordsStatus` reads `ok (...)` when it worked and `error (...)`, with the AWS error code, when it did not. Registering never fails the deploy, and the detail is in the `/aws/lambda/<prefix>-eum-wiring` log group. [Register the keyword replies](AGENTS.md#register-the-keyword-replies) has the rules for what the deploy writes and leaves alone.

### Optional: per-message SMS fallback

Add `-c smsFallbackNumber=<E.164 number>` to attach a `FallbackConfiguration` to the entry message of each use case example that defines a fallback body, so that a message RCS cannot deliver still reaches the member as an SMS. Without it, the demo runs RCS-only and the Settings tab says **Not configured**. The number must be an SMS-capable origination identity that you already own in this account and in the deploy Region, registered for the same use case as the message. Synth looks the number up with `aws pinpoint-sms-voice-v2 describe-phone-numbers` using the credentials in your environment, and stops with an error unless the number is one you own, is `ACTIVE` and is SMS-capable. If the lookup cannot run, synth prints a warning and continues, so check the number yourself. See [Per-message SMS fallback](docs/architecture.md#per-message-sms-fallback).

### Updating an existing deployment

If the stack was deployed before the media bucket had lifecycle rules, the update adds them, and objects already past the limits start expiring at the first lifecycle run. Copy anything you want to keep before you deploy. [SECURITY.md](SECURITY.md#scope--read-this-before-deploying) lists the retention rules.

## 4. Retrieve the API key

The dashboard needs the shared API key that the stack generated. It gates every route except the few that are open on purpose ([Routes that need the API key](SECURITY.md#routes-that-need-the-api-key) lists the gated routes and [Open routes](SECURITY.md#open-routes) lists the rest). If you use the `web/.env` command in step 5, which writes the key to the file without printing it, you can skip this step. Otherwise this command prints the key, for the case where you paste it into the dashboard's **Settings** tab. Replace `<ApiKeySecretName>` with the step 3 output and `<REGION>` with the `region` value in `.deploy/agent.json`:

```bash
aws secretsmanager get-secret-value \
  --secret-id <ApiKeySecretName> \
  --query SecretString --output text \
  --region <REGION>
```

> The secret is in the **deploy** Region, which might differ from your CLI default Region, so keep `--region` (or `export AWS_REGION=<REGION>`). For a `ResourceNotFoundException`, see [Troubleshooting](#troubleshooting).

> **Replacing the key later.** This value is shared, and nothing rotates it automatically. If it might have leaked, store a new one with `aws secretsmanager put-secret-value`. [Rotating the API key](SECURITY.md#rotating-the-api-key) has the command and says how long the old key keeps working. Then update `VITE_API_KEY` in `web/.env` and the key in the **Settings** tab, which each hold their own copy.

## 5. Run the dashboard

Give the dashboard its URL and key in one of two ways, then start it.

**Option A: `web/.env`.** One command writes both values without printing the key. Replace `<ApiKeySecretName>` and `<ApiUrl>` with the step 3 outputs and `<REGION>` with the deploy Region:

```bash
(umask 077; KEY=$(aws secretsmanager get-secret-value --secret-id <ApiKeySecretName> --query SecretString --output text --region <REGION>) && printf 'VITE_API_URL=%s\nVITE_API_KEY=%s\n' '<ApiUrl>' "$KEY" > web/.env)
```

**Option B: in the browser.** Skip the `.env` file. Start the dashboard, enter the `ApiUrl` under **API URL** on the **Connect to your deployment** screen and choose **Connect**. Then open the **Settings** tab, enter the key from step 4 under **API key**, choose **Save API key**, and reload the page. The **Settings** tab can also change the URL later.

Start the dashboard and open <http://localhost:5173>. `npm run dev` keeps running, so use a second terminal for anything else:

```bash
(cd web && npm ci && npm run dev)
```

**Confirm the account.** The **Settings** tab's **Deployment connection** card shows the AWS account ID and Region the API runs in, once the API key is set and the page is reloaded. Check it if you deploy to more than one account.

> **The dashboard is for local use only.** Run it with `npm run dev` on your own machine, and never host or share a `web/dist` build. A key you paste into the **Settings** tab is kept in your browser's `localStorage`. See [Why the dashboard is local-only](SECURITY.md#why-the-dashboard-is-local-only).

**Optional: a desktop icon for the dashboard.** On macOS and Windows, if you start the dashboard often, `(cd web && npm run create-shortcut)` puts a double-click **`<BrandName> Dashboard`** launcher on your Desktop. It does not configure the dashboard, so complete Option A or B first. Details and caveats are in [scripts/launcher/README.md](scripts/launcher/README.md).

The far right of the status bar reads a string such as `fe:1.0.0.42 | be:1.0.0.57`: the build of the dashboard in this browser, and the build of the stack it reached. A `be:?` means the version call failed, so `VITE_API_URL` is wrong or the stack isn't reachable. The version route does not use the API key, so it does not confirm step 4: if the **Recipients** tab lists your test devices, the key works. [Dashboard](docs/architecture.md#5-dashboard) explains the version string.

## 6. Try the demo

1. **Recipients tab.** If the assistant already added your phone, it appears on the tab, and you can name it by editing its **User** cell. Otherwise choose **Add recipient** and enter your phone number (a new number is registered as a test device and sent the invitation; for a number that is already registered, it only saves the name), accept the invitation on your phone (on an iPhone, check **Unknown Senders**), and confirm that the status shows **VERIFIED**. Set yourself as the current target.

   If the count in the tab header already reads **10/10**, the RCS agent is at its verified test device quota, and adding another number fails. Use **Remove** on a row you no longer need first. That unregisters the device with AWS, so it has to accept a new invitation to come back; its transcript is kept ([Removing a verified test device](docs/architecture.md#removing-a-verified-test-device)).
2. **Interactive Demos tab.** Send any use case example to your device. Tap chips and reply to drive the flows. **Device preview** renders a use case example's exact RCS content without sending it.
3. **Start from the phone (optional).** In the AWS console, open your RCS agent, then **Testing**, then **Inbound deep link**, and set the pre-populated body to the `deepLinkKeyword` from `content/brand.md` (`Get started` by default). Generate the link and paste the resulting `sms:` URL into the panel at the bottom of the **Recipients** tab. Scanning the QR code it renders opens the messaging app with that message ready to send, and the channel adapter answers with the welcome message (three rich cards). A testing agent still delivers only to registered test devices, so this is not a way to onboard an unregistered handset. See [Starting from the phone](docs/architecture.md#22-starting-from-the-phone-inbound-deep-links).
4. **Take over.** Ask to **“talk to a person”** to trigger the handover, then reply from the **2-way Conversations** tab as a human care advocate.

   Do not text `stop` to the agent from your own handset unless the `UNSTOP` keyword is registered (the deploy registers it unless you passed `-c registerKeywords=false`; check the `KeywordsStatus` output). The service adds your number to the account's Default opt-out list, after which every send to you fails with `DESTINATION_PHONE_NUMBER_OPTED_OUT` and the bot stops answering you; see [Troubleshooting](#troubleshooting).

## Teardown

Destroy the stack first, because it holds the two-way wiring that points at your RCS agent, and then delete the RCS agent:

```bash
(cd cdk && npx cdk destroy)
```

Run it with the same inputs you deployed with: keep `.deploy/agent.json` and `brandName` in `content/brand.md` unchanged, or repeat the `-c rcsAgentId=<AGENT_ID> -c region=<REGION>` options.

The stack's resources use `RemovalPolicy.DESTROY`, and `autoDeleteObjects` empties the two Amazon S3 buckets before they are deleted. The AWS KMS key for the DynamoDB table is scheduled for deletion, with a waiting period of 30 days by default, instead of being removed at once. CloudFormation deletes the API-key secret at once ([DeletionPolicy attribute](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-attribute-deletionpolicy.html)), so a redeploy under the same name works.

> **Two-way caveat: your RCS agent is not owned by the stack.** The agent is an external resource that `cdk deploy` reconfigures: the custom resource repoints its two-way messaging at this stack's SNS topic and inbound-media bucket. On `cdk destroy` it **disables two-way on the agent** instead of restoring whatever was there before, and it does not record the previous settings. If the agent was already wired to your own topic, capture the current settings before you deploy:
> ```bash
> aws pinpoint-sms-voice-v2 describe-rcs-agents --rcs-agent-ids <AGENT_ID> --region <REGION> \
>   --query "RcsAgents[0].{TwoWay:TwoWayEnabled,Chan:TwoWayChannelArn,Role:TwoWayChannelRole,Events:TwoWayRcsEventsEnabled,MediaBucket:TwoWayMediaS3BucketName,MediaRole:TwoWayMediaS3Role,MediaPrefix:TwoWayMediaS3KeyPrefix}"
> ```
> and re-apply them with `update-rcs-agent` afterwards. **The simplest approach is to use a dedicated RCS agent for this demo.** If another deployment has since taken over the agent's two-way messaging (it delivers to a different topic than this stack's), `cdk destroy` notices and leaves the agent's two-way setting, its `UNSTOP` keyword and the configuration set alone.

**What the destroy leaves on the agent.** `cdk destroy` removes the `UNSTOP` keyword only if it still has the text and the `OPT_IN` action that the stack wrote (nothing, if the last deploy used `-c registerKeywords=false`). `HELP` and `STOP` are permanent keywords on the agent and keep the replies the stack wrote, so the `STOP` reply still tells members to reply `UNSTOP`; if you keep using the agent, register `UNSTOP` again by hand or give `STOP` text of your own ([Register the keyword replies](AGENTS.md#register-the-keyword-replies)).

**Leftovers after a brand rename or an agent switch.** A `brandName` change that alters the prefix deploys a second stack ([Editing the demo](README.md#editing-the-demo)). If you destroy the first stack after the second one is deployed, the destroy leaves the agent's two-way setting and its `UNSTOP` keyword alone, because the agent now delivers to the second stack's topic, and it leaves the first stack's configuration set in your account. Remove that configuration set with:

```bash
aws pinpoint-sms-voice-v2 delete-event-destination --configuration-set-name <old-prefix>-demo-events --event-destination-name <old-prefix>-events-sns --region <REGION>
aws pinpoint-sms-voice-v2 delete-configuration-set --configuration-set-name <old-prefix>-demo-events --region <REGION>
```

If you point `.deploy/agent.json` at a different RCS agent and deploy again, the deploy wires the new agent and leaves the old one with two-way messaging on. It writes a `WARNING` line to the `/aws/lambda/<prefix>-eum-wiring` log group with the command that turns it off: `aws pinpoint-sms-voice-v2 update-rcs-agent --rcs-agent-id <OLD_AGENT_ID> --no-two-way-enabled --region <REGION>`.

**Then delete the RCS agent**, unless you reused one that other work depends on. Follow [Teardown in AGENTS.md](AGENTS.md#teardown) in this order: the verified test devices, deletion protection off (the setup turns it on when it creates the RCS agent), the registration, then the agent.

## Troubleshooting

This list covers `cdk deploy`, the dashboard and runtime errors. [AGENTS.md](AGENTS.md#troubleshooting) has a table for the RCS agent setup steps (registration denials, test device invitations, protect configurations).

- **`cdk deploy` fails bundling the layer.** The local `pip` build failed (a `pip` older than 24.2 on a Python older than 3.10 is the usual cause) and Docker isn't running. Upgrade `pip`, set `PYTHON=/path/to/python3` to a newer interpreter, or start Docker ([Node.js, python3 and Docker](#nodejs-python3-and-docker)).
- **A Lambda function fails at runtime with `Runtime.ImportModuleError` naming a compiled dependency** (for example `_cffi_backend`, `PIL`, `pillow_heif`). The layer was built with wheels for the wrong CPU architecture, or for another Python version than the function runs. Both layers pin x86_64 wheels and all functions declare `X86_64`; the `--python-version` tag, the functions' runtime and the layers' `compatibleRuntimes` all come from `PY_RUNTIME` and `PY_TAG` at the top of `cdk/lib/anyhealth-stack.ts`, so this happens only if those were edited. Restore them, then redeploy with the asset cache cleared, from the repository root: `(cd cdk && rm -rf cdk.out && npx cdk deploy <your -c options>)`. CDK otherwise reuses the already-bundled bad layer.
- **`cdk deploy` fails with "SSM parameter /cdk-bootstrap/... not found".** Run `cdk bootstrap` ([step 3](#3-deploy-the-infrastructure)).
- **`ResourceNotFoundException: Secrets Manager can't find the specified secret`.** This is most often a Region mismatch: the stack created the secret in the Region from `.deploy/agent.json`. Add `--region <REGION>` ([step 4](#4-retrieve-the-api-key)) or export `AWS_REGION`, and confirm that your profile is for the account you deployed to.
- **`Found invalid choice 'describe-rcs-agents'`.** Your AWS CLI does not have the RCS operations; see [AWS CLI with the RCS commands](#aws-cli-with-the-rcs-commands).
- **Sends fail with `MONTHLY_SPEND_LIMIT_REACHED_FOR_RCS`.** The account has reached its RCS monthly spend limit, often $1 on a new account; see [RCS monthly spend limit](#rcs-monthly-spend-limit).
- **`AWS::IAM::Role ... already exists` on deploy.** IAM role names are account-global. The two-way roles (`<prefix>` is defined in [step 3](#3-deploy-the-infrastructure)) are named `<prefix>-demo-twoway-<region>` and `<prefix>-demo-twoway-media-<region>`, so the same stack can be deployed to several Regions; this error means a role with that name is already in the account, owned by another stack or left behind by an earlier deploy. Delete the leftover role or stack and redeploy. A failed deploy can also leave a stack in `REVIEW_IN_PROGRESS`; delete it before retrying (`aws cloudformation delete-stack --stack-name <prefix>-rcs-demo --region <REGION>`).
- **No RCS agent id found / No region specified.** Both inputs are required. Run [step 2](#2-set-up-your-rcs-agent), or pass **both** `-c rcsAgentId=<AGENT_ID> -c region=<REGION>`. The Region is not inherited from your CLI configuration on purpose: it must match the agent's Region.
- **Messages arrive as SMS, not RCS.** The sample sends SMS only when you deployed with `-c smsFallbackNumber`, as the fallback for a message that RCS could not deliver. Check that `TestingAgent.Status` is `ACTIVE` (a top-level `Status` of `TESTING` is expected for a testing agent), that the phone has RCS chat enabled, and that the number shows **VERIFIED** on the **Recipients** tab.
- **Every send to one test device fails with `DESTINATION_PHONE_NUMBER_OPTED_OUT`.** That device texted `stop` (the **Recipients** tab shows an **Opted out** badge on its row), and the service added the number to the account's Default opt-out list; the bot skips its own replies to it ([Keywords, and where a keyword is answered](docs/architecture.md#21-keywords-and-where-a-keyword-is-answered)). The device opts back in by texting a registered `OPT_IN` keyword such as `UNSTOP`; otherwise see [Clear an opt-out entry](AGENTS.md#clear-an-opt-out-entry).
- **AI use case examples error.** Benefits & Coverage Q&A and Find a Provider failures are logged as `AI invocation failed` in the channel adapter's CloudWatch Logs group (`/aws/lambda/<prefix>-channel-adapter`), and the member sees "I'm having trouble right now". Photo failures are logged as `image classification failed` (the description) or `orientation inference failed` (the orientation check) in `/aws/lambda/<prefix>-media-convert`. Run the `converse` smoke test from [Amazon Bedrock access and model choice](#amazon-bedrock-access-and-model-choice) with your admin credentials against `bedrockRegion`. An `AccessDeniedException` means that the Anthropic use case form has not been submitted for the account, the identity making the first call does not have `aws-marketplace:Subscribe`, or the account has no valid payment method. After you fix the cause, run the `converse` command again after a few minutes (the subscription can take up to 15 minutes, see [Amazon Bedrock access and model choice](#amazon-bedrock-access-and-model-choice)). If the error continues after you submit the Anthropic use case form, run `aws bedrock get-foundation-model-availability --model-id <FOUNDATION_MODEL_ID> --region <BEDROCK_REGION>`, using the model ID without the `global.` or geography prefix (for example `anthropic.claude-sonnet-4-6`), and check that `agreementAvailability.status` is `AVAILABLE`. A validation error means that the model or inference profile is not offered in `bedrockRegion`: list what is (same section) and override with `-c bedrockModelId=...`. The defaults live in `cdk/lib/config.ts`; `cdk/cdk.json` deliberately does not set them.
- **A photo link returns 403 `AccessDenied` for a key that no longer exists.** The dashboard's role has `s3:GetObject` on the prefixes it serves but not `s3:ListBucket`, so Amazon S3 returns 403 `AccessDenied` instead of 404 for a key that does not exist ([GetObject](https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetObject.html)). The usual case is an object that the lifecycle rules already deleted (see the retention rules in [SECURITY.md](SECURITY.md#scope--read-this-before-deploying)). So if a link that should work is refused, check the role's `s3:GetObject` prefixes in `cdk/lib/anyhealth-stack.ts` too.
