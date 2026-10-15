# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[1.0.0]: https://keepachangelog.com/en/1.0.0/
