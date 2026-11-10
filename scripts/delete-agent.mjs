/**
 * Delete one brand's RCS agent and everything that hangs off it.
 *
 *   node scripts/delete-agent.mjs <Brand_Id> <REGION> [--agent-id rcs-...] [--profile P] [--yes] [--dry-run]
 *
 * The agent is taken from `--agent-id`, else from `.deploy/agent.json`. The
 * script refuses unless (1) the agent's registration brand name is this
 * brand's, and (2) the brand's CloudFormation stack is gone (the stack's
 * two-way wiring points at the agent; tear the stack down first).
 * Order: test devices, deletion protection off, registration, agent. The agent
 * delete is retried while the service still reports RESOURCE_NOT_EMPTY.
 *
 * Exit codes: 0 deleted (or dry run passed); 1 an AWS step failed; 2 bad input
 * or a check refused (nothing deleted).
 */
import { createInterface } from 'node:readline/promises';
import { parseArgs } from 'node:util';
import { pathToFileURL } from 'node:url';
import { isValidAgentId, isValidBrandId, isValidRegion, readCatalog, slugify } from './lib/brand-catalog.mjs';
import { AwsError, describeAwsError, lookupAgent, makeAws, readAgentFile, saveAgentFile, withoutAgent } from './lib/rcs-agent.mjs';

const USAGE = 'Usage: node scripts/delete-agent.mjs <Brand_Id> <REGION> [--agent-id rcs-...] [--profile P] [--yes] [--dry-run]\n';
const RETRIES = 6;
const RETRY_MS = 15_000;

export async function main(argv, deps = {}) {
  const out = deps.out ?? ((s) => process.stdout.write(s));
  const err = deps.err ?? ((s) => process.stderr.write(s));
  const sleep = deps.sleep ?? ((ms) => new Promise((r) => setTimeout(r, ms)));
  const root = deps.root ?? process.cwd();
  let parsed;
  try {
    parsed = parseArgs({
      args: argv,
      allowPositionals: true,
      options: {
        'agent-id': { type: 'string' },
        profile: { type: 'string' },
        yes: { type: 'boolean', default: false },
        'dry-run': { type: 'boolean', default: false },
      },
    });
  } catch {
    err(USAGE);
    return 2;
  }
  const [brand, region] = parsed.positionals;
  const o = parsed.values;
  if (parsed.positionals.length !== 2 || !isValidBrandId(brand) || !isValidRegion(region) || (o['agent-id'] !== undefined && !isValidAgentId(o['agent-id']))) {
    err(USAGE);
    return 2;
  }
  const refuse = (m) => {
    err(`Refused: ${m}\nNothing was deleted.\n`);
    return 2;
  };
  const catalog = readCatalog(root);
  if (catalog.error) return refuse(`cannot read the brand catalog: ${catalog.error}.`);
  const block = catalog.brands[brand];
  if (!block) return refuse(`"${brand}" is not in content/brand.md. Valid ids: ${Object.keys(catalog.brands).join(', ')}.`);
  const brandName = String(block.brandName).trim();
  const stack = `${slugify(brandName)}-rcs-demo`;
  const file = readAgentFile(root);
  if (file.error) return refuse(`${file.error}; fix or delete it.`);
  const agentId = o['agent-id'] ?? lookupAgent(file.doc, brand, catalog.defaultBrand)?.rcsAgentId;
  if (!agentId) return refuse(`no agent is recorded for ${brand}; pass --agent-id.`);

  const aws = deps.aws ?? makeAws({ region, profile: o.profile });
  let regId;
  let devices = [];
  try {
    const r = await aws(['pinpoint-sms-voice-v2', 'describe-rcs-agents', '--rcs-agent-ids', agentId]);
    const agent = r?.RcsAgents?.[0];
    if (!agent) return refuse(`agent ${agentId} was not found in ${region}.`);
    regId = agent.TestingAgent?.RegistrationId;
    if (!regId) return refuse(`agent ${agentId} has no testing registration, so its brand cannot be confirmed.`);
    const v = await aws(['pinpoint-sms-voice-v2', 'describe-registration-field-values', '--registration-id', regId, '--field-paths', 'agentDetails.brandName']);
    const name = v?.RegistrationFieldValues?.find((f) => f.FieldPath === 'agentDetails.brandName')?.TextValue;
    if (name !== brandName) return refuse(`agent ${agentId} is registered as "${name ?? 'unknown'}", not "${brandName}".`);
    try {
      await aws(['cloudformation', 'describe-stacks', '--stack-name', stack]);
      return refuse(`the stack ${stack} still exists. Tear it down first: (cd cdk && npx cdk destroy -c brand=${brand}).`);
    } catch (e) {
      // "does not exist" arrives as a ValidationError; anything else means we cannot tell.
      if (!(e instanceof AwsError) || e.code !== 'ValidationError') return refuse(`cannot confirm that ${stack} is gone (${describeAwsError(e)}).`);
    }
    const d = await aws(['pinpoint-sms-voice-v2', 'describe-verified-destination-numbers', '--filters', `Name=rcs-agent-id,Values=${agentId}`]);
    devices = (d?.VerifiedDestinationNumbers ?? []).map((x) => x.VerifiedDestinationNumberId).filter(Boolean);
  } catch (e) {
    err(`Cannot read AWS state: ${describeAwsError(e)}\n`);
    return 1;
  }
  out(`Delete for ${brand} (${brandName}) in ${region}:\n  agent ${agentId}\n  registration ${regId}\n  ${devices.length} test device(s)\n`);
  if (o['dry-run']) {
    out('Dry run: every check passed. Nothing was deleted.\n');
    return 0;
  }
  if (!o.yes) {
    const tty = deps.isTTY ?? Boolean(process.stdin.isTTY && process.stdout.isTTY);
    if (!tty) return refuse('no terminal to confirm on; pass --yes to proceed.');
    const rl = createInterface({ input: process.stdin, output: process.stdout });
    let answer;
    try {
      answer = deps.confirm ? await deps.confirm(brand) : await rl.question(`Type the brand id (${brand}) to delete this agent: `);
    } finally {
      rl.close();
    }
    if (String(answer).trim() !== brand) return refuse('not confirmed.');
  }
  try {
    for (const id of devices) {
      out('- delete test device\n');
      await aws(['pinpoint-sms-voice-v2', 'delete-verified-destination-number', '--verified-destination-number-id', id]);
    }
    out('- deletion protection off\n');
    await aws(['pinpoint-sms-voice-v2', 'update-rcs-agent', '--rcs-agent-id', agentId, '--no-deletion-protection-enabled']);
    out('- delete registration\n');
    await aws(['pinpoint-sms-voice-v2', 'delete-registration', '--registration-id', regId]);
    out('- delete agent\n');
    for (let i = 0; ; i++) {
      try {
        await aws(['pinpoint-sms-voice-v2', 'delete-rcs-agent', '--rcs-agent-id', agentId]);
        break;
      } catch (e) {
        const notEmpty = e instanceof AwsError && (e.reason === 'RESOURCE_NOT_EMPTY' || e.code === 'ConflictException');
        if (!notEmpty || i + 1 >= RETRIES) throw e;
        await sleep(RETRY_MS);
      }
    }
  } catch (e) {
    err(`Stopped: ${describeAwsError(e)}. Run the same command again to continue.\n`);
    return 1;
  }
  try {
    saveAgentFile(root, withoutAgent(file.doc, brand, agentId));
  } catch {
    err('The agent is deleted, but .deploy/agent.json could not be updated; remove the stale entry by hand.\n');
    return 1;
  }
  out(`Deleted agent ${agentId}.\n`);
  return 0;
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
