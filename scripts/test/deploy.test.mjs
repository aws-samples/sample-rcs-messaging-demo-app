/**
 * Offline tests for scripts/deploy.mjs. Run: node --test scripts/test/
 * AWS calls and child processes (aws, cdk, the wiring script) are faked.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { after, describe, test } from 'node:test';
import { failureLines, main, parseBrandList, summarizeDiff } from '../deploy.mjs';
import { readCatalog } from '../lib/brand-catalog.mjs';
import { AwsError } from '../lib/rcs-agent.mjs';
import { REPO, agentId as hex, cleanupRoots, io, makeRoot } from './helpers.mjs';

after(cleanupRoots);

const PHONE = '+15555550100';

function fakeAws({ quota = 5, agents = [], stacks = {}, bootstrapped = true, devices = [] } = {}) {
  const s = { agents: agents.map((a) => ({ ...a })), regs: {}, calls: [], n: 100, stacks: { ...stacks }, devices: [...devices] };
  for (const a of s.agents) s.regs[a.reg] = { brandName: a.brandName };
  const aws = async (args) => {
    const op = ['sts', 'service-quotas', 'cloudformation', 'ssm'].includes(args[0]) ? `${args[0]}:${args[1]}` : args[1];
    s.calls.push([op, ...args.slice(2)]);
    const arg = (f) => args[args.indexOf(f) + 1];
    switch (op) {
      case 'sts:get-caller-identity':
        return { Account: '111122223333' };
      case 'service-quotas:get-service-quota':
        return { Quota: { Value: quota } };
      case 'ssm:get-parameter':
        if (bootstrapped) return { Parameter: { Value: '30' } };
        throw new AwsError('ParameterNotFound');
      case 'describe-spend-limits':
        return { SpendLimits: [{ Name: 'RCS_MESSAGE_MONTHLY_SPEND_LIMIT', MaxLimit: 100, EnforcedLimit: 100 }] };
      case 'describe-rcs-agents': {
        const list = args.includes('--rcs-agent-ids') ? s.agents.filter((x) => x.id === arg('--rcs-agent-ids')) : s.agents;
        return { RcsAgents: list.map((a) => ({ RcsAgentId: a.id, TestingAgent: { Status: 'ACTIVE', RegistrationId: a.reg } })) };
      }
      case 'describe-registration-field-values':
        return { RegistrationFieldValues: [{ FieldPath: 'agentDetails.brandName', TextValue: s.regs[arg('--registration-id')]?.brandName }] };
      case 'create-rcs-agent': {
        const id = hex(++s.n);
        s.agents.push({ id });
        return { RcsAgentId: id };
      }
      case 'create-registration': {
        const id = `registration-${++s.n}`;
        s.regs[id] = {};
        return { RegistrationId: id };
      }
      case 'create-registration-association':
        s.agents.find((a) => a.id === arg('--resource-id')).reg = arg('--registration-id');
        return {};
      case 'create-registration-attachment':
        return { RegistrationAttachmentId: `att-${++s.n}` };
      case 'put-registration-field-value':
        if (arg('--field-path') === 'agentDetails.brandName') s.regs[arg('--registration-id')].brandName = arg('--text-value');
        return {};
      case 'update-rcs-agent':
      case 'submit-registration-version':
        return {};
      case 'cloudformation:describe-stacks': {
        const st = s.stacks[arg('--stack-name')];
        if (!st) throw new AwsError('ValidationError');
        return { Stacks: [{ StackStatus: st, Outputs: [{ OutputKey: 'KeywordsStatus', OutputValue: 'ok (HELP written)' }] }] };
      }
      case 'describe-verified-destination-numbers': {
        const d = s.devices.filter((x) => x.phone === arg('--destination-phone-numbers'));
        if (!d.length) throw new AwsError('ResourceNotFoundException');
        return { VerifiedDestinationNumbers: d.map((x) => ({ RcsAgentId: x.agent, Status: x.status })) };
      }
      case 'create-verified-destination-number':
        s.devices.push({ phone: arg('--destination-phone-number'), agent: arg('--rcs-agent-id'), status: 'PENDING' });
        return {};
      default:
        throw new Error(`unexpected aws op ${op}`);
    }
  };
  return { aws, s };
}

const DIFF_NEW =
  'Stack x\nIAM Statement Changes\n│ + │ ${A.Arn} │ Allow │ sns:Publish │\n│ + │ ${B.Arn} │ Allow │ s3:PutObject │\n' +
  'Resources\n[+] AWS::Lambda::Function A\n[+] AWS::SNS::Topic B\n✨  Number of stacks with differences: 1\n';

/** Fake child processes. `failDeploy` brands end in ROLLBACK_COMPLETE. */
function fakeRun({ s, failDeploy = [], noRcsCli = false } = {}) {
  const calls = [];
  const run = async (cmd, args) => {
    calls.push([cmd, ...args]);
    if (cmd === 'aws') return noRcsCli ? { code: 252, out: 'Found invalid choice' } : { code: 0, out: '{}' };
    if (cmd === 'python3') return { code: 0, out: 'pip 23.0 from x (python 3.11)' };
    if (cmd === 'node' && args[0] === '-e') return { code: 0, out: '' };
    if (cmd === 'node') return { code: 0, out: 'Wired.' };
    if (cmd === 'npx' && args[1] === 'diff') return { code: 0, out: DIFF_NEW };
    if (cmd === 'npx' && args[1] === 'bootstrap') return { code: 0, out: '' };
    if (cmd === 'npx' && args[1] === 'deploy') {
      const b = args[args.indexOf('-c') + 1].split('=')[1];
      if (failDeploy.includes(b)) {
        s.stacks[`${b}-rcs-demo`] = 'ROLLBACK_COMPLETE';
        return {
          code: 1,
          out: `${b}-rcs-demo | 3/40 | CREATE_FAILED | AWS::IAM::Role | TwoWayRole Resource handler returned message: "Role ${b}-demo-twoway-us-east-1 already exists"\n❌ ${b}-rcs-demo failed: Error: The stack failed\n`,
        };
      }
      s.stacks[`${b}-rcs-demo`] = 'CREATE_COMPLETE';
      return { code: 0, out: 'done' };
    }
    throw new Error(`unexpected run ${cmd} ${args.join(' ')}`);
  };
  return { run, calls };
}

