import { execFileSync } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import * as YAML from 'yaml';

/** Absolute path to the project root (the anyhealth/ folder). */
export const PROJECT_ROOT = path.resolve(__dirname, '..', '..');
export const CONTENT_DIR = path.join(PROJECT_ROOT, 'content');
export const MEDIA_DIR = path.join(PROJECT_ROOT, 'media');
export const LAMBDA_DIR = path.join(PROJECT_ROOT, 'lambda');
/**
 * Documents that must never travel over the carrier network. Deployed to the
 * `secure-docs/` prefix, which neither the channel adapter's role nor the bucket
 * policy for the EUM service principal lets the service read, so an object here
 * is not meant to be sendable as an RCS `FileMessage`. A send naming one was
 * refused with RESOURCE_NOT_ACCESSIBLE in testing — see anyhealth-stack.ts.
 */
export const SECURE_DOCS_DIR = path.join(PROJECT_ROOT, 'secure-docs');

export interface DeployInputs {
  /** RCS agent id (rcs-XXXX). Required — from .deploy/agent.json or -c rcsAgentId. */
  rcsAgentId: string;
  /** Region. From .deploy/agent.json or -c region. Required — must match the
   *  region the RCS agent lives in; never inherited from ambient AWS config. */
  region: string;
  /** Deployer account (CDK_DEFAULT_ACCOUNT). */
  account?: string;
  /** Bedrock model id + region (Converse API). */
  bedrockModelId: string;
  bedrockRegion: string;
  /** Slug derived from the brand name — used to name resources. */
  prefix: string;
  brandName: string;
  /**
   * Optional SMS-capable origination identity (E.164) used as the
   * FallbackConfiguration origination identity on SendRcsMessage. Absent by
   * default: a fallback needs a phone number registered for the right use
   * case, which this stack cannot provision, and sending an OTP from a number
   * registered for marketing is a compliance problem rather than a delivery
   * win. When absent, common.send_rcs omits FallbackConfiguration entirely.
   */
  smsFallbackNumber?: string;
  /**
   * The replies the EUM wiring custom resource registers as the agent's HELP,
   * STOP and UNSTOP keywords, built from content/brand.md. Absent when the
   * deployer passed -c registerKeywords=false, which makes the custom resource
   * skip the keyword step and leave the agent's keywords as they are.
   */
  keywordMessages?: KeywordMessages;
}

export interface KeywordMessages {
  help: string;
  stop: string;
  unstop: string;
}

/**
 * Longest keyword reply this stack will register. A HELP, STOP or UNSTOP reply
 * is a sentence or two, so 1000 characters stays well under the PutKeyword
 * message limit (see the AWS keywords documentation).
 */
const KEYWORD_MESSAGE_MAX_CHARS = 1000;

/** Parse the YAML frontmatter block out of a markdown file. */
export function readFrontmatter(mdPath: string): Record<string, any> {
  const raw = fs.readFileSync(mdPath, 'utf8');
  const m = raw.match(/^---\n([\s\S]*?)\n---/);
  if (!m) return {};
  return YAML.parse(m[1]) ?? {};
}

function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 20) || 'anyhealth';
}

/**
 * Read -c registerKeywords (default true). `-c registerKeywords=false` arrives
 * as the string "false", while a value in cdk.json is a boolean; both are
 * accepted. Anything else is an error rather than a guess: `-c
 * registerKeywords=no` silently meaning "yes" would write keyword replies to an
 * agent the deployer meant to leave alone.
 */
function registerKeywordsFlag(raw: unknown): boolean {
  if (raw === undefined || raw === null) return true;
  if (typeof raw === 'boolean') return raw;
  const text = String(raw).trim().toLowerCase();
  if (text === 'true') return true;
  if (text === 'false') return false;
  throw new Error(
    `registerKeywords must be "true" or "false" (got "${raw}"). It controls whether the stack ` +
      "registers the agent's HELP, STOP and UNSTOP replies on deploy; pass " +
      "-c registerKeywords=false to leave the agent's keywords alone.",
  );
}

function brandText(brand: Record<string, any>, key: string): string {
  const value = brand[key];
  return value === undefined || value === null ? '' : String(value).trim();
}

