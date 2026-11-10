# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

_No changes yet._

## [1.1.0] - 2026-11-10

The demo becomes the AWS End User Messaging RCS Demo Catalog: five independent,
fictitious brands, each deployed as its own stack with its own RCS agent.

### Added

- Brand catalog in `content/brand.md`: AnyHealth, AnyTravel, AnyWealth, AnyHR
  and AnyBuild, with 41 use case examples in total. `-c brand=<id>` selects one
  brand per deploy, and each deploy opens only that brand's examples.
- AnyTravel airline examples (Flight Check-In, Flight Status Alert, Disruption
  Rebooking, Bag Tracking) alongside the hotel examples.
- AnyBuild brand for builders, suppliers and trades: nine field-messaging
  examples, including Site Evidence, Identity Capture, Delivery Location and
  Agreement/Waiver.
- Brand assistants: AnyTravel, AnyWealth, AnyHR and AnyBuild each have an
  Amazon Bedrock assistant grounded on the brand's content that answers
  questions and never takes actions. Seven examples also accept a typed answer,
  which the model turns into JSON that code validates.
- `scripts/deploy.mjs` deploys one or more brands with one plan and one
  confirmation, and can resume a failed brand. `scripts/create-agent.mjs`,
  `record-agent.mjs` and `delete-agent.mjs` manage one RCS agent per brand.
- Dashboard brand picker that lists only deployed, usable brands, wired with
  `scripts/wire-dashboard-brand.mjs`.
- CI tests for the deploy and agent scripts, and a synth of every brand.

### Changed

- `.deploy/agent.json` records one agent per brand. Synth refuses an agent
  whose registration names a different brand (`-c skipAgentCheck=true` skips
  the check). The single-agent format from 1.0.0 is still read.
- `cdk/lib/anyhealth-stack.ts` is now `cdk/lib/rcs-demo-stack.ts`. The stack
  name and resource IDs are unchanged, so a 1.0.0 stack updates in place.
- Brand media moved into per-brand folders, `media/<id>/`.
- The staff self-service examples moved to AnyHR and the hotel examples to
  AnyTravel.
- Documentation updated throughout for the multi-brand layout.

### Fixed

- Delivery, read and failure events for RCS, SMS and MMS now reach the event
  topic, which uses a customer managed AWS KMS key that the service can use.
- Stale sample values in several use case examples, including the Rx reminder
  calendar time, the media size limit and a provider address.

### Security

- Probe report logging keeps only allow-listed, bounded fields, and the video
  visit invite log no longer records the conversation hash.
- The Region check no longer uses a regular expression that is open to ReDoS.
- The media layer requirements note the LGPL/GPL libraries bundled in the
  `pillow-heif` wheels (see `NOTICE`).

## [1.0.0] - 2026-10-12

Initial public release of the AnyHealth RCS messaging demo: a deployable,
end-to-end demonstration of AWS End User Messaging Rich Communication Services
(RCS), themed as a fictitious healthcare brand.

### Added

- AWS CDK stack (`cdk/`) that provisions the demo backend: an HTTP API, four
  Lambda functions (channel adapter, dashboard, media convert, authorizer) plus
  a custom-resource Lambda, two dependency layers, a DynamoDB table, an SNS
  topic, an S3 media bucket, a configuration set for delivery and read events,
  and the API-key secret and Lambda authorizer.
- RCS test agent setup workflow driven by `AGENTS.md`, reading brand values from
  `content/brand.md` and writing the agent id to `.deploy/agent.json`.
- Twenty use case examples spanning customer/member and internal-staff flows,
  including rich cards and carousels, event-driven sends and inbound two-way
  routing, Amazon Bedrock AI conversations grounded on repository content,
  verification codes, per-message SMS fallback, live-agent handover, a
  conversational cart, and keyword/opt-out handling.
- Rich-media handling: inbound native RCS photos and secure webview uploads,
  both normalized (HEIC/HEIF/JPEG/PNG, EXIF orientation) and classified with
  generative AI, plus `FileMessage` delivery and in-message webviews.
- Experimental use cases: Video Visit via the Amazon Chime SDK for JavaScript,
  two Amazon IVS webview demos, and a camera/microphone capability probe.
- Local Cloudscape dashboard (`web/`) with Instructions, Interactive Demos,
  2-way Conversations, Recipients, and Settings tabs, plus an optional
  double-click desktop launcher.
- Documentation set: `README.md`, `SETUP.md`, `AGENTS.md`, `SECURITY.md`,
  architecture diagrams and narration (`docs/`), a tutorial, and content-editing
  guides. Content is parameterized through `content/*.md` so the demo can be
  re-themed for any brand.

### Security

- API key stored in AWS Secrets Manager and enforced by a Lambda authorizer on
  every route that can send a message, change data, or disclose recipient data;
  the open member-facing routes are documented in `SECURITY.md`.
- IAM grants to the `sms-voice.amazonaws.com` service principal are scoped to the
  deploying account with an `aws:SourceAccount` condition (confused-deputy
  prevention), and S3 and DynamoDB access is scoped per prefix and per table.

[Unreleased]: https://github.com/aws-samples/sample-rcs-messaging-demo-app/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/aws-samples/sample-rcs-messaging-demo-app/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/aws-samples/sample-rcs-messaging-demo-app/releases/tag/v1.0.0
