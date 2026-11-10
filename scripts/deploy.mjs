/**
 * Deploy one or more brands of the demo, each as its own stack with its own
 * RCS agent.
 *
 *   node scripts/deploy.mjs [--brands <id,id,...|all>] --region <REGION> [options]
 *
 *   --brands <list>        brand ids, comma-separated, or `all`. In a terminal you
 *                          can leave it off and pick from a list.
 *   --region <REGION>      the Region for the agents and the stacks (required)
 *   --phone <E.164>        your phone: sent a tester invitation from each brand's agent
 *   --profile <name>       AWS CLI profile (also used for cdk)
 *   --context k=v          extra cdk context, repeatable (for example bedrockModelId=...)
 *   --check-bedrock        also make one real, small Amazon Bedrock call (costs a few
 *                          tokens; the first call can subscribe the account to the model)
 *   --plan-only            run pre-flight and print the plan; change nothing
 *   --yes                  confirm without a prompt (required without a terminal)
 *
 * Run from the repository root. The run has three stages:
 *
 *   1. Pre-flight (read-only). Checks the tools, the account, the agent quota,
 *      the spend limit, each brand's registration values, whether each brand
 *      already has an agent and a stack, and runs `cdk diff` for each brand.
 *      Every blocker for every brand is reported at once.
 *   2. Plan. One summary of what will be created or changed, including IAM
 *      changes, and one confirmation.
 *   3. Deploy, one brand after another: create the agent if needed, `cdk deploy`,
 *      wire the dashboard, send the tester invitation. A brand that fails is
 *      skipped and the run carries on; the summary says which step failed, why,
 *      what already exists, and the command that resumes it.
 *
 * Logs: `.deploy/logs/<brand>-plan.diff`, `.deploy/logs/<brand>-deploy.log`
 * (gitignored).
 *
 * Exit codes: 0 every brand deployed (or the plan was printed); 1 one or more
 * brands failed; 2 bad input or pre-flight blocked the run (nothing changed).
 */
import { spawn as nodeSpawn } from 'node:child_process';
import { createWriteStream, mkdirSync, readFileSync } from 'node:fs';
import { createInterface } from 'node:readline/promises';
import { join } from 'node:path';
import { parseArgs } from 'node:util';
import { pathToFileURL } from 'node:url';
import { isValidBrandId, isValidRegion, readCatalog, slugify, validateBlock } from './lib/brand-catalog.mjs';
import { AwsError, describeAwsError, lookupAgent, makeAws, readAgentFile, readState } from './lib/rcs-agent.mjs';
import { main as createAgentMain } from './create-agent.mjs';
import { main as recordAgentMain } from './record-agent.mjs';

const QUOTA_CODE = 'L-AE02F3F6';
const PLACEHOLDER_AGENT = 'rcs-00000000000000000000000000000000';
const DEVICE_WAIT_MS = 125_000;
const USAGE =
  'Usage: node scripts/deploy.mjs [--brands <id,id|all>] --region <REGION> [--phone +E164] [--profile P]\n' +
  '                               [--context k=v ...] [--check-bedrock] [--plan-only] [--yes]\n';

/**
 * Run a command with an argument array (no shell). Resolves `{ code, out }`
 * where `out` is stdout+stderr; when `log` is a path, output is also written there.
 */
export function makeRun({ spawn = nodeSpawn, env = process.env } = {}) {
  return (cmd, args, { cwd, log, extraEnv } = {}) =>
    new Promise((resolve) => {
      let out = '';
      let stream = null;
      if (log) {
        mkdirSync(join(log, '..'), { recursive: true, mode: 0o700 });
        stream = createWriteStream(log, { mode: 0o600 });
      }
      let child;
      try {
        child = spawn(cmd, args, { cwd, env: { ...env, ...extraEnv }, stdio: ['ignore', 'pipe', 'pipe'] });
      } catch {
        resolve({ code: 127, out: 'command not found' });
        return;
      }
      const onData = (d) => {
        out += d;
        if (out.length > 4_000_000) out = out.slice(-2_000_000);
        stream?.write(d);
      };
      child.stdout.on('data', onData);
      child.stderr.on('data', onData);
      child.on('error', () => {
        stream?.end();
        resolve({ code: 127, out: 'command not found' });
      });
      child.on('close', (code) => {
        stream?.end();
        resolve({ code: code ?? 1, out });
      });
    });
}

