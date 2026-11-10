/**
 * Record an existing RCS agent for a brand in `.deploy/agent.json`.
 *
 *   node scripts/record-agent.mjs <Brand_Id> <AGENT_ID> <REGION> [--profile P] [--replace] [--no-verify]
 *
 * Writes `agents.<Brand_Id> = { rcsAgentId, region }` and keeps any other
 * entries and the legacy top-level `rcsAgentId` / `region` / `brand` keys.
 * Unless `--no-verify` is given it first checks in AWS that the agent exists
 * and that its registration's brand name is this brand's, so an agent cannot
 * be recorded under the wrong brand.
 *
 * Exit codes: 0 recorded; 1 AWS read or file write failed; 2 bad input or the
 * agent does not belong to the brand (file unchanged).
 */
import { parseArgs } from 'node:util';
import { pathToFileURL } from 'node:url';
import { isValidAgentId, isValidBrandId, isValidRegion, readCatalog } from './lib/brand-catalog.mjs';
import { describeAwsError, makeAws, readAgentFile, saveAgentFile, withAgent } from './lib/rcs-agent.mjs';

const USAGE = 'Usage: node scripts/record-agent.mjs <Brand_Id> <AGENT_ID> <REGION> [--profile P] [--replace] [--no-verify]\n';

export async function main(argv, deps = {}) {
  const out = deps.out ?? ((s) => process.stdout.write(s));
  const err = deps.err ?? ((s) => process.stderr.write(s));
  const root = deps.root ?? process.cwd();
  let parsed;
  try {
    parsed = parseArgs({
      args: argv,
      allowPositionals: true,
      options: { profile: { type: 'string' }, replace: { type: 'boolean', default: false }, 'no-verify': { type: 'boolean', default: false } },
    });
  } catch {
    err(USAGE);
    return 2;
  }
  const [brand, agentId, region] = parsed.positionals;
  if (parsed.positionals.length !== 3 || !isValidBrandId(brand) || !isValidAgentId(agentId) || !isValidRegion(region)) {
    err(USAGE);
    return 2;
  }
  const catalog = readCatalog(root);
  if (catalog.error) {
    err(`Cannot read the brand catalog: ${catalog.error}.\n`);
    return 2;
  }
  const block = catalog.brands[brand];
  if (!block) {
    err(`"${brand}" is not in content/brand.md. Valid ids: ${Object.keys(catalog.brands).join(', ')}.\n`);
    return 2;
  }
  if (!parsed.values['no-verify']) {
    const aws = deps.aws ?? makeAws({ region, profile: parsed.values.profile });
    try {
      const r = await aws(['pinpoint-sms-voice-v2', 'describe-rcs-agents', '--rcs-agent-ids', agentId]);
      const agent = r?.RcsAgents?.[0];
      if (!agent) {
        err(`Agent ${agentId} was not found in ${region}.\n`);
        return 2;
      }
      const regId = agent.TestingAgent?.RegistrationId;
      if (regId) {
        const v = await aws(['pinpoint-sms-voice-v2', 'describe-registration-field-values', '--registration-id', regId, '--field-paths', 'agentDetails.brandName']);
        const name = v?.RegistrationFieldValues?.find((f) => f.FieldPath === 'agentDetails.brandName')?.TextValue;
        if (name && name !== String(block.brandName).trim()) {
          err(`Agent ${agentId} is registered as "${name}", not "${String(block.brandName).trim()}". Not recorded.\n`);
          return 2;
        }
      }
    } catch (e) {
      err(`Cannot verify the agent: ${describeAwsError(e)}. Use --no-verify to record without checking.\n`);
      return 1;
    }
  }
  const file = readAgentFile(root);
  if (file.error) {
    err(`${file.error}; fix or delete it.\n`);
    return 1;
  }
  let next;
  try {
    next = withAgent(file.doc, brand, agentId, region, { replace: parsed.values.replace });
  } catch (e) {
    err(`${e instanceof Error ? e.message : 'cannot record'}\n`);
    return 2;
  }
  try {
    saveAgentFile(root, next);
  } catch {
    err('Could not write .deploy/agent.json.\n');
    return 1;
  }
  out(`Recorded ${agentId} for ${brand} in ${region}.\n`);
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