const mutatingAws = (s) => s.calls.filter(([op]) => /^(create|put|update|submit|delete)/.test(op));

describe('helpers', () => {
  test('parseBrandList accepts all, numbers and ids, and rejects unknown ids', () => {
    const v = ['anyhealth', 'anytravel', 'anybuild'];
    assert.deepEqual(parseBrandList('all', v).ids, v);
    assert.deepEqual(parseBrandList('1, 3', v).ids, ['anyhealth', 'anybuild']);
    assert.deepEqual(parseBrandList('anytravel anytravel', v).ids, ['anytravel']);
    assert.match(parseBrandList('nope', v).error, /not a brand/);
    assert.match(parseBrandList('', v).error, /no brands/);
  });

  test('summarizeDiff and failureLines', () => {
    assert.deepEqual(summarizeDiff(DIFF_NEW), { added: 2, changed: 0, removed: 0, iam: 2, replaced: 0, noChanges: false });
    assert.equal(failureLines('x\nabc | CREATE_FAILED | Role exists\nResource creation cancelled CREATE_FAILED\n').length, 1);
  });
});

describe('pre-flight and plan', () => {
  test('--plan-only --brands all on a fresh account: a new agent and stack per brand, nothing changed', async () => {
    const root = makeRoot();
    const brandCount = Object.keys(readCatalog(REPO).brands).length;
    // Enough agent slots for every brand in the catalog, however many there are.
    const { aws, s } = fakeAws({ quota: brandCount });
    const { run, calls } = fakeRun({ s });
    const { o, deps } = io();
    assert.equal(await main(['--brands', 'all', '--region', 'us-east-1', '--phone', PHONE, '--plan-only'], { ...deps, root, aws, run }), 0, o.out + o.err);
    assert.equal(calls.filter((c) => c[2] === 'diff').length, brandCount);
    assert.match(o.out, /anybuild\s+agent: CREATE/);
    assert.match(o.out, /2 to add, 0 to change, 0 to remove, 2 IAM statement change/);
    assert.match(o.out, /send a tester invitation/);
    assert.match(o.out, /Bedrock access was not checked/);
    assert.equal(mutatingAws(s).length, 0);
  });

  test('every blocker is listed, and no diff runs while one exists', async () => {
    const root = makeRoot();
    const agents = [1, 2, 3, 4].map((i) => ({ id: hex(i), reg: `r${i}`, brandName: `Other${i}` }));
    const { aws, s } = fakeAws({ agents, quota: 5 });
    const { run, calls } = fakeRun({ s, noRcsCli: true });
    const { o, deps } = io();
    assert.equal(await main(['--brands', 'anyhealth,anytravel', '--region', 'us-east-1'], { ...deps, root, aws, run }), 2);
    assert.match(o.out, /2 new RCS agent\(s\) are needed but only 1 of 5 slots are free/);
    assert.match(o.out, /no RCS commands/);
    assert.equal(calls.filter((c) => c[2] === 'diff').length, 0);
  });

  test('a stack in ROLLBACK_COMPLETE blocks, with the command that clears it', async () => {
    const root = makeRoot();
    const { aws, s } = fakeAws({ stacks: { 'anyhr-rcs-demo': 'ROLLBACK_COMPLETE' } });
    const { run } = fakeRun({ s });
    const { o, deps } = io();
    assert.equal(await main(['--brands', 'anyhr', '--region', 'us-east-1', '--yes'], { ...deps, root, aws, run }), 2);
    assert.match(o.out, /cannot be updated\n\s+fix: Delete it: aws cloudformation delete-stack/);
    assert.match(o.out, /stack: blocked \(ROLLBACK_COMPLETE\)/);
  });

  test('no terminal and no --yes: stops after the plan', async () => {
    const root = makeRoot();
    const { aws, s } = fakeAws();
    const { run, calls } = fakeRun({ s });
    const { o, deps } = io();
    assert.equal(await main(['--brands', 'anyhr', '--region', 'us-east-1'], { ...deps, root, aws, run }), 2);
    assert.match(o.err, /--yes/);
    assert.ok(!calls.some((c) => c[2] === 'deploy'));
  });

  test('the terminal picker selects by number, and a wrong confirmation changes nothing', async () => {
    const root = makeRoot();
    const { aws, s } = fakeAws();
    const { run, calls } = fakeRun({ s });
    const { o, deps } = io();
    const answers = ['2', 'nope'];
    assert.equal(await main(['--region', 'us-east-1'], { ...deps, isTTY: true, ask: async () => answers.shift(), root, aws, run }), 2);
    assert.match(o.out, /anytravel\s+agent: CREATE/);
    assert.match(o.out, /Not confirmed/);
    assert.ok(!calls.some((c) => c[2] === 'deploy'));
  });

  test('bad input exits 2', async () => {
    const { deps } = io();
    assert.equal(await main(['--brands', 'all'], deps), 2);
    assert.equal(await main(['--brands', 'nope', '--region', 'us-east-1'], { ...deps, root: makeRoot() }), 2);
    assert.equal(await main(['--region', 'us-east-1', '--context', 'brand=x', '--brands', 'all'], deps), 2);
    assert.equal(await main(['--region', 'us-east-1', '--brands', 'all', '--phone', '123'], deps), 2);
  });
});