/** Summarize `cdk diff` output: resource counts and IAM statement changes. */
export function summarizeDiff(text) {
  const lines = String(text).split('\n');
  const count = (re) => lines.filter((l) => re.test(l)).length;
  const added = count(/^\[\+\] AWS::/);
  const changed = count(/^\[~\] AWS::/);
  const removed = count(/^\[-\] AWS::/);
  let iam = 0;
  let inIam = false;
  for (const l of lines) {
    if (/^IAM Statement Changes|^IAM Policy Changes/.test(l)) inIam = true;
    else if (/^(Security Group Changes|Resources|Parameters|Outputs|Conditions)\b/.test(l)) inIam = false;
    else if (inIam && /^│ [+-] │/.test(l)) iam++;
  }
  const replaced = count(/may be replaced|requires replacement/);
  return { added, changed, removed, iam, replaced, noChanges: /There were no differences|Number of stacks with differences: 0/.test(text) };
}

/** The useful lines of a failed `cdk deploy`, for the summary. */
export function failureLines(text) {
  return String(text)
    .split('\n')
    .filter((l) => /(CREATE|UPDATE|DELETE)_FAILED|❌|Error:|ValidationError|is in .*state and can not be updated/.test(l))
    .filter((l) => !/Resource creation cancelled|Resource update cancelled/.test(l))
    .map((l) => l.replace(/\s+/g, ' ').trim().slice(0, 400))
    .slice(0, 6);
}

/** Pick brands interactively: numbers or ids, comma-separated, or `all`. */
async function pickBrands(catalog, ask) {
  const ids = Object.keys(catalog.brands);
  const lines = ids.map((id, i) => {
    const b = catalog.brands[id];
    return `  ${i + 1}. ${id.padEnd(10)} ${String(b.displayName ?? b.brandName ?? id)}: ${String(b.lineOfBusiness ?? '').slice(0, 70)}`;
  });
  const answer = await ask(`Brands in this demo:\n${lines.join('\n')}\nWhich brands? (numbers or ids, comma-separated, or "all"): `);
  return parseBrandList(answer, ids);
}

/** Turn `1,3`, `anyhealth,anytravel` or `all` into ids. Returns `{ ids }` or `{ error }`. */
export function parseBrandList(text, valid) {
  const raw = String(text ?? '').trim();
  if (!raw) return { error: 'no brands chosen' };
  if (raw.toLowerCase() === 'all') return { ids: [...valid] };
  const ids = [];
  for (const part of raw.split(/[\s,]+/).filter(Boolean)) {
    const n = Number(part);
    const id = Number.isInteger(n) && n >= 1 && n <= valid.length ? valid[n - 1] : part.toLowerCase();
    if (!valid.includes(id)) return { error: `"${part}" is not a brand. Valid ids: ${valid.join(', ')}` };
    if (!ids.includes(id)) ids.push(id);
  }
  return { ids };
}

