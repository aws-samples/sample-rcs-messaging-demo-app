/**
 * Offline tests for create-agent.mjs, delete-agent.mjs, record-agent.mjs and
 * scripts/lib. Run: node --test scripts/test/
 * Needs the CDK dependencies for the yaml parser: (cd cdk && npm ci).
 */
import assert from 'node:assert/strict';
import { existsSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { after, describe, test } from 'node:test';
import { main as create } from '../create-agent.mjs';
import { main as del } from '../delete-agent.mjs';
import { main as record } from '../record-agent.mjs';
import { readCatalog, validateBlock } from '../lib/brand-catalog.mjs';
import { AwsError, classifyAwsError } from '../lib/rcs-agent.mjs';
import { REPO, agentId as hex, cleanupRoots, io, makeRoot, mutating } from './helpers.mjs';

after(cleanupRoots);

/** Stateful fake AWS for the agent scripts. */
function fakeAws({ quota = 5, agents = [], failOnce = {}, stackExists = false, statusSeq = ['None', 'PENDING', 'ACTIVE'], notEmptyTimes = 0 } = {}) {
  const s = { agents: agents.map((a) => ({ ...a })), regs: {}, calls: [], n: 100, status: [...statusSeq], notEmpty: notEmptyTimes };
  for (const a of s.agents) s.regs[a.reg] = { brandName: a.brandName };
  const aws = async (args) => {
    const op = ['sts', 'service-quotas', 'cloudformation'].includes(args[0]) ? `${args[0]}:${args[1]}` : args[1];
    s.calls.push([op, ...args.slice(2)]);
    if (failOnce[op]) {
      const e = failOnce[op];
      delete failOnce[op];
      throw e;
    }
    const arg = (f) => args[args.indexOf(f) + 1];
    switch (op) {
      case 'sts:get-caller-identity':
        return { Account: '111122223333' };
      case 'service-quotas:get-service-quota':
        return { Quota: { Value: quota } };
      case 'describe-spend-limits':
        return { SpendLimits: [{ Name: 'RCS_MESSAGE_MONTHLY_SPEND_LIMIT', MaxLimit: 1, EnforcedLimit: 1 }] };
      case 'describe-rcs-agents': {
        if (args.includes('--rcs-agent-ids')) {
          const a = s.agents.find((x) => x.id === arg('--rcs-agent-ids'));
          if (!a) return { RcsAgents: [] };
          const st = a.created ? (s.status.length > 1 ? s.status.shift() : s.status[0]) : 'ACTIVE';
          return { RcsAgents: [{ RcsAgentId: a.id, TestingAgent: { Status: st, RegistrationId: a.reg } }] };
        }
        return { RcsAgents: s.agents.map((a) => ({ RcsAgentId: a.id, TestingAgent: { RegistrationId: a.reg } })) };
      }
      case 'describe-registration-field-values':
        return { RegistrationFieldValues: [{ FieldPath: 'agentDetails.brandName', TextValue: s.regs[arg('--registration-id')]?.brandName }] };
      case 'create-rcs-agent': {
        const id = hex(++s.n);
        s.agents.push({ id, created: true });
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
        return { RegistrationAttachmentId: `attachment-${++s.n}` };
      case 'put-registration-field-value':
        if (arg('--field-path') === 'agentDetails.brandName') s.regs[arg('--registration-id')].brandName = arg('--text-value');
        return {};
      case 'update-rcs-agent':
      case 'submit-registration-version':
      case 'create-verified-destination-number':
      case 'delete-verified-destination-number':
      case 'delete-registration':
        return {};
      case 'cloudformation:describe-stacks':
        if (stackExists) return { Stacks: [{}] };
        throw new AwsError('ValidationError');
      case 'describe-verified-destination-numbers':
        return { VerifiedDestinationNumbers: [{ VerifiedDestinationNumberId: 'vdn-1' }] };
      case 'delete-rcs-agent':
        if (s.notEmpty-- > 0) throw new AwsError('ConflictException', 'RESOURCE_NOT_EMPTY');
        s.agents = s.agents.filter((a) => a.id !== arg('--rcs-agent-id'));
        return {};
      default:
        throw new Error(`unexpected op ${op}`);
    }
  };
  return { aws, s };
}

const readAgentJson = (root) => JSON.parse(readFileSync(join(root, '.deploy', 'agent.json'), 'utf8'));

describe('create-agent', () => {
  test('happy path with a phone: 21 fields, invite, recorded, legacy keys kept', async () => {
    const root = makeRoot({ rcsAgentId: hex(1), region: 'us-east-1' });
    const { aws, s } = fakeAws({ agents: [{ id: hex(1), reg: 'r1', brandName: 'AnyHealth' }] });
    const { o, deps } = io();
    assert.equal(await create(['anyhr', 'us-east-1', '--yes', '--phone', '+15555550100'], { ...deps, aws, root }), 0, o.err);
    const doc = readAgentJson(root);
    assert.equal(doc.rcsAgentId, hex(1));
    assert.equal(doc.agents.anyhr.rcsAgentId, hex(101));
    assert.equal(statSync(join(root, '.deploy', 'agent.json')).mode & 0o777, 0o600);
    assert.ok(!existsSync(join(root, '.deploy', 'agent-setup', 'anyhr.json')));
    assert.equal(s.calls.filter(([op]) => op === 'put-registration-field-value').length, 21);
    assert.ok(s.calls.some(([op]) => op === 'create-verified-destination-number'));
    assert.match(o.err, /spend limit is \$1/);
  });

  test('quota full: refused, nothing created', async () => {
    const root = makeRoot();
    const agents = [1, 2, 3, 4, 5].map((i) => ({ id: hex(i), reg: `r${i}`, brandName: `Other${i}` }));
    const { aws, s } = fakeAws({ agents, quota: 5 });
    const { o, deps } = io();
    assert.equal(await create(['anyhr', 'us-east-1', '--yes'], { ...deps, aws, root }), 2);
    assert.equal(mutating(s.calls).length, 0);
    assert.match(o.err, /quota is 5/);
  });

  test('an agent already registered as the brand is refused before the quota', async () => {
    const root = makeRoot();
    const agents = [1, 2, 3, 4].map((i) => ({ id: hex(i), reg: `r${i}`, brandName: `Other${i}` }));
    agents.push({ id: hex(7), reg: 'r7', brandName: 'AnyHR' });
    const { aws, s } = fakeAws({ agents, quota: 5 });
    const { o, deps } = io();
    assert.equal(await create(['anyhr', 'us-east-1', '--yes'], { ...deps, aws, root }), 2);
    assert.equal(mutating(s.calls).length, 0);
    assert.match(o.err, /already exists for AnyHR/);
  });

  test('a brand already recorded is refused', async () => {
    const root = makeRoot({ agents: { anyhr: { rcsAgentId: hex(9), region: 'us-east-1' } } });
    const { aws, s } = fakeAws();
    const { deps } = io();
    assert.equal(await create(['anyhr', 'us-east-1', '--yes'], { ...deps, aws, root }), 2);
    assert.equal(mutating(s.calls).length, 0);
  });

  test('RCS_AGENTS_PER_ACCOUNT on create-rcs-agent: exit 1, named, nothing half-built', async () => {
    const root = makeRoot();
    const { aws, s } = fakeAws({ failOnce: { 'create-rcs-agent': new AwsError('ServiceQuotaExceededException', 'RCS_AGENTS_PER_ACCOUNT') } });
    const { o, deps } = io();
    assert.equal(await create(['anyhr', 'us-east-1', '--yes'], { ...deps, aws, root }), 1);
    assert.match(o.err, /RCS agent quota/);
    assert.equal(mutating(s.calls).length, 1);
  });

  test('a run that stops part way resumes without a second agent', async () => {
    const root = makeRoot();
    const f = fakeAws({ failOnce: { 'submit-registration-version': new AwsError('ThrottlingException') } });
    assert.equal(await create(['anybuild', 'us-east-1', '--yes'], { ...io().deps, aws: f.aws, root }), 1);
    assert.ok(existsSync(join(root, '.deploy', 'agent-setup', 'anybuild.json')));
    const before = f.s.calls.length;
    const { o, deps } = io();
    assert.equal(await create(['anybuild', 'us-east-1', '--yes'], { ...deps, aws: f.aws, root }), 0, o.err);
    const second = f.s.calls.slice(before).map(([op]) => op);
    assert.ok(!second.includes('create-rcs-agent') && !second.includes('put-registration-field-value'));
    assert.equal(f.s.calls.filter(([op]) => op === 'create-rcs-agent').length, 1);
    assert.match(o.out, /Resuming/);
  });

  test('--dry-run creates and writes nothing', async () => {
    const root = makeRoot();
    const { aws, s } = fakeAws();
    const { o, deps } = io();
    assert.equal(await create(['anytravel', 'us-east-1', '--dry-run'], { ...deps, aws, root }), 0, o.err);
    assert.equal(mutating(s.calls).length, 0);
    assert.ok(!existsSync(join(root, '.deploy', 'agent.json')));
  });

  test('no terminal and no --yes: refused', async () => {
    const root = makeRoot();
    const { aws, s } = fakeAws();
    assert.equal(await create(['anytravel', 'us-east-1'], { ...io().deps, aws, root, isTTY: false }), 2);
    assert.equal(mutating(s.calls).length, 0);
  });

  test('a wrong typed confirmation: refused', async () => {
    const root = makeRoot();
    const { aws, s } = fakeAws();
    assert.equal(await create(['anytravel', 'us-east-1'], { ...io().deps, aws, root, isTTY: true, confirm: async () => 'nope' }), 2);
    assert.equal(mutating(s.calls).length, 0);
  });

  test('a rejected testing agent stops the poll with exit 1', async () => {
    const root = makeRoot();
    const { aws } = fakeAws({ statusSeq: ['PENDING', 'REJECTED'] });
    const { o, deps } = io();
    assert.equal(await create(['anytravel', 'us-east-1', '--yes'], { ...deps, aws, root }), 1);
    assert.match(o.err, /REJECTED/);
  });

  test('bad input exits 2', async () => {
    const { deps } = io();
    assert.equal(await create(['AnyHR', 'us-east-1'], deps), 2);
    assert.equal(await create(['anyhr', 'nowhere'], deps), 2);
    assert.equal(await create(['nosuch', 'us-east-1'], { ...deps, root: makeRoot() }), 2);
    assert.equal(await create(['anyhr', 'us-east-1', '--phone', '5551234'], deps), 2);
  });
});

describe('brand validation', () => {
  test('every shipped brand passes the registration limits', () => {
    const { brands } = readCatalog(REPO);
    for (const id of Object.keys(brands)) assert.deepEqual(validateBlock(id, brands[id], { root: REPO }).errors, [], id);
  });

  test('long description, low contrast and non-PNG media are caught', () => {
    const { brands } = readCatalog(REPO);
    const b = { ...brands.anyhr, agentDescription: 'x'.repeat(101), accentColor: '#FFEE00' };
    const { errors } = validateBlock('anyhr', b, { root: REPO });
    assert.ok(errors.some((e) => /agentDescription/.test(e)));
    assert.ok(errors.some((e) => /contrast/.test(e)));
    assert.ok(validateBlock('anyhr', brands.anyhr, { root: REPO, readFile: () => Buffer.alloc(10) }).warnings.some((w) => /not a PNG/.test(w)));
  });

  test('AWS CLI errors are reduced to a code and a reason', () => {
    assert.deepEqual(classifyAwsError('An error occurred (ServiceQuotaExceededException) when calling CreateRcsAgent: x, Reason="RCS_AGENTS_PER_ACCOUNT"'), {
      code: 'ServiceQuotaExceededException',
      reason: 'RCS_AGENTS_PER_ACCOUNT',
    });
    assert.equal(classifyAwsError('Unable to locate credentials.').code, 'ExpiredToken');
    assert.equal(classifyAwsError('aws: error: argument operation: Found invalid choice').code, 'AwsCliTooOld');
  });
});

describe('delete-agent', () => {
  test('deletes in order, retries RESOURCE_NOT_EMPTY, keeps the legacy keys', async () => {
    const root = makeRoot({ rcsAgentId: hex(1), region: 'us-east-1', agents: { anyhr: { rcsAgentId: hex(2), region: 'us-east-1' } } });
    const { aws, s } = fakeAws({ agents: [{ id: hex(2), reg: 'r2', brandName: 'AnyHR' }], notEmptyTimes: 2 });
    const { o, deps } = io();
    assert.equal(await del(['anyhr', 'us-east-1', '--yes'], { ...deps, aws, root }), 0, o.err);
    assert.deepEqual(
      mutating(s.calls).map(([op]) => op),
      ['delete-verified-destination-number', 'update-rcs-agent', 'delete-registration', 'delete-rcs-agent', 'delete-rcs-agent', 'delete-rcs-agent'],
    );
    const doc = readAgentJson(root);
    assert.equal(doc.agents.anyhr, undefined);
    assert.equal(doc.rcsAgentId, hex(1));
  });

  test('an agent registered as another brand is refused', async () => {
    const root = makeRoot();
    const { aws, s } = fakeAws({ agents: [{ id: hex(2), reg: 'r2', brandName: 'AnyHealth' }] });
    assert.equal(await del(['anyhr', 'us-east-1', '--agent-id', hex(2), '--yes'], { ...io().deps, aws, root }), 2);
    assert.equal(mutating(s.calls).length, 0);
  });

  test('a live stack is refused', async () => {
    const root = makeRoot();
    const { aws, s } = fakeAws({ agents: [{ id: hex(2), reg: 'r2', brandName: 'AnyHR' }], stackExists: true });
    const { o, deps } = io();
    assert.equal(await del(['anyhr', 'us-east-1', '--agent-id', hex(2), '--yes'], { ...deps, aws, root }), 2);
    assert.match(o.err, /anyhr-rcs-demo still exists/);
    assert.equal(mutating(s.calls).length, 0);
  });

  test('the legacy single-agent file resolves for the default brand', async () => {
    const root = makeRoot({ rcsAgentId: hex(1), region: 'us-east-1' });
    const { aws } = fakeAws({ agents: [{ id: hex(1), reg: 'r1', brandName: 'AnyHealth' }] });
    const { o, deps } = io();
    assert.equal(await del(['anyhealth', 'us-east-1', '--dry-run'], { ...deps, aws, root }), 0, o.err);
    assert.match(o.out, new RegExp(hex(1)));
  });
});

describe('record-agent', () => {
  test('checks the brand, needs --replace to overwrite, keeps the legacy keys', async () => {
    const root = makeRoot({ rcsAgentId: hex(1), region: 'us-east-1' });
    const { aws } = fakeAws({
      agents: [
        { id: hex(3), reg: 'r3', brandName: 'AnyTravel' },
        { id: hex(4), reg: 'r4', brandName: 'AnyTravel' },
        { id: hex(5), reg: 'r5', brandName: 'AnyHR' },
      ],
    });
    const { deps } = io();
    assert.equal(await record(['anytravel', hex(3), 'us-east-1'], { ...deps, aws, root }), 0);
    assert.equal(await record(['anytravel', hex(5), 'us-east-1'], { ...deps, aws, root }), 2);
    assert.equal(await record(['anytravel', hex(4), 'us-east-1'], { ...deps, aws, root }), 2);
    assert.equal(await record(['anytravel', hex(4), 'us-east-1', '--replace'], { ...deps, aws, root }), 0);
    assert.deepEqual(readAgentJson(root), { rcsAgentId: hex(1), region: 'us-east-1', agents: { anytravel: { rcsAgentId: hex(4), region: 'us-east-1' } } });
  });
});