/**
 * Build the HELP, STOP and UNSTOP replies from content/brand.md, so the member
 * hears the brand and not the service's "Default Help Message" placeholder.
 *
 * The HELP reply names how to reach the brand: the phone number and email
 * address when both are set, whichever one is set otherwise, and the website
 * when neither is (brand.md requires at least one contact method, and a website
 * counts). STOP confirms the opt-out and says how to undo it, which depends on
 * the UNSTOP keyword the same step registers. Throws, naming the brand fields
 * involved, when there is no contact method or a reply comes out too long, so a
 * bad brand.md fails at synth rather than as an error buried in a Lambda log.
 */
export function buildKeywordMessages(brand: Record<string, any>, brandName: string): KeywordMessages {
  const phone = brandText(brand, 'contactPhoneNumber');
  const email = brandText(brand, 'contactEmailAddress');
  const website = brandText(brand, 'contactWebsite');

  let helpContact: string;
  if (phone && email) helpContact = `call ${phone} or email ${email}`;
  else if (phone) helpContact = `call ${phone}`;
  else if (email) helpContact = `email ${email}`;
  else if (website) helpContact = `visit ${website}`;
  else {
    throw new Error(
      'content/brand.md has no contact method, so the HELP reply cannot tell a member how to ' +
        'reach you. Set contactPhoneNumber, contactEmailAddress or contactWebsite (the agent ' +
        'registration needs one of them too), or deploy with -c registerKeywords=false to leave ' +
        'the agent\'s keywords alone.',
    );
  }

  const messages: KeywordMessages = {
    help: `${brandName}: for help ${helpContact}. Reply STOP to opt out.`,
    stop: `${brandName}: you are opted out and will receive no more messages. Reply UNSTOP to opt back in.`,
    unstop: `${brandName}: you are opted back in to messages. Reply STOP to opt out.`,
  };
  for (const [name, text] of Object.entries(messages)) {
    if (text.length > KEYWORD_MESSAGE_MAX_CHARS) {
      const source =
        name === 'help'
          ? 'brandName and the contact fields (contactPhoneNumber, contactEmailAddress, contactWebsite)'
          : 'brandName';
      throw new Error(
        `The ${name.toUpperCase()} keyword reply built from content/brand.md is ${text.length} ` +
          `characters, over the ${KEYWORD_MESSAGE_MAX_CHARS} this stack allows. It is built ` +
          `from ${source}. Shorten that, or deploy with -c registerKeywords=false.`,
      );
    }
  }
  return messages;
}

/**
 * Copy content/*.md and content/*.json into lambda/_content so they ship inside
 * every Lambda asset. Deterministic, gitignored. Called at synth time from bin/.
 *
 * The .json half is content/rcs-features.json, the RCS feature/limit registry
 * that common.validate_rcs_content and /api/vignettes read at runtime. It is
 * required, not optional: common.rcs_registry() raises if it is missing rather
 * than validating sends against nothing, so a staging filter that drops it
 * fails loudly. Checked here at synth for the same reason.
 */
export function stageContentForLambda(): void {
  const dest = path.join(LAMBDA_DIR, '_content');
  fs.rmSync(dest, { recursive: true, force: true });
  fs.mkdirSync(dest, { recursive: true });
  for (const f of fs.readdirSync(CONTENT_DIR)) {
    if (f.endsWith('.md') || f.endsWith('.json')) {
      fs.copyFileSync(path.join(CONTENT_DIR, f), path.join(dest, f));
    }
  }
  if (!fs.existsSync(path.join(dest, 'rcs-features.json'))) {
    throw new Error(
      'content/rcs-features.json is missing — the Lambdas read every RCS limit ' +
        'from it and will not start without it.',
    );
  }
}

