---
inclusion: always
---
# AWS End User Messaging RCS Demo Catalog: project orientation

This demo ships a **catalog of independent, standalone brands** covering various
industries and use cases, which demonstrate AWS End User Messaging RCS. The
brands are siblings — there is no parent or umbrella brand, and none groups or
owns the others. More can be added as blocks under `brands:` in
`content/brand.md`. This version includes:

- **AnyHealth** — healthcare (appointments, prescriptions, benefits, wellness store)
- **AnyTravel** — travel and hospitality (AI trip assistant, hotel booking, mobile check-in, travel offers, flight check-in, flight status, rebooking, bag tracking)
- **AnyWealth** — financial services (AI account assistant, fraud alerts, loan agreement)
- **AnyHR** — HR and workforce self-service (AI HR assistant, clock in/out, schedule, PTO, shift swaps)
- **AnyBuild** — residential construction field messaging for builders, suppliers and trades (AI jobsite assistant, app welcomes, site evidence, identity capture, arrival alerts, delivery location, field schedule, job readiness, agreement/waiver)

The model is **one stack and one RCS agent per brand**. The user deploys one or
more brands. `scripts/deploy.mjs --brands <id,...|all>` runs pre-flight checks,
prints one plan (agents, stacks, IAM changes from `cdk diff`) for a single
confirmation, then deploys the brands one after another. Each `cdk deploy`
provisions one brand, selected with `-c brand=<id>` (default `anyhealth`): it
wires that brand's own agent and deploys only that brand's vignettes. An unknown
`brand` id stops the build and deploy before provisioning anything. The demo is deployable by any user into
their own AWS account with no hardcoded values.

- **Brand + content** live in `content/*.md` (single source of truth). Brand
  identity is the `brands:` catalog map in the YAML frontmatter of
  `content/brand.md` — a stable id keyed to a complete identity block per brand,
  plus `defaultBrand`. Never hardcode brand values, account IDs, region, ARNs,
  bucket names, or URLs anywhere else; only the brand selection is a
  deploy-time input.
- **Brand media** lives per brand at `media/<id>/logo.png` (224×224) and
  `media/<id>/banner.png` (1440×448), referenced from that brand's identity
  block (`logoImage`, `bannerImage`).
- **Setup and deploy** (create each brand's RCS agent, register it, add test
  devices, deploy, wire the dashboard) is driven by `AGENTS.md` in the repo root.
  When the user asks to set up or deploy the demo, read `AGENTS.md` in full,
  follow its ground rules and prerequisite checks, then its "Deploy one or more
  brands" section. Each brand gets exactly one agent, registered as that brand.
- **Infrastructure** is AWS CDK (TypeScript) under `cdk/`. The account comes from
  the deployer's credentials, but the **region and the RCS agent ID both come from
  `.deploy/agent.json`**, one `agents.<brandId>` entry per brand written by
  `scripts/create-agent.mjs` or `scripts/record-agent.mjs` (or
  `-c region= -c rcsAgentId=`). Synth refuses an agent whose registration names a
  different brand (`-c skipAgentCheck=true` skips that check). The region is never
  inherited from the deployer's CLI config — `loadDeployInputs` throws if it is
  not stated, because the stack has to deploy to the same region as the agent.
  The resource-name prefix is derived from the selected brand's name in
  `content/brand.md`, not from any hardcoded literal. Nothing is created
  before the user approves the plan from `scripts/deploy.mjs --plan-only`.
- **Backend** Lambdas are Python under `lambda/`; they read `content/*.md`
  bundled into the package at runtime, resolving the selected brand's identity
  and grounding content from the catalog rather than from hardcoded literals.
- **Dashboard** is React + Vite under `web/`, for local use only. It presents one
  brand at a time, with its own verified sender identity, and a brand picker
  switches between the deployed brands wired with `scripts/wire-dashboard-brand.mjs`. It does **not**
  self-configure: it needs the `ApiUrl` stack output and the API key from the
  Secrets Manager secret named by the `ApiKeySecretName` output, set in `web/.env`
  (`VITE_API_URL`, `VITE_API_KEY`) or the Settings tab, or the dashboard cannot
  send or read recipient data (a missing key stops the call in the browser; a
  wrong key is refused with 403). Brand/theme and the selected brand's vignettes
  come from `GET /api/brand` and `GET /api/vignettes`.

This is a demo/learning tool. Keep it parameterized and adaptable: any user can
re-theme any brand by editing its identity block in `content/brand.md` alone.
