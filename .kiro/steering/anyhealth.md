---
inclusion: always
---
# AnyHealth project orientation

AnyHealth is a fictitious healthcare brand demonstrating AWS End User Messaging
RCS. It is deployable by any user into their own AWS account with no hardcoded
values.

- **Brand + content** live in `content/*.md` (single source of truth). Brand
  identity is the YAML frontmatter of `content/brand.md`. Never hardcode brand
  values, account IDs, region, ARNs, bucket names, or URLs anywhere else.
- **RCS agent setup** (create the RCS agent, register it, add test devices) is driven
  by `AGENTS.md` in the repo root. When the user asks to "set up my RCS agent",
  read `AGENTS.md` in full, follow its ground rules and prerequisite checks, then
  its "RCS Agent Setup" section.
- **Infrastructure** is AWS CDK (TypeScript) under `cdk/`. The account comes from
  the deployer's credentials, but the **region and the RCS agent ID both come from
  `.deploy/agent.json`** (or `-c region= -c rcsAgentId=`). The region is never
  inherited from the deployer's CLI config — `loadDeployInputs` throws if it is
  not stated, because the stack has to deploy to the same region as the agent.
  Deployment is two stages: set up the RCS agent first (`AGENTS.md`), then deploy by
  following "Deploy the demo" in `AGENTS.md`, which shows the `cdk diff` and waits for
  the user's approval before `cdk deploy`.
- **Backend** Lambdas are Python under `lambda/`; they read `content/*.md`
  bundled into the package at runtime.
- **Dashboard** is React + Vite under `web/`, for local use only. It does **not**
  self-configure: it needs the `ApiUrl` stack output and the API key from the
  Secrets Manager secret named by the `ApiKeySecretName` output, set in `web/.env`
  (`VITE_API_URL`, `VITE_API_KEY`) or the Settings tab, or the dashboard cannot
  send or read recipient data (a missing key stops the call in the browser; a
  wrong key is refused with 403).
  Brand/theme come from `GET /api/brand`.

This is a demo/learning tool. Keep it parameterized and adaptable.