/** Resolve all deploy inputs from .deploy/agent.json, CDK context, and env. */
export function loadDeployInputs(app: {
  node: { tryGetContext(key: string): any };
}): DeployInputs {
  const agentFile = path.join(PROJECT_ROOT, '.deploy', 'agent.json');
  let fromFile: { rcsAgentId?: string; region?: string } = {};
  if (fs.existsSync(agentFile)) {
    try {
      fromFile = JSON.parse(fs.readFileSync(agentFile, 'utf8'));
    } catch {
      /* ignore malformed file; fall back to context/env */
    }
  }

  const rcsAgentId = app.node.tryGetContext('rcsAgentId') || fromFile.rcsAgentId;

  if (!rcsAgentId) {
    throw new Error(
      'No RCS agent id found. Run the RCS agent setup (SETUP.md step 2, or AGENTS.md ' +
        'if an AI coding assistant runs it) to create .deploy/agent.json, or pass ' +
        '-c rcsAgentId=rcs-XXXX.'
    );
  }

  // The region MUST be stated explicitly, because it has to equal the region the
  // RCS agent lives in — an RCS agent is a regional resource, and every IAM ARN
  // this stack builds comes from the *stack's* region. Inheriting the region from
  // ambient config (AWS_REGION / AWS_PROFILE / CDK_DEFAULT_REGION) is never
  // right: it produces a stack that deploys perfectly and then fails on every
  // SendRcsMessage. So we fail here instead of guessing.
  const region = app.node.tryGetContext('region') || fromFile.region;
  if (!region) {
    const ambient = process.env.CDK_DEFAULT_REGION || '(none resolved)';
    throw new Error(
      'No region specified. This stack must deploy to the SAME region as your RCS ' +
        'agent, so it will not silently inherit one from your CLI configuration ' +
        `(which currently resolves to ${ambient}).\n` +
        '\n  1. Find the region your agent is actually in — check each region you may ' +
        'have used:\n' +
        '       aws pinpoint-sms-voice-v2 describe-rcs-agents --region <REGION> \\\n' +
        '         --query "RcsAgents[].RcsAgentId"\n' +
        '\n  2. Then state it, either in .deploy/agent.json:\n' +
        `       { "rcsAgentId": "${rcsAgentId}", "region": "<the region from step 1>" }\n` +
        '     or at deploy time:\n' +
        `       npx cdk deploy -c rcsAgentId=${rcsAgentId} -c region=<the region from step 1>\n` +
        `\n  Only use ${ambient} if that is genuinely where the agent lives — deploying to ` +
        'the wrong region succeeds and then fails on every send, which is why this is not ' +
        'guessed for you.'
    );
  }

  const brand = readFrontmatter(path.join(CONTENT_DIR, 'brand.md'));
  const brandName: string = brand.brandName || 'AnyHealth';

  // Checked before the optional AWS lookups below, so a bad value or a brand.md
  // that cannot produce the replies fails without touching the network.
  const keywordMessages = registerKeywordsFlag(app.node.tryGetContext('registerKeywords'))
    ? buildKeywordMessages(brand, brandName)
    : undefined;

  // Default to the `global.` cross-region inference profile, not a
  // geography-scoped one. A `us.`-prefixed default does not resolve outside US
  // regions, so it deploys cleanly and then fails every AI vignette at runtime
  // with a validation error — and since bedrockRegion defaults to the deploy
  // region, that hit anyone deploying outside the US. Checked against
  // ListInferenceProfiles: `global.anthropic.claude-sonnet-4-6` is present in
  // us-east-1, eu-central-1, eu-west-1, ap-northeast-1, ap-southeast-1,
  // ap-southeast-2 and ca-central-1, so it works wherever the RCS agent lives.
  //
  // `global.` routes the request to whichever Region has capacity, which is
  // fine for demo data but not for a real data-residency requirement. If you
  // have one, override with the profile for your geography — `us.`, `eu.`,
  // `au.` and `jp.` all carry this model. Note `apac.` does NOT (it stops at
  // claude-sonnet-4), so pick `au.` or `jp.` in Asia Pacific, and confirm with:
  //   aws bedrock list-inference-profiles --region <REGION> \
  //     --type-equals SYSTEM_DEFINED --query "inferenceProfileSummaries[].inferenceProfileId"
  const bedrockModelId =
    app.node.tryGetContext('bedrockModelId') || 'global.anthropic.claude-sonnet-4-6';
  // Bedrock region defaults to the deploy region unless explicitly overridden.
  const bedrockRegion = app.node.tryGetContext('bedrockRegion') || region;
  warnOnGeographyMismatch(bedrockModelId, bedrockRegion);

  // Validated here rather than at runtime: a malformed number produces a
  // ValidationException on every send of the verification vignette, which is a
  // slow failure to attribute to a deploy flag typed hours earlier.
  const smsFallbackNumber = app.node.tryGetContext('smsFallbackNumber') || undefined;
  if (smsFallbackNumber && !/^\+[1-9][0-9]{1,18}$/.test(smsFallbackNumber)) {
    throw new Error(
      `smsFallbackNumber must be an E.164 phone number (got "${smsFallbackNumber}"). ` +
        'It is the origination identity the SMS fallback is sent FROM — an SMS-capable ' +
        'number you already own in this account, registered for the same use case as the ' +
        'message. List yours with:\n' +
        `    aws pinpoint-sms-voice-v2 describe-phone-numbers --region ${region} \\\n` +
        '      --query "PhoneNumbers[].[PhoneNumber,NumberCapabilities]"',
    );
  }
  if (smsFallbackNumber) checkFallbackNumberIsUsable(smsFallbackNumber, region);

  return {
    rcsAgentId,
    region,
    account: process.env.CDK_DEFAULT_ACCOUNT,
    bedrockModelId,
    bedrockRegion,
    prefix: slugify(brandName),
    brandName,
    smsFallbackNumber,
    keywordMessages,
  };
}

