/**
 * Create one brand's RCS testing agent (registration, attachments, submit),
 * wait until it is active, optionally add your phone as a test device, and
 * record the agent in `.deploy/agent.json`.
 *
 *   node scripts/create-agent.mjs <Brand_Id> <REGION> [options]
 *
 *   --profile <name>   AWS CLI profile
 *   --phone <E.164>    also register this number as a test device (waits ~2 min first)
 *   --yes              do not ask for confirmation (required without a terminal)
 *   --dry-run          run every check, print the plan, create nothing
 *   --replace          overwrite a different agent already recorded for the brand
 *
 * Run from the repository root. Before anything is created the script checks
 * the account's RCS agent quota, the monthly RCS spend limit, that no agent
 * for this brand exists yet, and the brand's block in content/brand.md against
 * the registration form's limits. Progress is kept in
 * `.deploy/agent-setup/<brand>.json` (gitignored), so a run that stops part way
 * continues where it stopped instead of creating a second agent.
 *
 * Exit codes: 0 done (or dry run passed); 1 an AWS step failed (run again to
 * resume); 2 bad input or a check refused (nothing created).
 */
import { readFileSync } from 'node:fs';
import { createInterface } from 'node:readline/promises';
import { join, resolve } from 'node:path';
import { parseArgs } from 'node:util';
import { pathToFileURL } from 'node:url';
import { isValidBrandId, isValidRegion, readCatalog, slugify, validateBlock, CONTACT_PAIRS } from './lib/brand-catalog.mjs';
import {
  AwsError,
  clearState,
  describeAwsError,
  lookupAgent,
  makeAws,
  readAgentFile,
  readState,
  saveAgentFile,
  saveState,
  withAgent,
} from './lib/rcs-agent.mjs';

const QUOTA_CODE = 'L-AE02F3F6';
const POLL_MS = 15_000;
const POLL_MAX = 24; // about 6 minutes
const DEVICE_WAIT_MS = 125_000;

const defaultSleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** The registration field plan for a brand block: `[fieldPath, kind, value]`. */
export function fieldPlan(block, attachments) {
  const s = (k) => String(block[k] ?? '').trim();
  const plan = [];
  for (const k of ['brandName', 'serviceName', 'senderDisplayName', 'agentDescription', 'accentColor', 'privacyPolicyUrl', 'termsAndConditionsUrl', 'monthlyRcsVolume'])
    plan.push([`agentDetails.${k}`, 'text', s(k)]);
  plan.push(['agentDetails.useCase', 'select', s('useCase')]);
  plan.push(['agentDetails.averageMonthlyRcsFrequency', 'select', s('averageMonthlyRcsFrequency')]);
  plan.push(['agentDetails.billingCategory', 'select', 'CONVERSATIONAL']);
  plan.push(['agentDetails.logoImage', 'attachment', attachments.logo]);
  plan.push(['agentDetails.bannerImage', 'attachment', attachments.banner]);
  for (const [v, l] of CONTACT_PAIRS)
    if (s(v) && s(l)) {
      plan.push([`agentDetails.${v}`, 'text', s(v)]);
      plan.push([`agentDetails.${l}`, 'text', s(l)]);
    }
  plan.push(['agentDetails.privacyPolicyLabel', 'text', 'Privacy Policy']);
  plan.push(['agentDetails.termsAndConditionsLabel', 'text', 'Terms and Conditions']);
  return plan;
}

function putArgs(regId, [path, kind, value]) {
  const flag = kind === 'text' ? '--text-value' : kind === 'select' ? '--select-choices' : '--registration-attachment-id';
  return ['pinpoint-sms-voice-v2', 'put-registration-field-value', '--registration-id', regId, '--field-path', path, flag, value];
}

/**
 * Entry point. `deps` is injectable for tests: `aws`, `out`, `err`, `sleep`,
 * `confirm`, `isTTY`, `readFile`.
 */