describe('deploy', () => {
  test('create, reuse, record and a failed brand that the run carries on past', async () => {
    const root = makeRoot({ agents: { anyhealth: { rcsAgentId: hex(1), region: 'us-east-1' } } });
    const { aws, s } = fakeAws({
      agents: [
        { id: hex(1), reg: 'r1', brandName: 'AnyHealth' },
        { id: hex(2), reg: 'r2', brandName: 'AnyTravel' },
      ],
      stacks: { 'anyhealth-rcs-demo': 'UPDATE_COMPLETE' },
      devices: [{ phone: PHONE, agent: hex(1), status: 'VERIFIED' }],
      bootstrapped: false,
    });
    const { run, calls } = fakeRun({ s, failDeploy: ['anyhr'] });
    const { o, deps } = io();
    const code = await main(['--brands', 'anyhealth,anytravel,anyhr,anybuild', '--region', 'us-east-1', '--phone', PHONE, '--yes'], {
      ...deps,
      root,
      aws,
      run,
      now: () => 0,
    });
    assert.equal(code, 1, o.out);
    // The plan
    assert.match(o.out, /anyhealth\s+agent: reuse/);
    assert.match(o.out, /anytravel\s+agent: reuse .*not yet recorded/);
    assert.match(o.out, /already a tester \(VERIFIED\)/);
    assert.match(o.out, /cdk bootstrap/);
    // Bootstrap once, then the brands in order, one after another
    assert.equal(calls.filter((c) => c[0] === 'npx' && c[2] === 'bootstrap').length, 1);
    assert.deepEqual(
      calls.filter((c) => c[2] === 'deploy').map((c) => c[4]),
      ['brand=anyhealth', 'brand=anytravel', 'brand=anyhr', 'brand=anybuild'],
    );
    // Results
    const doc = JSON.parse(readFileSync(join(root, '.deploy', 'agent.json'), 'utf8'));
    assert.deepEqual(Object.keys(doc.agents).sort(), ['anybuild', 'anyhealth', 'anyhr', 'anytravel']);
    assert.match(o.out, /anyhealth\s+OK\s+keywords: ok/);
    assert.match(o.out, /anybuild\s+OK.*tester: sent/);
    // The failed brand has enough detail to recover
    assert.match(o.out, /anyhr\s+FAILED\s+at: cdk deploy/);
    assert.match(o.out, /why: .*CREATE_FAILED .*already exists/);
    assert.match(o.out, /exists now: agent rcs-\S+; stack anyhr-rcs-demo \(ROLLBACK_COMPLETE\)/);
    assert.match(o.out, /to resume: aws cloudformation delete-stack --stack-name anyhr-rcs-demo .* node scripts\/deploy.mjs --brands anyhr/);
    assert.equal(s.devices.filter((d) => d.status === 'PENDING').length, 2); // anytravel and anybuild
    assert.equal(calls.filter((c) => c[0] === 'node' && c[1] === 'scripts/wire-dashboard-brand.mjs').length, 3);
  });

  test('an agent recorded in another Region blocks, even though it is not listed here', async () => {
    const root = makeRoot({ agents: { anyhr: { rcsAgentId: hex(5), region: 'eu-west-1' } } });
    const { aws, s } = fakeAws();
    const { run, calls } = fakeRun({ s });
    const { o, deps } = io();
    assert.equal(await main(['--brands', 'anyhr', '--region', 'us-east-1', '--yes'], { ...deps, root, aws, run }), 2);
    assert.match(o.out, /recorded agent is in eu-west-1, not us-east-1/);
    assert.ok(!calls.some((c) => c[2] === 'deploy'));
    assert.equal(mutatingAws(s).length, 0);
  });

  test('a recorded agent that no longer exists is replaced by the new one', async () => {
    const root = makeRoot({ agents: { anyhr: { rcsAgentId: hex(9), region: 'us-east-1' } } });
    const { aws, s } = fakeAws();
    const { run } = fakeRun({ s });
    const { o, deps } = io();
    assert.equal(await main(['--brands', 'anyhr', '--region', 'us-east-1', '--yes'], { ...deps, root, aws, run, now: () => 0 }), 0, o.out);
    assert.match(o.out, /recorded agent no longer exists/);
    const doc = JSON.parse(readFileSync(join(root, '.deploy', 'agent.json'), 'utf8'));
    assert.notEqual(doc.agents.anyhr.rcsAgentId, hex(9));
  });

  test('the resume command repeats --context options', async () => {
    const root = makeRoot();
    const { aws, s } = fakeAws();
    const { run } = fakeRun({ s, failDeploy: ['anyhr'] });
    const { o, deps } = io();
    const args = ['--brands', 'anyhr', '--region', 'us-east-1', '--context', 'bedrockModelId=us.x.y', '--yes'];
    assert.equal(await main(args, { ...deps, root, aws, run, now: () => 0 }), 1);
    assert.match(o.out, /to resume: .*node scripts\/deploy.mjs --brands anyhr --region us-east-1 --context bedrockModelId=us\.x\.y/);
  });

  test('a rerun deploys an already-recorded brand without a new agent', async () => {
    const root = makeRoot({ agents: { anyhr: { rcsAgentId: hex(5), region: 'us-east-1' } } });
    const { aws, s } = fakeAws({ agents: [{ id: hex(5), reg: 'r5', brandName: 'AnyHR' }] });
    const { run } = fakeRun({ s });
    const { o, deps } = io();
    assert.equal(await main(['--brands', 'anyhr', '--region', 'us-east-1', '--yes'], { ...deps, root, aws, run }), 0, o.out);
    assert.ok(!s.calls.some(([op]) => op === 'create-rcs-agent'));
  });
});