interface PhoneNumberSummary {
  PhoneNumber: string;
  Status: string;
  NumberType: string;
  NumberCapabilities: string[];
}

/**
 * Confirm the SMS fallback number is one this account can actually send from,
 * *before* it reaches a Lambda environment variable.
 *
 * The shape check above only proves the string is E.164. common.send_rcs then
 * gates on "is SMS_FALLBACK_NUMBER non-empty", not on the number being usable,
 * so an unusable one gets attached as a FallbackConfiguration on every send —
 * and SendRcsMessage rejects the whole call when that configuration is bad. The
 * fallback would not merely be inert: it would take down the RCS message it was
 * supposed to protect. A number in PENDING is the normal way to arrive here,
 * because a freshly requested number sits there for hours (toll-free, until TFN
 * verification clears) or days (10DLC, until the campaign is approved), which is
 * exactly the window in which someone tries the flag.
 *
 * Only runs when fallback was opted into, so the default deploy path makes no
 * AWS calls and needs no extra credentials. Deliberately shells out to the AWS
 * CLI rather than adding an @aws-sdk client dependency for one read: the CLI is
 * already a hard prerequisite (creating the RCS agent needs it) and the stack
 * already uses execSync for asset bundling.
 */
function checkFallbackNumberIsUsable(number: string, region: string): void {
  let numbers: PhoneNumberSummary[];
  try {
    const out = execFileSync(
      'aws',
      [
        'pinpoint-sms-voice-v2',
        'describe-phone-numbers',
        '--region',
        region,
        '--output',
        'json',
        '--no-cli-pager',
      ],
      { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], timeout: 30_000 },
    );
    numbers = JSON.parse(out).PhoneNumbers ?? [];
  } catch (e: any) {
    // A check that cannot run must never block a deploy that would have worked —
    // same principle as warnOnGeographyMismatch. Missing CLI, no credentials, or
    // no sms-voice:DescribePhoneNumbers permission all land here, and none of
    // them mean the number is bad.
    console.warn(
      `\n[warning] Could not verify that ${number} is usable for SMS fallback — ` +
        `describe-phone-numbers did not run (${(e?.message ?? e).toString().split('\n')[0]}).\n` +
        `  Deploying anyway. If the number is not ACTIVE and SMS-capable, every send will ` +
        `fail with a ValidationException on FallbackConfiguration, including the RCS message ` +
        `itself. Check it by hand:\n` +
        `    aws pinpoint-sms-voice-v2 describe-phone-numbers --region ${region} \\\n` +
        `      --query "PhoneNumbers[].[PhoneNumber,Status,NumberCapabilities]"\n`,
    );
    return;
  }

  const match = numbers.find((p) => p.PhoneNumber === number);
  const inventory = numbers.length
    ? numbers.map((p) => `${p.PhoneNumber} (${p.Status}, ${p.NumberCapabilities.join('+')})`).join('\n      ')
    : '(this account owns no phone numbers in this Region)';

  if (!match) {
    throw new Error(
      `smsFallbackNumber ${number} is not a phone number this account owns in ${region}.\n` +
        '  It is an origination identity, not a destination — the number the SMS is sent ' +
        'FROM. A number you do not own cannot be one, and SendRcsMessage would reject every ' +
        'send that carried it.\n' +
        `  Numbers available here:\n      ${inventory}\n` +
        '  Or omit -c smsFallbackNumber to deploy RCS-only: every vignette still carries its ' +
        'fallback body, and the Settings tab reports the feature as not configured.',
    );
  }

  if (match.Status !== 'ACTIVE') {
    throw new Error(
      `smsFallbackNumber ${number} is in status ${match.Status}, not ACTIVE, so it cannot ` +
        'originate messages yet.\n' +
        '  Attaching it would make SendRcsMessage reject the whole call, so the RCS message ' +
        'would fail too — a fallback that breaks the send it protects is worse than no ' +
        'fallback. Blocked here rather than at runtime because the flag and the first failed ' +
        'send can be hours apart.\n' +
        `  ${match.NumberType === 'TOLL_FREE' ? 'Toll-free numbers stay PENDING until TFN verification is approved' : 'A 10DLC number stays PENDING until its campaign is approved'}; ` +
        'watch it with:\n' +
        `    aws pinpoint-sms-voice-v2 describe-phone-numbers --region ${region} \\\n` +
        `      --query "PhoneNumbers[?PhoneNumber=='${number}'].Status"\n` +
        '  Until then, deploy without -c smsFallbackNumber — the stack is fully functional ' +
        'RCS-only and the skipped fallbacks are logged.',
    );
  }

  if (!match.NumberCapabilities.includes('SMS')) {
    throw new Error(
      `smsFallbackNumber ${number} is ACTIVE but has no SMS capability ` +
        `(it reports ${match.NumberCapabilities.join(', ') || 'none'}). The fallback channel ` +
        'is SMS, so this number cannot carry it.\n' +
        `  Numbers available here:\n      ${inventory}`,
    );
  }

  // ACTIVE + SMS is as far as this check goes. Whether the number is
  // registered for the *use case* is a compliance decision for the deployer:
  // sending an OTP from a number registered for marketing is a compliance
  // problem. So this one warns and does not throw.
  console.warn(
    `\n[note] SMS fallback active: ${number} (${match.NumberType}, ${match.Status}).\n` +
      `  Confirm it is registered for the same use case as the messages it will carry — ` +
      `transactional traffic must not fall back through a marketing number. This stack ` +
      `leaves that check to you.\n`,
  );
}