export async function main(argv, deps = {}) {
  const out = deps.out ?? ((s) => process.stdout.write(s));
  const err = deps.err ?? ((s) => process.stderr.write(s));
  const sleep = deps.sleep ?? defaultSleep;
  const root = deps.root ?? process.cwd();
  const readFile = deps.readFile ?? ((p) => readFileSync(p));
  let parsed;
  try {
    parsed = parseArgs({
      args: argv,
      allowPositionals: true,
      options: {
        profile: { type: 'string' },
        phone: { type: 'string' },
        yes: { type: 'boolean', default: false },
        'dry-run': { type: 'boolean', default: false },
        replace: { type: 'boolean', default: false },
      },
    });
  } catch {
    err('Usage: node scripts/create-agent.mjs <Brand_Id> <REGION> [--profile P] [--phone +E164] [--yes] [--dry-run] [--replace]\n');
    return 2;
  }
  const [brand, region] = parsed.positionals;
  const o = parsed.values;
  if (parsed.positionals.length !== 2 || !isValidBrandId(brand) || !isValidRegion(region)) {
    err('Usage: node scripts/create-agent.mjs <Brand_Id> <REGION> [--profile P] [--phone +E164] [--yes] [--dry-run] [--replace]\n');
    return 2;
  }
  if (o.phone !== undefined && !/^\+[1-9][0-9]{7,14}$/.test(o.phone)) {
    err('--phone must be an E.164 number such as +15555550100.\n');
    return 2;
  }
  const refuse = (m) => {
    err(`Refused: ${m}\nNothing was created.\n`);
    return 2;
  };

  const catalog = readCatalog(root);
  if (catalog.error) return refuse(`cannot read the brand catalog: ${catalog.error}.`);
  const block = catalog.brands[brand];
  if (!block) return refuse(`"${brand}" is not in content/brand.md. Valid ids: ${Object.keys(catalog.brands).join(', ')}.`);
  const { errors, warnings } = validateBlock(brand, block, { root, readFile });
  for (const w of warnings) err(`Warning: ${w}\n`);
  if (errors.length) return refuse(`fix content/brand.md first:\n  - ${errors.join('\n  - ')}`);

  const aws = deps.aws ?? makeAws({ region, profile: o.profile });
  const brandName = String(block.brandName).trim();
  const stack = `${slugify(brandName)}-rcs-demo`;

  // ---- preflight (read-only) -------------------------------------------
  let account;
  let agents;
  try {
    account = (await aws(['sts', 'get-caller-identity']))?.Account;
    agents = (await aws(['pinpoint-sms-voice-v2', 'describe-rcs-agents']))?.RcsAgents ?? [];
  } catch (e) {
    err(`Cannot reach AWS: ${describeAwsError(e)}\n`);
    return 1;
  }
  const state = readState(root, brand);
  const file = readAgentFile(root);
  if (file.error) return refuse(`${file.error}; fix or delete it.`);
  const recorded = lookupAgent(file.doc, brand, catalog.defaultBrand);
  if (recorded && !o.replace && recorded.rcsAgentId !== state.agentId)
    return refuse(`${brand} already has agent ${recorded.rcsAgentId} recorded in .deploy/agent.json. Use that agent, or pass --replace.`);

  if (!state.agentId) {
    // Duplicate brand first: an existing agent whose registration already
    // carries this brand name is the answer even when the quota is full.
    for (const a of agents) {
      const regId = a?.TestingAgent?.RegistrationId;
      if (!regId) continue;
      try {
        const v = await aws(['pinpoint-sms-voice-v2', 'describe-registration-field-values', '--registration-id', regId, '--field-paths', 'agentDetails.brandName']);
        const name = v?.RegistrationFieldValues?.find((f) => f.FieldPath === 'agentDetails.brandName')?.TextValue;
        if (name === brandName && !o.replace)
          return refuse(`agent ${a.RcsAgentId} already exists for ${brandName}. Record it with scripts/record-agent.mjs, or pass --replace to create another.`);
      } catch {
        /* cannot tell: not a reason to refuse */
      }
    }
    // Quota: do not start a half-built agent that the account cannot hold.
    let limit = null;
    try {
      const q = await aws(['service-quotas', 'get-service-quota', '--service-code', 'sms-voice', '--quota-code', QUOTA_CODE]);
      limit = Number(q?.Quota?.Value);
    } catch {
      err('Warning: could not read the RCS agent quota (service-quotas); continuing. A full quota fails at the first create.\n');
    }
    if (Number.isFinite(limit) && agents.length >= limit)
      return refuse(
        `this account already has ${agents.length} RCS agents and the quota is ${limit}. Delete an unused agent or request an increase ` +
          `(aws service-quotas get-service-quota --service-code sms-voice --quota-code ${QUOTA_CODE}).`,
      );
    try {
      const sl = await aws(['pinpoint-sms-voice-v2', 'describe-spend-limits']);
      const rcs = sl?.SpendLimits?.find((x) => x.Name === 'RCS_MESSAGE_MONTHLY_SPEND_LIMIT');
      if (rcs && Number(rcs.MaxLimit) <= 1)
        err('Warning: the RCS monthly spend limit is $1. The deploy and Device preview still work, but real sends stop after a few dozen messages.\n');
    } catch {
      /* advisory only */
    }
  }

  const logoPath = resolve(root, String(block.logoImage));
  const bannerPath = resolve(root, String(block.bannerImage));
  out(
    [
      `Brand:    ${brand} (${brandName})`,
      `Account:  ${account ?? 'unknown'}   Region: ${region}`,
      `Agents:   ${agents.length} in the account`,
      `Plan:     create agent, enable deletion protection, create + fill + submit a TEST_RCS_LAUNCH_REGISTRATION,`,
      `          wait for the testing agent to become ACTIVE${o.phone ? ', add your phone as a test device' : ''}, record it in .deploy/agent.json`,
      `Stack:    deploy later with:  (cd cdk && npx cdk deploy -c brand=${brand})   [stack ${stack}]`,
      '',
    ].join('\n'),
  );
  if (state.agentId) out(`Resuming from ${STATE_NOTE(state)}.\n`);
  if (o['dry-run']) {
    out('Dry run: every check passed. Nothing was created.\n');
    return 0;
  }
  const tty = deps.isTTY ?? Boolean(process.stdin.isTTY && process.stdout.isTTY);
  if (!o.yes) {
    if (!tty) return refuse('no terminal to confirm on; pass --yes to proceed.');
    const answer = deps.confirm
      ? await deps.confirm(brand)
      : await (async () => {
          const rl = createInterface({ input: process.stdin, output: process.stdout });
          try {
            return await rl.question(`This creates AWS resources in account ${account}. Type the brand id (${brand}) to continue: `);
          } finally {
            rl.close();
          }
        })();
    if (String(answer).trim() !== brand) return refuse('not confirmed.');
  }

  // ---- create (resumable) -----------------------------------------------
  const st = { fields: [], ...state, brand, region };
  const save = () => saveState(root, brand, st);
  const step = async (label, fn) => {
    out(`- ${label}\n`);
    return fn();
  };
  try {
    if (!st.agentId) {
      const r = await step('create-rcs-agent', () => aws(['pinpoint-sms-voice-v2', 'create-rcs-agent']));
      st.agentId = r?.RcsAgentId;
      if (!st.agentId) throw new AwsError('NoAgentId');
      save();
    }
    if (!st.protected) {
      await step('deletion protection on', () =>
        aws(['pinpoint-sms-voice-v2', 'update-rcs-agent', '--rcs-agent-id', st.agentId, '--deletion-protection-enabled']),
      );
      st.protected = true;
      save();
    }
    if (!st.regId) {
      const r = await step('create-registration', () =>
        aws(['pinpoint-sms-voice-v2', 'create-registration', '--registration-type', 'TEST_RCS_LAUNCH_REGISTRATION']),
      );
      st.regId = r?.RegistrationId;
      if (!st.regId) throw new AwsError('NoRegistrationId');
      save();
    }
    if (!st.associated) {
      await step('associate registration with agent', () =>
        aws(['pinpoint-sms-voice-v2', 'create-registration-association', '--registration-id', st.regId, '--resource-id', st.agentId]),
      );
      st.associated = true;
      save();
    }
    for (const [key, path] of [
      ['logo', logoPath],
      ['banner', bannerPath],
    ]) {
      if (!st[`${key}Att`]) {
        const r = await step(`upload ${key}`, () =>
          aws(['pinpoint-sms-voice-v2', 'create-registration-attachment', '--attachment-body', `fileb://${path}`]),
        );
        st[`${key}Att`] = r?.RegistrationAttachmentId;
        if (!st[`${key}Att`]) throw new AwsError('NoAttachmentId');
        save();
      }
    }
    const plan = fieldPlan(block, { logo: st.logoAtt, banner: st.bannerAtt });
    if (!st.submitted) {
      for (const f of plan) {
        if (st.fields.includes(f[0])) continue;
        await step(`set ${f[0]}`, () => aws(putArgs(st.regId, f)));
        st.fields.push(f[0]);
        save();
      }
      await step('submit-registration-version', () =>
        aws(['pinpoint-sms-voice-v2', 'submit-registration-version', '--registration-id', st.regId]),
      );
      st.submitted = true;
      save();
    }
    if (!st.active) {
      out('- waiting for the testing agent to become ACTIVE\n');
      let status = '';
      for (let i = 0; i < POLL_MAX; i++) {
        const r = await aws(['pinpoint-sms-voice-v2', 'describe-rcs-agents', '--rcs-agent-ids', st.agentId]);
        status = String(r?.RcsAgents?.[0]?.TestingAgent?.Status ?? 'PENDING');
        if (status === 'ACTIVE') break;
        if (!['PENDING', 'CREATED', 'NONE', 'None'].includes(status)) {
          err(
            `The testing agent reports ${status}. Read the reason with: aws pinpoint-sms-voice-v2 describe-registration-field-values --registration-id ${st.regId} --region ${region}\n`,
          );
          return 1;
        }
        await sleep(POLL_MS);
      }
      if (status !== 'ACTIVE') {
        err('The testing agent is not ACTIVE yet. Run the same command again to keep waiting.\n');
        return 1;
      }
      st.active = true;
      st.activeAt = Date.now();
      save();
    }
    if (o.phone && !st.deviceAdded) {
      const waited = Date.now() - (st.activeAt ?? 0);
      if (waited < DEVICE_WAIT_MS) {
        out('- waiting two minutes before adding the test device\n');
        await sleep(DEVICE_WAIT_MS - waited);
      }
      await step('add test device (an invitation is sent to the phone)', () =>
        aws(['pinpoint-sms-voice-v2', 'create-verified-destination-number', '--destination-phone-number', o.phone, '--rcs-agent-id', st.agentId]),
      );
      st.deviceAdded = true;
      save();
    }
  } catch (e) {
    err(`Stopped: ${describeAwsError(e)}${e?.reason === 'RCS_AGENTS_PER_ACCOUNT' ? ' (the account is at its RCS agent quota)' : ''}\n`);
    err(`Progress is saved in .deploy/agent-setup/${brand}.json. Fix the cause and run the same command again to resume.\n`);
    return 1;
  }

  // ---- record -----------------------------------------------------------
  try {
    saveAgentFile(root, withAgent(file.doc, brand, st.agentId, region, { replace: o.replace }));
  } catch (e) {
    err(`The agent ${st.agentId} exists but could not be recorded: ${e instanceof Error ? e.message : 'write failed'}\nUse: node scripts/record-agent.mjs ${brand} ${st.agentId} ${region}\n`);
    return 1;
  }
  clearState(root, brand);
  out(`\nDone. Agent ${st.agentId} is recorded for ${brand} in .deploy/agent.json.\n`);
  if (o.phone) out('Accept the invitation on the phone ("Make me a tester"); it arrives in 2 to 20 minutes.\n');
  out(`Next: (cd cdk && npx cdk diff -c brand=${brand}), then deploy after you approve the diff.\n`);
  return 0;
}

function STATE_NOTE(s) {
  return s.submitted ? 'the saved state (registration submitted)' : 'the saved state';
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) {
  main(process.argv.slice(2)).then(
    (code) => {
      process.exitCode = code;
    },
    () => {
      process.stderr.write("Unexpected error.\n");
      process.exitCode = 1;
    },
  );
}
