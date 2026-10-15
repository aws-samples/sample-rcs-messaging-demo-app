# Security Policy

## Reporting a vulnerability

If you discover a potential security issue in this project, please notify AWS
Security via our
[vulnerability reporting page](https://aws.amazon.com/security/vulnerability-reporting/)
or email aws-security@amazon.com directly.

**Please do not create a public GitHub issue for a security report.**

## Scope — read this before deploying

This is **sample code for demonstration purposes**, not a production system. Before you
deploy:

- Deploy into an isolated sandbox or development AWS account that you own, never a
  production account.
- Run the dashboard locally only (`npm run dev` on your own machine). See
  [Why the dashboard is local-only](#why-the-dashboard-is-local-only).
- Do not point the sample at real member or customer data, and do not register phone
  numbers that belong to people who have not agreed to receive test messages.
- Run `(cd cdk && npx cdk destroy)` when you are finished. Leaving the stack up leaves an
  internet-reachable API and accrues cost.

The sample also makes deliberate trade-offs that you must understand before you deploy it:

- **Authentication is a single shared API key**, held in an AWS Secrets Manager secret
  that the stack creates and checked by an AWS Lambda authorizer. There is no per-user
  identity, no revocation beyond rotating the one secret (see
  [Rotating the API key](#rotating-the-api-key) for how, and for how long the
  old key keeps working), and no audit trail of who did what (the API's access
  log, described in [API access log](#api-access-log), records the route and source IP
  of each request that matches a route, not who made it). For anything beyond a demo in
  an account you own, replace the Lambda authorizer with a JWT authorizer that uses an
  Amazon Cognito user pool as the issuer, or with AWS Identity and Access Management
  (IAM) authorization.
- **The dashboard is for local use only.** Run it with `npm run dev` on your own
  machine, and never host or share a `web/dist` build.
  [Why the dashboard is local-only](#why-the-dashboard-is-local-only) explains how the
  key reaches the browser, what it unlocks, and what to do if it gets out.
- **Some routes are intentionally unauthenticated**, either because a member's in-app
  webview browser or an `<img>` tag has to reach them and cannot hold the operator's key,
  or because they return only static demo metadata.
  [Open routes](#open-routes) lists each one, who calls it and what limits it, and
  [Routes that need the API key](#routes-that-need-the-api-key) lists the rest.
- **"Secure webview" here means *off the carrier path*, not *authenticated*.** The upload
  webview (on the way in) and the Rx prescription record (on the way out) move their
  bytes between Amazon Simple Storage Service (Amazon S3) and the member's browser over
  HTTPS, not through the Rich Communication Services (RCS) conversation. Neither the
  bucket policy for the AWS End User Messaging service principal nor the channel
  adapter's role covers `secure-docs/`;
  [Pharmacy Rx refill](docs/architecture.md#42-pharmacy-rx-refill) has the permission
  analysis, including the one role that holds both the send and the read permission for
  `secure-docs/` (the dashboard's, whose code sends nothing), and what this sample's
  testing observed. That prefix scoping covers this
  sample's own function roles only: the role that AWS Cloud Development Kit (AWS CDK)
  creates for the bucket-deployment
  helper keeps the CDK library's bucket-wide read and write grants on the media bucket
  (it holds no `sms-voice` permission). The webview pages carry no member sign-in, and
  the `ph` value in their URLs is `common.hash_phone` (`anon-` plus the first 24 hex
  characters of an **unsalted** SHA-256 of the E.164 number), which anyone who knows the
  number can compute. Serving real protected health information (PHI)
  needs a member session on those routes, per-member object keys, and an access log of
  every fetch (the [API access log](#api-access-log) records the route, not which member
  or document).
- **Member-submitted files expire, but not immediately.** The media bucket's lifecycle
  rules delete objects under `raw-uploads/` and `converted-uploads/` after 7 days and
  under `inbound/` and `converted-inbound/` after 30 days, and purge old versions after
  1 day. Raw originals can carry GPS EXIF data until then. `media/` and `secure-docs/`
  are never expired. Change the rules in `cdk/lib/anyhealth-stack.ts` if you need
  different retention. To delete these objects at once, use **Reset demo data** on the
  Interactive Demos tab ([Dashboard](README.md#dashboard)); it removes every version of
  the member-submitted files under `raw-uploads/`, `converted-uploads/`, `inbound/rcs/`
  and `converted-inbound/` for every recipient. If you update a deployment made before
  these rules existed, objects already past the limits start expiring at the first
  lifecycle run after the update (Amazon S3 runs lifecycle rules on its own schedule, not
  at deploy time), and once the previous versions are purged an expired object cannot be
  recovered, so copy anything you want to keep first. The media bucket also writes S3
  server access logs to a separate access-logs bucket, which keeps them for 90 days. Each
  record holds the requester's IP address and the object key, and keys under
  `raw-uploads/` and `converted-uploads/` include the `ph` conversation hash, so limit who
  can read that bucket. **Reset demo data** does not remove these records; `cdk destroy`
  does.
- **The stack sets no route or stage throttling.** Only the account-level throttling that
  Amazon API Gateway applies in each Region is in effect
  ([Throttle requests to your HTTP APIs](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-throttling.html)),
  and every API in the account shares it. Set stage-level or route-level throttling
  before you expose the API to anything you don't control.
- **The API access log records requests, not people, and it holds client IP addresses.**
  Each request that matches a route writes one line with the route, the status and the
  source IP address, and the log group keeps the lines for two weeks. It is operational
  telemetry, not an audit log. [API access log](#api-access-log) lists what a line holds
  and omits, what was checked on deployed stacks, and the permissions the deploy needs
  for it.
- **Photos are sent to Amazon Bedrock.** Every image a member sends to the RCS agent, and
  every upload from the secure upload webview, is converted by `lambda/media_convert.py`,
  which sends a downscaled copy to Amazon Bedrock for a one-sentence description. For a
  JPEG, PNG or GIF with no usable EXIF orientation it sends up to two more copies to
  check orientation. The prompt tells the model not to repeat names, numbers, IDs or medical
  details; the sample does not check that the reply complies. The default model uses a
  global inference profile, so a request can be processed in any Region that profile
  covers; see
  [Amazon Bedrock access and model choice](SETUP.md#amazon-bedrock-access-and-model-choice)
  if you have a data-residency requirement.
- **This is not a HIPAA-compliant system.** See the
  [HIPAA notice](README.md#privacy-and-security) before you adapt this sample for real
  protected health information (PHI).
- **Opt-outs are enforced by the service, and only read here.** AWS End User Messaging
  adds a member who texts `STOP` to the account's Default opt-out list, and the sample
  reads that list before it replies (observed on a testing agent; a country-launched
  agent was not tested). The sample keeps no suppression list of its own. AWS recommends
  that a production sender keep its own opt-out record
  ([RCS best practices](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-best-practices.html)).
  See [Keywords, and where a keyword is answered](docs/architecture.md#21-keywords-and-where-a-keyword-is-answered).
- **The emergency screen is a safety net, not triage.** A short list of whole-word
  phrases gets one fixed 911/988 reply. It reads no context, is no substitute for
  clinical judgment or a screening service, and uses US numbers. See
  [Inbound routing](docs/architecture.md#2-inbound-routing).
- **Service-principal access is scoped to your account, except the topic policy.** The
  bucket policy statement that lets the `sms-voice.amazonaws.com` service principal read
  media and the trust policies of the two roles that the service assumes (two-way publish
  and inbound media) carry an `aws:SourceAccount` condition with the deploying account's
  ID, as AWS recommends
  ([Cross-service confused deputy prevention](https://docs.aws.amazon.com/IAM/latest/UserGuide/confused-deputy.html#cross-service-confused-deputy-prevention)).
  On a testing agent with these conditions, a file message, an inbound text and an
  inbound photo all worked. The Amazon Simple Notification Service (Amazon SNS) topic
  policy statement that lets the service publish inbound messages has no condition,
  matching the AWS example for that option, and inbound messages in testing arrived
  through the two-way role. This sample did not test a condition on the topic policy: to
  add one, deploy it to a test account and confirm that inbound messages still arrive.

## Open routes

A small set of routes is deliberately open, either because something that cannot hold
the operator's key has to call them (a member's in-app browser, an `<img>` tag) or
because they return only static demo metadata:

| Open route | Called by | Why it is open, and what limits it |
|---|---|---|
| `/` | anyone who pastes the bare `ApiUrl` into a browser | the handler has no route for it and answers a JSON `404`. The route accepts any method, so every request to it invokes the dashboard function; it returns no data |
| `/webview/{proxy+}` | the member's in-app browser | serves the brand-substituted webview pages and the vendored Amazon Chime SDK script. The diagnostic pages report to it through a `?report=` query string, which the handler writes (up to 4,000 characters) to the dashboard function's log group, so treat that group as holding caller-supplied text. No recipient data |
| `/api/uploads/presign`, `/api/uploads/{ph}/{id}/status` | the upload webview | no key in a member session. `presign` requires a well-formed hash (`common.hash_phone` form) for a conversation that already exists, plus a supported image type; that stops unauthenticated scans and arbitrary input, not a caller who knows a member's number. `status` needs the upload id `presign` minted, and returns the photo's one-sentence description and a one-hour presigned link to the converted photo, so the 122-bit upload id (a `uuid4`) is the control for that data |
| `/api/video/join`, `/api/video/ping`, `/api/video/status`, `/api/video/end` | the video-visit webview (`join`, `ping`, `end`) and the dashboard's Video Visit window (all four; `join`, `ping` and `end` with `role=clinician`) | no key in a member session. Each call names an unguessable visit token this deployment already minted, which expires in 30 minutes and can be exchanged for Chime SDK join material only a capped number of times (`MAX_JOINS` is 12; attendee-minutes are billed). The caller supplies `role`, so it is not a permission; the token is the control. `status` returns booleans, never recipient data |
| `/api/secure-doc?ph=&doc=` | the Rx record webview | no key in a member session. Returns a 300-second presigned link to a document that must not cross the carrier network; the caller names a document id, never an S3 key, and the conversation must exist. Not a substitute for a member sign-in: see `dashboard_handler.get_secure_doc` |
| `/api/media?key=` | `<img src>` in the dashboard | a browser cannot attach a header to an image request, so the server presigns (for one hour) only keys under `media/`, `inbound/rcs/`, `converted-inbound/` and `converted-uploads/` (`dashboard_handler._MEDIA_ALLOWED_PREFIXES`). The last three hold member-submitted media, so the unguessable object key is the control. `raw-uploads/` and `secure-docs/` are not presignable here |
| `/api/brand`, `/api/vignettes`, `/api/vignettes/preview`, `/api/vignettes/features` | the dashboard | static demo metadata: brand tokens and the contact details in `content/brand.md`, the use case example catalog and previews, and the RCS feature registry; no recipient data. These values are served without a key, so keep private details out of `content/brand.md` |
| `/api/version` | the dashboard status bar | one build string for the deployed stack, shown beside the frontend's own; build metadata about this sample, nothing account-specific. The bar has to show it even when the API key is missing or wrong, which is exactly when it is asked for |

**What the upload and media routes allow.** The presigned upload URL that `presign`
returns is valid for 10 minutes and can be reused within that time. The sample sets no
size or count limit on it, and the media bucket accepts `PUT` from any origin, so the
signature is the only control. Each object written starts `media_convert` (files up to
50 MB are accepted) and its vision calls.

**Do not treat the API hostname as a secret.** The channel adapter embeds it
in the in-message webview links it sends to member handsets.

## Routes that need the API key

Every route that is not in the [Open routes](#open-routes) table needs the API key in the
`x-api-key` header, which the Lambda authorizer checks against the Secrets Manager secret.
[`cdk/lib/anyhealth-stack.ts`](cdk/lib/anyhealth-stack.ts) registers the routes and is the
authoritative list. The key is not an identity; see
[Why the dashboard is local-only](#why-the-dashboard-is-local-only) for what a holder can
do.

| Method | Route | What it returns or changes |
|---|---|---|
| `GET` | `/api/health` | the account's RCS spend limits and quota alert |
| `GET` | `/api/agent-identity` | the AWS account ID, the registration's brand and contact details, and the SMS fallback number |
| `GET` | `/api/conversations`, `/api/conversations/{ph}` | conversation lists and full transcripts |
| `GET` | `/api/testers`, `/api/testers/names`, `/api/testers/status`, `/api/testers/metrics` | test device phone numbers, names, verification status and per-recipient counts |
| `GET` | `/api/keywords` | the agent's custom keywords and their replies |
| `GET` | `/api/media/latest` | one-hour links to the latest member photos |
| `GET` | `/api/mode`, `/api/typing` | the conversation mode (bot or human) of a recipient, and the hashes and timestamps of recipients who are composing a reply |
| `POST`, `PUT` | `/api/testers`, `/api/testers/{phone}` | register or rename a test device |
| `POST` | `/api/keywords` | register or update a keyword on the RCS agent |
| `POST` | `/api/trigger`, `/api/push`, `/api/reply` | send an RCS message to the phone number in the request: a use case example, content that the caller supplies, or a human reply |
| `POST` | `/api/mode`, `/api/reset` | switch a conversation between bot and human, and delete demo data and generated media |
| `POST` | `/api/video/start`, `/api/video/preview` | mint a video visit token (`start` also sends the invitation) |
| `DELETE` | `/api/testers/{phone}`, `/api/keywords/{keyword}` | delete a test device or a keyword |

## API access log

The access log records requests, not people, and it holds client IP addresses. The stack
sets the `$default` stage to write a JSON line to the Amazon CloudWatch Logs group
`/aws/vendedlogs/apigateway/<prefix>-demo-api` for each request that matches a route
(`<prefix>` is the brand name from `content/brand.md` as a lowercase slug, `anyhealth`
by default), and the group keeps the lines for two weeks. A CORS preflight is logged too (its route key is
`-`), including a preflight to an unknown path, but any other request that matches no
route (a `GET` to an unknown path, a method the route does not list, `HEAD` on a `GET`
route) writes no line, so the log holds only requests that match a route. A line
holds the time, request ID, source IP address, HTTP method, route key (the route template,
for example `GET /api/conversations/{proxy+}`), status, response size, latencies, the
Lambda integration's status, the gateway response type (`errorResponseType`), and the
error text the gateway, the authorizer or the integration reports: 14 fields in all, and
a variable with no value logs `-`. It holds no
request or response body, no headers (so no API key), no user agent, and neither the
request path nor the query string, because those carry the `ph` conversation hash, upload
ids, visit tokens and test device phone numbers; `cdk synth` fails if the format string names
the path, the user agent or a `$request` variable.

The source IP is personal data, and on the open webview routes it is a member's address,
so limit who can read the group. The log is operational telemetry, not an audit log: it
names no user (every holder of the shared key looks the same), it cannot say whose
document was fetched, anyone who can delete its log streams or the group, or write to
it, can change it, and it limits nothing, because it records requests and does not
throttle them. Other logs are not held to the same rule. For example, the dashboard
function's own log group records the method and raw path of a request that raises an
unhandled error, and the first 12 characters of a caller-supplied conversation hash when
`/api/secure-doc` or `/api/uploads/presign` finds no conversation for it. The group
belongs to the stack with `RemovalPolicy.DESTROY`, so `cdk destroy` removes it; confirm
in CloudWatch Logs that the group is gone. The policy that appeared at deploy time (see
[What was checked on deployed stacks](#what-was-checked-on-deployed-stacks)) is not part
of the stack, and this sample did not check whether `cdk destroy` removes it.

### Permissions the deploy needs for the log

Turning on an HTTP API's access log adds one CloudWatch Logs requirement. AWS's list for
whoever enables logging on a stage includes `logs:CreateLogDelivery`,
`logs:UpdateLogDelivery`, `logs:GetLogDelivery`, `logs:ListLogDeliveries`,
`logs:DeleteLogDelivery`, `logs:PutResourcePolicy`, `logs:DescribeResourcePolicies` and
`logs:DescribeLogGroups`
([Configure logging for HTTP APIs](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-logging.html)).
During `cdk deploy` that is the execution role of AWS CloudFormation, which a default
`cdk bootstrap` sets to `AdministratorAccess`; a bootstrap with narrower
`--cloudformation-execution-policies` has to allow them.

### What was checked on deployed stacks

The stack authors no log resource policy. When the stage began logging, during the stack
update, CloudTrail showed CloudFormation's execution role making a
`logs:PutResourcePolicy` call, and a policy scoped to this group appeared (a statement for
`delivery.logs.amazonaws.com` allowing `logs:CreateLogStream` and `logs:PutLogEvents` on
the group's streams, limited to the account). Lines do reach the group: the first one
appeared about 50 seconds after its request, so allow a couple of minutes before deciding
that nothing is being written. Scans of every line in the group, after requests that
carried sentinel path and query values, conversation hashes, an upload id, a visit token,
a phone number, an API key and request headers, found none of those values, and each line
had exactly the 14 fields of the format. The same scan of the lines that traffic from a
real test device wrote on a second deployed stack found none of the phone numbers or
conversation hashes involved. The gateway's authorizer cache is keyed on the key value
across routes (the same wrong key sent to two routes ran the authorizer once), so a denial
that the gateway answers from its authorizer cache looks the same in the log as one the
authorizer decided.

The free-text error fields (`errorMessage`, `integrationErrorMessage` and
`authorizerError`) hold the error text the gateway, the authorizer or the integration
reports. In testing they held only `-`, `Unauthorized` and `Forbidden`. This sample did
not exercise gateway or integration failures (a 502, 503 or 504, or a timeout), so the
error text for those cases was not inspected; limit who can read the group.
The 500s that were logged, one on each stack, were the handler's own answer to a
deliberately malformed request body; on the line that was inspected, `integrationStatus`
was `200` and the error fields held `-`.

## Why the dashboard is local-only

The dashboard in `web/` is a single-page app built with
[Vite](https://vite.dev) ([source on GitHub](https://github.com/vitejs/vite)), a
frontend build tool and development server. `npm run dev` starts Vite's
development server, and `npm run build` compiles the app into static files in
`web/dist/`.

**How the key gets into the browser.** The dashboard runs entirely in the
browser, so it has to hold the shared API key to send it with each request.
Vite makes every environment variable whose name starts with `VITE_` available
to the app's code in the browser (as `import.meta.env.VITE_…`), and `npm run build`
replaces each reference with the variable's literal value. Vite's own
documentation says that `VITE_*` variables should not contain sensitive
information such as API keys, because their values are bundled into the source
code at build time ([Env variables and modes](https://vite.dev/guide/env-and-mode)).
The dashboard reads four of them:

| Variable | Holds | Secret? |
|---|---|---|
| `VITE_API_KEY` | the shared API key | **Yes** |
| `VITE_API_URL` | the API's base URL | No. See [the API hostname is not a secret](#open-routes) |
| `VITE_DEEP_LINK` | the agent's inbound deep link, optional | No |
| `VITE_FE_VERSION` | the frontend build string, set by `web/vite.config.ts` | No |

Vite reads these from `web/.env`, `web/.env.local`, the mode-specific files
(`.env.production` and so on), **and** from the environment of the process that
runs it. A variable already set in the shell takes priority over the files. So a
terminal or CI job with `VITE_API_KEY` exported compiles the key into a build
in the same way that a populated `web/.env` does. Every one of those files is gitignored.

**What someone does with the key.** The key is the only thing that gates the routes that
send messages, change data and return recipient or account details. The API accepts
requests from any origin (CORS `*`), so a web page's origin is no second barrier, and the
API hostname is not a secret. Anyone holding both can call every route outside the
[Open routes](#open-routes) table to:

- send RCS messages, with content of their choosing, to any phone number they supply
  (`/api/push` and `/api/reply` take the number and the content from the request). A
  testing agent delivers only to its verified test devices, and an agent that has
  launched in a country delivers to recipients on the carriers that approved it. These
  sends bill your account and count against the account's RCS monthly spend limit;
- register or delete the agent's keywords, including keywords that opt a member out or
  in (`/api/keywords`);
- mint video visit tokens, each good for up to 12 joins that bill Amazon Chime SDK
  attendee-minutes;
- reset or change demo data, and add, rename or remove test device registrations;
- read test device names and phone numbers, conversation transcripts, one-hour links to
  member photos, the registration's contact details, your AWS account ID and the
  account's RCS spend limits.

The key is not an AWS credential. It gives no access to your AWS account beyond
what those routes do. It is also one shared value with no per-user identity, so
you cannot tell whose request was whose, and revoking it means rotating it for
everyone.

**Where the key is and is not exposed.**

| What you do | Who can read the key | Verdict |
|---|---|---|
| `npm run dev` with the key in `web/.env`, on the default `localhost` address | The page in your browser, and anyone with access to your machine or browser profile. Vite hands the same values to the page it serves in development. | Supported |
| `npm run dev -- --host`, or the dev-server port forwarded, tunneled or shared | Anyone who can reach that port. Vite listens on `localhost` unless you change `server.host` ([server options](https://vite.dev/config/server-options)) | Do not |
| `npm run build` with the key in `web/.env` or the shell, then the `web/dist` files hosted or sent anywhere (Amazon S3, Amazon CloudFront, GitHub Pages, a zip, a chat attachment) | Anyone who can fetch the page or open the files. The key is a string in the JavaScript, and minification does not hide it | **Never** |
| The key pasted into the Settings tab (any build) | That browser profile's `localStorage`, in plaintext: `anyhealth_api_key`, plus the selected test device's phone number (`anyhealth_phone`), the API URL and the deep link. A `VITE_API_KEY` value takes precedence over the stored key. Any script that runs on the page's origin can read them | Use a browser profile you control. Hosting a build is not supported (see the paragraph after this table) |

A build made with no `VITE_API_KEY` set carries no key, so it does not leak one
by itself. It is still not a supported way to run the dashboard. The page has no
sign-in, so whoever can load it can use it, and whoever pastes a key into it
leaves that key in plaintext in the browser. Sign-in and per-user keys need the
production change in [Scope](#scope--read-this-before-deploying) (a JWT authorizer or
IAM authorization instead of the Lambda authorizer), with the dashboard hosted behind it.

**Sharing the project.** `web/.env` and `web/dist/` are both gitignored, so `git clone` and
`git archive` do not carry them. Zipping or copying your working folder does. Share the
repository with git, not a copy of the folder. If you must send a copy, delete
`web/.env` and any other `web/.env.*` file, `web/dist/`, `.deploy/` and `cdk/cdk.out/`
first, and rotate the key if a copy that held it has already left your machine (see
[Rotating the API key](#rotating-the-api-key)).

**If the key might have been exposed**, because a build or `web/.env` left your
machine, rotate it as described in [Rotating the API key](#rotating-the-api-key),
and delete the build that holds the old value.

## Deploying safely

- Follow the checklist at the top of
  [Scope — read this before deploying](#scope--read-this-before-deploying): a sandbox
  account that you own, a local-only dashboard, no real data, and `cdk destroy` when you
  are finished.
- Never commit `.deploy/` or `web/.env`: both are gitignored, and both contain
  deployment-specific values (`web/.env` holds the API key in plaintext).

### Known scanner findings

Scanners that you run on this repository can report the following items.

- A Retire.js scan of `web/` (`npx retire --path . --deep`, Retire.js 6.1.0 on
  2026-10-07) reports `lodash` 3.10.1 inside `ace-builds`, in
  `node_modules/ace-builds/src*/worker-xquery.js`, with six published advisories
  (four high, two medium: prototype pollution, and command injection in
  CVE-2021-23337). `npm audit` reports nothing, because this is a copy bundled
  inside those files, not an installed package. `ace-builds` 1.44.0 arrives
  through `@cloudscape-design/components` 3.0.1362, and its `code-editor`
  component is the only one that uses Ace. The dashboard does not import
  `code-editor`, a string search of the production build (`npm run build`) finds
  no `ace-builds`, `worker-xquery` or `lodash`, and `node_modules` is neither
  committed nor deployed, so the file sits unused on the machine that ran
  `npm ci`. As of 2026-10-14, the current releases of
  `@cloudscape-design/components` depend on `ace-builds` `^1.34.0` and the latest
  `ace-builds` is 1.44.0, so updating does not change this. `overrides` apply to
  installed packages, not to files bundled inside them. If you add `code-editor`
  to the dashboard, review this bundled copy of lodash first.
- The Lambda execution roles in the stack, including the roles that CDK creates for
  its own helper functions, use the AWS managed policy
  `AWSLambdaBasicExecutionRole` for logging, which scanners such as cdk-nag report
  as `AwsSolutions-IAM4`. The policy allows `logs:CreateLogGroup`,
  `logs:CreateLogStream` and `logs:PutLogEvents` on `Resource: "*"`, so a role can
  create log groups and streams and put log events in any log group in the account,
  not only its own function's. Each of this sample's functions keeps its other
  permissions in a separate inline policy. To limit each role to its own function's
  log group, replace the managed policy with an inline policy scoped to that group
  (the stack already creates one per function). AWS recommends that you reduce
  permissions further with customer managed policies specific to your use case
  ([Get started with AWS managed policies](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html#bp-use-aws-defined-policies)).

## Rotating the API key

The shared key is the only credential, so replacing it is the only way to revoke
it. Do this if `web/.env`, a `web/dist` build or a browser profile holding the
key might have been exposed. The stack generated the first value (32 alphanumeric
characters) when it created the secret; nothing rotates it automatically.

**1. Put a new value in the existing secret.** Generating the value with Secrets
Manager and piping it into `put-secret-value` keeps it out of your shell history
and out of any process's arguments, which the
[Secrets Manager guidance on CLI exposure](https://docs.aws.amazon.com/secretsmanager/latest/userguide/security_cli-exposure-risks.html)
warns about:

```bash
aws secretsmanager get-random-password --password-length 32 --exclude-punctuation \
  --query RandomPassword --output text --region <REGION> \
  | tr -d '\n' \
  | aws secretsmanager put-secret-value --secret-id <ApiKeySecretName> \
      --secret-string file:///dev/stdin --region <REGION>
```

`<ApiKeySecretName>` is the stack output (`<prefix>-demo-api-key`) and `<REGION>`
is the deploy Region. Keep `tr -d '\n'`: `--output text` ends the value with a
newline and `file://` passes it through, so without it the stored key ends in a
newline that no client sends. The command assumes bash or zsh on macOS, Linux or
Windows Subsystem for Linux (`/dev/stdin`). With no `--version-stages`, the new
version becomes `AWSCURRENT`, the version the authorizer reads.

**2. Then give the new key to your clients.** Read it back with the command in
[SETUP.md step 4](SETUP.md#4-retrieve-the-api-key), update `VITE_API_KEY` in
`web/.env` (restart `npm run dev` if it is running), and
re-enter the key in the Settings tab, which keeps its own copy in `localStorage`.
When `VITE_API_KEY` is set, it takes priority over the saved copy. Do this after
step 1: API Gateway caches denials as well as approvals, so a new key presented
before the secret holds it can stay refused for up to 5 minutes.

**3. Expect the old key to keep working for up to 6 minutes.** Two caches add up:

- API Gateway caches each authorizer result for 5 minutes (`resultsCacheTtl` in
  `cdk/lib/anyhealth-stack.ts`), per distinct key value.
- A warm authorizer execution environment reuses the secret it last read for up to
  60 seconds (`SECRET_CACHE_TTL_SECONDS` in `lambda/authorizer.py`).

The worst case is an approval the execution environment issues in the last moments
it still holds the old secret (60 s), which the gateway then keeps for its full 5
minutes: 300 s + 60 s = **360 s**. Secrets Manager is eventually consistent, so
allow a little longer for a change to become visible. The new key does not wait:
a request whose key does not match the execution environment's cached copy makes
the authorizer re-read the secret once before denying.

**Measured on a deployed stack.** With a rotation done at time zero, the new key
was accepted 1 second later. The old key was first refused at 299 seconds (the
gateway's 5-minute cache dominated) and was never accepted again. Rolling a
rotation back has the mirror-image delay: the gateway had cached a denial for the
key being restored, and it was accepted again only 281 seconds after the rollback.
If you restore an old value, expect the restored key to stay refused for up to
5 minutes (or reset the gateway cache, as described in the next paragraph).

**Cutting the old key off sooner.** Wait at least 60 seconds after step 1, plus a short
margin for Secrets Manager to propagate the change, so that no authorizer execution
environment still holds the old secret, then reset the gateway's cache:

```bash
aws apigatewayv2 reset-authorizers-cache --api-id <api-id> --stage-name '$default' \
  --region <REGION>
```

`<api-id>` is the first label of the `ApiUrl` output
(`https://<api-id>.execute-api.<region>.amazonaws.com`), and the stack uses the
default stage, `$default`. The call resets all authorizer cache entries on the stage
([reset-authorizers-cache](https://docs.aws.amazon.com/cli/latest/reference/apigatewayv2/reset-authorizers-cache.html)).
Do not run it earlier than the 60 seconds plus margin: an execution environment that
still holds the old secret would approve the old key again, and the gateway would
cache that approval for another 5 minutes. Lambda also drops its warm execution
environments when a function's code or configuration changes, so a deploy
that changes the authorizer function has the same effect as that 60-second wait;
a deploy that does not touch it has none.

To shorten the standing window rather than a single rotation, lower
`resultsCacheTtl` (`Duration.seconds(0)` disables the gateway cache) and run
`cdk deploy`. The worst case becomes that TTL plus 60 seconds, at the price of
more authorizer invocations.