/** Regions each CRIS geography prefix can be invoked from. `global.` is
 *  omitted because it resolves everywhere, and `us.` deliberately includes
 *  Canada — ListInferenceProfiles lists the `us.` profiles in ca-central-1. */
const GEOGRAPHY_REGIONS: Record<string, RegExp> = {
  'us.': /^(us|ca)-/,
  'eu.': /^eu-/,
  'apac.': /^ap-/,
  'au.': /^ap-southeast-(2|4|6)$/,
  'jp.': /^ap-northeast-(1|3)$/,
};

/**
 * Warn (don't fail) when an explicitly chosen geography-scoped inference
 * profile can't be invoked from the Bedrock region. Getting this wrong is
 * invisible until runtime: the stack deploys, and only the AI vignettes break,
 * with a validation error buried in Lambda logs. A warning rather than a throw
 * because AWS adds source regions to these profiles over time, and a stale
 * table here should never be able to block a deploy that would have worked.
 */
function warnOnGeographyMismatch(modelId: string, bedrockRegion: string): void {
  const prefix = Object.keys(GEOGRAPHY_REGIONS).find((p) => modelId.startsWith(p));
  if (!prefix || GEOGRAPHY_REGIONS[prefix].test(bedrockRegion)) return;
  console.warn(
    `\n[warning] bedrockModelId "${modelId}" is a ${prefix.slice(0, -1).toUpperCase()} ` +
      `inference profile, but bedrockRegion is "${bedrockRegion}". If that profile has no ` +
      `source Region there, this stack will deploy fine and every AI vignette will then fail ` +
      `at runtime with a validation error.\n` +
      `  Confirm what is actually available:\n` +
      `    aws bedrock list-inference-profiles --region ${bedrockRegion} \\\n` +
      `      --type-equals SYSTEM_DEFINED \\\n` +
      `      --query "inferenceProfileSummaries[?contains(inferenceProfileId, 'anthropic')].inferenceProfileId"\n` +
      `  Then either pass -c bedrockModelId=<a profile from that list>, or -c bedrockRegion=<a ` +
      `region the profile covers>. The default, global.anthropic.claude-sonnet-4-6, resolves ` +
      `in every Region.\n`
  );
}