export async function main(argv, deps = {}) {
  const out = deps.out ?? ((s) => process.stdout.write(s));
  const err = deps.err ?? ((s) => process.stderr.write(s));
  const root = deps.root ?? process.cwd();
  const sleep = deps.sleep ?? ((ms) => new Promise((r) => setTimeout(r, ms)));
  const now = deps.now ?? (() => Date.now());
  const tty = deps.isTTY ?? Boolean(process.stdin.isTTY && process.stdout.isTTY);
  const ask =
    deps.ask ??
    (async (q) => {
      const rl = createInterface({ input: process.stdin, output: process.stdout });
      try {
        return await rl.question(q);
      } finally {
        rl.close();
      }
    });

  let parsed;
  try {
    parsed = parseArgs({
      args: argv,
      allowPositionals: false,
      options: {
        brands: { type: 'string' },
        region: { type: 'string' },
        phone: { type: 'string' },
        profile: { type: 'string' },
        context: { type: 'string', multiple: true, default: [] },
        'check-bedrock': { type: 'boolean', default: false },
        'plan-only': { type: 'boolean', default: false },
        yes: { type: 'boolean', default: false },
      },
    });
  } catch (e) {
    err(USAGE);
    return 2;
  }
  const o = parsed.values;
  if (!isValidRegion(o.region)) {
    err(`--region is required and must be a Region name such as us-east-1.\n${USAGE}`);
    return 2;
  }
  if (o.phone !== undefined && !/^\+[1-9][0-9]{7,14}$/.test(o.phone)) {
    err('--phone must be an E.164 number such as +15555550100.\n');
    return 2;
  }
  const extraContext = [];
  for (const c of o.context) {
    const m = /^([A-Za-z][A-Za-z0-9]*)=(.*)$/.exec(c);
    if (!m || ['brand', 'rcsAgentId', 'region'].includes(m[1])) {
      err(`--context ${c}: use key=value; brand, rcsAgentId and region are set by this script.\n`);
      return 2;
    }
    extraContext.push('-c', `${m[1]}=${m[2]}`);
  }
  const catalog = readCatalog(root);
  if (catalog.error) {
    err(`Cannot read the brand catalog: ${catalog.error}.\n`);
    return 2;
  }
  const allIds = Object.keys(catalog.brands);
  let picked;
  if (o.brands !== undefined) picked = parseBrandList(o.brands, allIds);
  else if (tty) picked = await pickBrands(catalog, ask);
  else picked = { error: 'pass --brands (no terminal to pick on)' };
  if (picked.error) {
    err(`${picked.error}.\n`);
    return 2;
  }
  const brands = picked.ids;
  const region = o.region;
  const profileEnv = o.profile ? { AWS_PROFILE: o.profile } : {};
  const aws = deps.aws ?? makeAws({ region, profile: o.profile });
  const run = deps.run ?? makeRun();
  const logDir = join(root, '.deploy', 'logs');

  // ───────────────────────── 1. Pre-flight ─────────────────────────
  out(`Pre-flight for ${brands.join(', ')} in ${region} (read-only)\n`);
  const blockers = []; // { brand|null, text, fix }
  const warnings = [];
  const block = (brand, text, fix) => blockers.push({ brand, text, fix });

  // Tools
  const node = Number(/^v(\d+)/.exec(process.version)?.[1]);
  if (node < 22) block(null, `Node.js ${process.version} is too old`, 'Install Node.js 22 or later (`nvm use` reads .nvmrc).');
  const cli = await run('aws', ['pinpoint-sms-voice-v2', 'set-rcs-message-spend-limit-override', '--generate-cli-skeleton']);
  if (cli.code === 127) block(null, 'The AWS CLI is not installed', 'Install AWS CLI v2 2.35.12 or later.');
  else if (cli.code !== 0) block(null, 'This AWS CLI has no RCS commands', 'Upgrade to AWS CLI v2 2.35.12 or later.');
  const pip = await run('python3', ['-m', 'pip', '--version']);
  const pyOk = (() => {
    const m = /pip (\d+)\.(\d+).*\(python (\d+)\.(\d+)\)/.exec(pip.out);
    if (pip.code !== 0 || !m) return false;
    return Number(m[3]) * 100 + Number(m[4]) >= 310 || Number(m[1]) * 100 + Number(m[2]) >= 2402;
  })();
  if (!pyOk) {
    const docker = await run('docker', ['info']);
    if (docker.code !== 0)
      block(null, 'Neither python3 3.10+ (or pip 24.2+) nor a running Docker was found', 'Upgrade pip, set PYTHON=/path/to/python3, or start Docker.');
  }
  const cdkDeps = await run('node', ['-e', "require.resolve('aws-cdk-lib')"], { cwd: join(root, 'cdk') });
  if (cdkDeps.code !== 0) block(null, 'The CDK dependencies are not installed', 'Run: (cd cdk && npm ci)');

  // Account
  let account = null;
  let agents = [];
  try {
    account = (await aws(['sts', 'get-caller-identity']))?.Account ?? null;
    agents = (await aws(['pinpoint-sms-voice-v2', 'describe-rcs-agents']))?.RcsAgents ?? [];
  } catch (e) {
    block(null, `Cannot reach AWS (${describeAwsError(e)})`, 'Sign in (aws sso login or aws configure), then run this again.');
  }

  // Each brand's state
  const agentFile = readAgentFile(root);
  if (agentFile.error) block(null, agentFile.error, 'Fix or delete .deploy/agent.json.');
  const doc = agentFile.doc ?? {};
  const nameOf = async (regId) => {
    try {
      const v = await aws(['pinpoint-sms-voice-v2', 'describe-registration-field-values', '--registration-id', regId, '--field-paths', 'agentDetails.brandName']);
      return v?.RegistrationFieldValues?.find((f) => f.FieldPath === 'agentDetails.brandName')?.TextValue ?? null;
    } catch {
      return null;
    }
  };
  const agentNames = new Map();
  if (account) for (const a of agents) if (a?.TestingAgent?.RegistrationId) agentNames.set(a.RcsAgentId, await nameOf(a.TestingAgent.RegistrationId));

  const plan = [];
  for (const id of brands) {
    const blk = catalog.brands[id];
    const brandName = String(blk.brandName ?? '').trim();
    const stack = `${slugify(brandName)}-rcs-demo`;
    const p = { id, brandName, stack, agent: null, agentAction: null, stackAction: null, diff: null, invite: false };
    plan.push(p);
    const v = validateBlock(id, blk, { root });
    for (const w of v.warnings) warnings.push(`${id}: ${w}`);
    for (const e of v.errors) block(id, e, 'Fix that value in content/brand.md.');
    if (!account) continue;

    // Agent: recorded, else an existing agent registered as this brand, else create.
    const recorded = lookupAgent(doc, id, catalog.defaultBrand);
    const live = (aid) => agents.find((a) => a.RcsAgentId === aid);
    if (readState(root, id).agentId) {
      p.agent = readState(root, id).agentId;
      p.agentAction = 'resume';
    } else if (recorded && recorded.region && recorded.region !== region) {
      // Checked before liveness: `agents` lists only --region, so an agent
      // recorded in another Region would otherwise look deleted.
      block(id, `its recorded agent is in ${recorded.region}, not ${region}`, `Deploy ${id} with --region ${recorded.region}, or record another agent.`);
      p.agent = recorded.rcsAgentId;
      p.agentAction = 'reuse';
    } else if (recorded && live(recorded.rcsAgentId)) {
      const name = agentNames.get(recorded.rcsAgentId);
      if (name && name !== brandName)
        block(id, `the recorded agent is registered as "${name}"`, `Record ${brandName}'s agent: node scripts/record-agent.mjs ${id} <AGENT_ID> ${region}`);
      p.agent = recorded.rcsAgentId;
      p.agentAction = 'reuse';
    } else {
      const match = agents.find((a) => agentNames.get(a.RcsAgentId) === brandName);
      if (match) {
        p.agent = match.RcsAgentId;
        p.agentAction = 'record';
      } else {
        p.agentAction = 'create';
        if (recorded) {
          // The approved plan says so, so create-agent may replace the entry.
          p.replaceRecorded = true;
          warnings.push(`${id}: the recorded agent no longer exists; a new one will be created`);
        }
      }
    }
    const liveAgent = p.agent ? live(p.agent) : null;
    if (liveAgent && liveAgent.TestingAgent?.Status && liveAgent.TestingAgent.Status !== 'ACTIVE' && p.agentAction !== 'resume')
      block(id, `its agent's testing status is ${liveAgent.TestingAgent.Status}`, 'Check the registration with describe-registration-field-values (look for DeniedReason).');

    // Stack
    try {
      const s = await aws(['cloudformation', 'describe-stacks', '--stack-name', stack]);
      const status = s?.Stacks?.[0]?.StackStatus ?? 'UNKNOWN';
      p.stackAction = 'update';
      if (/_IN_PROGRESS$/.test(status)) {
        block(id, `stack ${stack} is ${status}`, 'Wait for it to finish, then run this again.');
        p.stackAction = `blocked (${status})`;
      } else if (status === 'ROLLBACK_COMPLETE' || status === 'ROLLBACK_FAILED' || status === 'DELETE_FAILED') {
        block(id, `stack ${stack} is ${status} and cannot be updated`, `Delete it: aws cloudformation delete-stack --stack-name ${stack} --region ${region}`);
        p.stackAction = `blocked (${status})`;
      }
      // Two-way already pointing somewhere else?
      const topic = (s?.Stacks?.[0]?.Outputs ?? []).find((x) => /Topic/i.test(x.OutputKey))?.OutputValue;
      if (liveAgent?.TwoWayChannelArn && topic && liveAgent.TwoWayChannelArn !== topic)
        warnings.push(`${id}: the agent's two-way messaging points at another topic; the deploy repoints it at ${stack}`);
    } catch (e) {
      if (e instanceof AwsError && e.code === 'ValidationError') p.stackAction = 'create';
      else block(id, `cannot read stack ${stack} (${describeAwsError(e)})`, 'Check your permissions, then run this again.');
    }
    if (liveAgent?.TwoWayChannelArn && p.stackAction === 'create')
      warnings.push(`${id}: the agent already has two-way messaging set up; the deploy repoints it at ${stack}`);

    // Tester invitation needed?
    if (o.phone) {
      if (!p.agent) p.invite = true;
      else {
        try {
          const d = await aws(['pinpoint-sms-voice-v2', 'describe-verified-destination-numbers', '--destination-phone-numbers', o.phone]);
          const mine = (d?.VerifiedDestinationNumbers ?? []).find((x) => x.RcsAgentId === p.agent);
          p.invite = !mine;
          p.deviceStatus = mine?.Status ?? null;
        } catch {
          p.invite = true; // ResourceNotFoundException: the number is not registered anywhere yet
        }
      }
    }
  }

  // Account-wide
  if (account) {
    const toCreate = plan.filter((p) => p.agentAction === 'create').length;
    if (toCreate) {
      try {
        const q = await aws(['service-quotas', 'get-service-quota', '--service-code', 'sms-voice', '--quota-code', QUOTA_CODE]);
        const limit = Number(q?.Quota?.Value);
        const free = limit - agents.length;
        if (Number.isFinite(limit) && free < toCreate)
          block(
            null,
            `${toCreate} new RCS agent(s) are needed but only ${Math.max(free, 0)} of ${limit} slots are free (${agents.length} agents exist)`,
            `Deploy fewer brands, delete an agent nothing uses (node scripts/delete-agent.mjs), or request an increase for quota ${QUOTA_CODE} in Service Quotas.`,
          );
      } catch {
        warnings.push('could not read the RCS agent quota; a full quota fails at the first new agent');
      }
    }
    try {
      const sl = await aws(['pinpoint-sms-voice-v2', 'describe-spend-limits']);
      const rcs = sl?.SpendLimits?.find((x) => x.Name === 'RCS_MESSAGE_MONTHLY_SPEND_LIMIT');
      if (rcs && Number(rcs.EnforcedLimit) <= 1)
        warnings.push('the RCS monthly spend limit is $1: the deploy works, but real sends stop after a few dozen messages (SETUP.md, RCS monthly spend limit)');
    } catch {
      /* advisory */
    }
    try {
      await aws(['ssm', 'get-parameter', '--name', '/cdk-bootstrap/hnb659fds/version']);
    } catch {
      warnings.push(`CDK is not bootstrapped in ${region}: the run starts with cdk bootstrap (creates the CDKToolkit stack)`);
      plan.bootstrap = true;
    }
    if (o['check-bedrock']) {
      const model = (o.context.find((c) => c.startsWith('bedrockModelId=')) ?? '').split('=')[1] || 'global.anthropic.claude-sonnet-4-6';
      const bRegion = (o.context.find((c) => c.startsWith('bedrockRegion=')) ?? '').split('=')[1] || region;
      const r = await run('aws', [
        'bedrock-runtime', 'converse', '--region', bRegion, '--model-id', model,
        '--messages', '[{"role":"user","content":[{"text":"Reply with OK."}]}]',
        '--inference-config', '{"maxTokens":16}', '--output', 'text', '--query', 'output.message.content[0].text',
        ...(o.profile ? ['--profile', o.profile] : []),
      ]);
      if (r.code !== 0) {
        const code = /An error occurred \((\w+)\)/.exec(r.out)?.[1] ?? 'call failed';
        warnings.push(`Amazon Bedrock check failed (${code}): the AI use case examples will not answer until access works (SETUP.md, Amazon Bedrock access)`);
      }
    } else {
      warnings.push('Amazon Bedrock access was not checked (add --check-bedrock); only the AI use case examples need it');
    }
  }

  // cdk diff per brand, only when nothing else blocks (it is slow and needs the tools).
  if (!blockers.length) {
    for (const p of plan) {
      out(`- cdk diff ${p.id} ...\n`);
      const agentArgs = p.agent ? ['-c', `rcsAgentId=${p.agent}`, '-c', `region=${region}`] : ['-c', `rcsAgentId=${PLACEHOLDER_AGENT}`, '-c', `region=${region}`, '-c', 'skipAgentCheck=true'];
      const log = join(logDir, `${p.id}-plan.diff`);
      const r = await run('npx', ['cdk', 'diff', '-c', `brand=${p.id}`, ...agentArgs, ...extraContext], { cwd: join(root, 'cdk'), log, extraEnv: profileEnv });
      if (r.code !== 0) {
        block(p.id, `cdk diff failed: ${failureLines(r.out)[0] ?? 'see the log'}`, `Read .deploy/logs/${p.id}-plan.diff`);
        continue;
      }
      p.diff = summarizeDiff(r.out);
    }
  }

  // ───────────────────────── 2. Plan ─────────────────────────
  const lines = [`\nAccount ${account ?? 'unknown'}   Region ${region}\n`];
  for (const p of plan) {
    const agentText = {
      create: 'CREATE a new RCS testing agent (registration fees may apply)',
      reuse: `reuse ${p.agent}`,
      record: `reuse ${p.agent} (exists, not yet recorded)`,
      resume: `RESUME creating ${p.agent}`,
    }[p.agentAction] ?? 'unknown';
    const d = p.diff;
    const diffText = !d
      ? ''
      : d.noChanges
        ? 'no changes'
        : `${d.added} to add, ${d.changed} to change, ${d.removed} to remove${d.iam ? `, ${d.iam} IAM statement change(s)` : ', no IAM changes'}${d.replaced ? `, ${d.replaced} replacement(s)` : ''}`;
    lines.push(
      `${p.id.padEnd(10)} agent: ${agentText}\n` +
        `${''.padEnd(10)} stack: ${p.stackAction === 'create' ? 'CREATE' : (p.stackAction ?? '?')} ${p.stack}${diffText ? ` (${diffText})` : ''}\n` +
        (o.phone ? `${''.padEnd(10)} phone: ${p.invite ? 'send a tester invitation' : `already a tester (${p.deviceStatus})`}\n` : ''),
    );
  }
  if (plan.bootstrap) lines.push('Also: cdk bootstrap (once per account and Region)\n');
  lines.push('Also: wire each brand into the local dashboard (.deploy/dashboard-brands.json)\n');
  if (plan.some((p) => p.diff)) lines.push('Full diffs: .deploy/logs/<brand>-plan.diff\n');
  out(lines.join(''));
  if (warnings.length) out(`\nWarnings:\n${warnings.map((w) => `  - ${w}`).join('\n')}\n`);
  if (blockers.length) {
    out(`\nBlocked. Fix these, then run the same command again (nothing was changed):\n`);
    for (const b of blockers) out(`  - ${b.brand ? `${b.brand}: ` : ''}${b.text}\n      fix: ${b.fix}\n`);
    return 2;
  }
  if (o['plan-only']) {
    out('\nPlan only: nothing was changed.\n');
    return 0;
  }
  if (!o.yes) {
    if (!tty) {
      err('\nNo terminal to confirm on; review the plan, then run again with --yes.\n');
      return 2;
    }
    const a = await ask('\nType "deploy" to put this in place: ');
    if (String(a).trim() !== 'deploy') {
      out('Not confirmed; nothing was changed.\n');
      return 2;
    }
  }

  // ───────────────────────── 3. Deploy ─────────────────────────
  if (plan.bootstrap) {
    out('\n== cdk bootstrap\n');
    // Bootstrap synthesizes the app, which needs an agent id; no agent may exist yet.
    const r = await run('npx', ['cdk', 'bootstrap', '-c', `brand=${plan[0].id}`, '-c', `rcsAgentId=${PLACEHOLDER_AGENT}`, '-c', 'skipAgentCheck=true', '-c', `region=${region}`], {
      cwd: join(root, 'cdk'),
      log: join(logDir, 'bootstrap.log'),
      extraEnv: profileEnv,
    });
    if (r.code !== 0) {
      out(`cdk bootstrap failed; nothing else was run. ${failureLines(r.out).join(' | ')}\nLog: .deploy/logs/bootstrap.log\n`);
      return 1;
    }
  }
  const results = [];
  for (const p of plan) {
    out(`\n== ${p.id}\n`);
    const res = { id: p.id, ok: false, step: null, why: [], exists: [], resume: null, invite: null, keywords: null };
    results.push(res);
    // The same --context options as this run, so a resume deploys the same way.
    const contextArgs = o.context.map((c) => ` --context ${/^[\w.:+\/=@-]+$/.test(c) ? c : `'${c.replace(/'/g, `'\\''`)}'`}`).join('');
    const resumeCmd = `node scripts/deploy.mjs --brands ${p.id} --region ${region}${o.phone ? ` --phone ${o.phone}` : ''}${o.profile ? ` --profile ${o.profile}` : ''}${contextArgs}`;
    // Agent
    if (p.agentAction === 'create' || p.agentAction === 'resume') {
      res.step = 'create the RCS agent';
      const buf = { out: '', err: '' };
      const code = await createAgentMain([p.id, region, '--yes', ...(p.replaceRecorded ? ['--replace'] : []), ...(o.profile ? ['--profile', o.profile] : [])], {
        root,
        aws,
        sleep,
        out: (s) => {
          buf.out += s;
          if (/^- /.test(s)) out(`  ${s}`);
        },
        err: (s) => (buf.err += s),
      });
      const recorded = lookupAgent(readAgentFile(root).doc ?? {}, p.id, catalog.defaultBrand);
      if (code !== 0 || !recorded) {
        res.why = buf.err.trim().split('\n').slice(0, 4);
        const st = readState(root, p.id);
        if (st.agentId) res.exists.push(`agent ${st.agentId} (partly set up; progress in .deploy/agent-setup/${p.id}.json)`);
        else res.exists.push('nothing for this brand');
        res.resume = resumeCmd;
        out(`  failed: ${res.why[0] ?? 'see above'}\n`);
        continue;
      }
      p.agent = recorded.rcsAgentId;
      p.activeAt = now();
    } else if (p.agentAction === 'record') {
      res.step = 'record the existing agent';
      const buf = { err: '' };
      const code = await recordAgentMain([p.id, p.agent, region], { root, aws, out: () => {}, err: (s) => (buf.err += s) });
      if (code !== 0) {
        res.why = buf.err.trim().split('\n').slice(0, 3);
        res.exists.push(`agent ${p.agent} (not recorded)`);
        res.resume = `node scripts/record-agent.mjs ${p.id} ${p.agent} ${region}, then: ${resumeCmd}`;
        continue;
      }
    }
    res.exists.push(`agent ${p.agent}`);
    // Stack
    res.step = 'cdk deploy';
    out(`  - cdk deploy ${p.stack} (several minutes; log .deploy/logs/${p.id}-deploy.log)\n`);
    const d = await run('npx', ['cdk', 'deploy', '-c', `brand=${p.id}`, '--require-approval', 'never', ...extraContext], {
      cwd: join(root, 'cdk'),
      log: join(logDir, `${p.id}-deploy.log`),
      extraEnv: profileEnv,
    });
    if (d.code !== 0) {
      res.why = failureLines(d.out);
      if (!res.why.length) res.why = ['cdk deploy exited without a CloudFormation error; read the log'];
      try {
        const s = await aws(['cloudformation', 'describe-stacks', '--stack-name', p.stack]);
        const status = s?.Stacks?.[0]?.StackStatus;
        res.exists.push(`stack ${p.stack} (${status})`);
        if (status === 'ROLLBACK_COMPLETE') res.resume = `aws cloudformation delete-stack --stack-name ${p.stack} --region ${region}, wait for it, then: ${resumeCmd}`;
      } catch {
        res.exists.push(`no stack ${p.stack}`);
      }
      res.resume ??= resumeCmd;
      res.log = `.deploy/logs/${p.id}-deploy.log`;
      out(`  failed: ${res.why[0]}\n`);
      continue;
    }
    res.exists.push(`stack ${p.stack}`);
    try {
      const s = await aws(['cloudformation', 'describe-stacks', '--stack-name', p.stack]);
      res.keywords = (s?.Stacks?.[0]?.Outputs ?? []).find((x) => x.OutputKey === 'KeywordsStatus')?.OutputValue ?? null;
    } catch {
      /* summary only */
    }
    // Dashboard
    res.step = 'wire the dashboard';
    out('  - wire the dashboard\n');
    const w = await run('node', ['scripts/wire-dashboard-brand.mjs', p.id, region, ...(o.profile ? [o.profile] : [])], { cwd: root });
    if (w.code !== 0) {
      res.why = [w.out.trim().split('\n').slice(-1)[0] ?? 'the wiring command failed'];
      res.resume = `node scripts/wire-dashboard-brand.mjs ${p.id} ${region}${o.profile ? ` ${o.profile}` : ''}`;
      continue;
    }
    // Invitation (sent, not awaited)
    if (o.phone && p.invite) {
      res.step = 'send the tester invitation';
      const wait = DEVICE_WAIT_MS - (now() - (p.activeAt ?? 0));
      if (p.activeAt && wait > 0) {
        out('  - waiting until the agent has been active two minutes\n');
        await sleep(wait);
      }
      try {
        await aws(['pinpoint-sms-voice-v2', 'create-verified-destination-number', '--destination-phone-number', o.phone, '--rcs-agent-id', p.agent]);
        res.invite = 'sent';
        out('  - tester invitation sent\n');
      } catch (e) {
        res.invite = `not sent (${describeAwsError(e)})`;
      }
    } else if (o.phone) res.invite = p.deviceStatus ?? 'already a tester';
    res.ok = true;
    res.step = null;
  }

  // ───────────────────────── Summary ─────────────────────────
  out('\n================ Summary ================\n');
  for (const r of results) {
    if (r.ok) {
      out(`${r.id.padEnd(10)} OK      keywords: ${r.keywords ?? 'n/a'}${r.invite ? `   tester: ${r.invite}` : ''}\n`);
    } else {
      out(`${r.id.padEnd(10)} FAILED  at: ${r.step}\n`);
      for (const w of r.why) out(`           why: ${w}\n`);
      out(`           exists now: ${r.exists.join('; ')}\n`);
      if (r.log) out(`           log: ${r.log}\n`);
      out(`           to resume: ${r.resume}\n`);
    }
  }
  const ok = results.filter((r) => r.ok);
  if (ok.length) {
    out('\nNext: start the dashboard with  (cd web && npm ci && npm run dev)  and open http://localhost:5173.\n');
    if (o.phone && ok.some((r) => r.invite === 'sent'))
      out('Accept each "RBM Tester Management" invitation on your phone (Make me a tester); they arrive within 2 to 20 minutes. On an iPhone, check Unknown Senders.\n');
  }
  return results.every((r) => r.ok) ? 0 : 1;
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) {
  main(process.argv.slice(2)).then(
    (c) => {
      process.exitCode = c;
    },
    () => {
      process.stderr.write("Unexpected error.\n");
      process.exitCode = 1;
    },
  );
}
