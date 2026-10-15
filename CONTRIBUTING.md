# Contributing

Thanks for your interest in contributing. Please read through this document
before submitting any issues or pull requests.

## Reporting bugs and feature requests

Use the issue tracker to report bugs or suggest features. When filing an issue,
please check existing open and recently closed issues first, and try to include
as much information as you can:

- A reproducible test case or series of steps
- The **AWS Region** you deployed to, and whether you changed `bedrockModelId`
- The `fe:… | be:…` string from the right of the dashboard's status bar, which
  says which build of each half you are running
- The output of `aws --version` **and** of the RCS capability check in
  [SETUP.md](SETUP.md) — a CLI without the RCS operations is a common cause of
  setup failures
- The output of `aws pinpoint-sms-voice-v2 describe-spend-limits --region <REGION>`
  if the problem is that messages are not arriving
- Relevant CloudWatch log output from `/aws/lambda/<prefix>-channel-adapter`
- Anything unusual about your environment or deployment

**Please do not include** real phone numbers, API keys, account IDs, or the
contents of `.deploy/agent.json` or `web/.env` in an issue. The dashboard's
Settings tab shows your account ID, so redact it in screenshots.

## Contributing via pull request

1. Fork the repository and work against the latest `main`.
2. Check existing open and recently merged pull requests to avoid duplicating
   effort.
3. Open an issue first for anything substantial, so you don't spend time on a
   change that won't be merged.
4. Keep the change focused. Large or unrelated changes are hard to review.
5. Run the checks below before opening the PR.
6. Write a clear commit message and PR description explaining the problem and
   the fix.

### Before you open a PR

```bash
# Infrastructure typechecks and synthesizes.
# `.deploy/agent.json` is gitignored, so on a fresh clone pass the two required
# inputs on the command line — synth needs them but the values don't have to be
# real, since nothing is deployed.
cd cdk && npm ci
npx cdk synth --quiet -c rcsAgentId=rcs-0000000000000000 -c region=us-east-1

# Dashboard typechecks
cd ../web && npm ci && npm run typecheck
```

If you changed anything under `lambda/`, deploy to your own account and exercise
the affected use case example end to end — several RCS constraints (carousel card
counts, suggestion limits, media sizes) are only enforced by the service at send
time and will not show up in `cdk synth` or in the dashboard's Device preview.

### Things worth knowing

- **`content/*.md` is the single source of truth** for brand values. Don't
  hardcode brand strings anywhere else.
- **RCS has hard content limits** the API enforces: carousels take 2–10 cards,
  a card takes at most 4 suggestions, a message at most 11 message-level
  suggestions. Exceeding them fails the send with a `ValidationException`.
- **Don't bump a build number by hand.** `version.json` holds only the
  hand-maintained `major.minor.patch` for each half; the fourth segment the
  dashboard shows is a commit count computed by `scripts/version.mjs`, so it
  advances by itself. Edit `version.json` only for a real release.
- **Never commit** `.deploy/`, `web/.env`, real phone numbers, or real
  organization names in sample content.

### Editing the diagrams

After you edit a page in `docs/architecture.drawio`, re-export it from the
`docs/` directory with the draw.io desktop app. Page numbers are 1-based, and
`DRAWIO` is the path to the app's executable:

```bash
cd docs
DRAWIO=/Applications/draw.io.app/Contents/MacOS/draw.io   # macOS desktop app
"$DRAWIO" -x -f png -s 2 --crop -b 16 -p 1 -o img/architecture.png          architecture.drawio
"$DRAWIO" -x -f png -s 2 --crop -b 16 -p 2 -o img/inbound-routing.png       architecture.drawio
"$DRAWIO" -x -f png -s 2 --crop -b 16 -p 3 -o img/rich-media.png            architecture.drawio
"$DRAWIO" -x -f png -s 2 --crop -b 16 -p 4 -o img/architecture-overview.png architecture.drawio
```

`--crop` trims each export to its content, and `-b 16` keeps a small margin
around it. For the vector copy of a page, swap `-f png -s 2` for `-f svg` and
use the `.svg` file name.

## Code of conduct

This project has adopted a [Code of Conduct](CODE_OF_CONDUCT.md). Please read it
before participating.

## Security issue notifications

If you discover a potential security issue, please follow
[SECURITY.md](SECURITY.md). **Do not** open a public issue.

## Licensing

This project is licensed under the MIT-0 License. See [LICENSE](LICENSE). We may
ask you to confirm the licensing of your contribution.
