import { useEffect, useState } from 'react';
import Select from '@cloudscape-design/components/select';
import Button from '@cloudscape-design/components/button';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import Container from '@cloudscape-design/components/container';
import Icon from '@cloudscape-design/components/icon';
import Popover from '@cloudscape-design/components/popover';
import { api, Tester, Health, TypingRecipient } from '../api';

const HEALTH_POLL_MS = 30000;

// The demo's one persistent strip of state: which registered recipient is being
// demoed to, whether that device can receive, who is typing, the last error, who
// is answering the conversation, and which build is running. Rendered on every
// tab (App.tsx) rather than on two of them, because none of those facts stops
// being true when the operator switches tabs.
//
// Reading order is left to right by how often it changes and how much it
// matters: the device lamp and number first (checked before every send), then
// the live signals (typing, errors), then — pushed right, deliberately with the
// versions beyond it rather than at the edge — who is handling the conversation,
// then the build string, which changes least of all.
//
// Recipients are onboarded exclusively on the Recipients tab
// (create_verified_destination_number); this bar only picks among numbers that
// are already registered — no freeform phone entry here.
//
// `testers`, `mode`, `typing` and `error` are all owned by App: the mode poll
// drives the app-wide handover banner and the tab-label flag too, the typing
// poll is app-wide by nature, and errors are raised by views this bar never
// sees.
export default function StatusBar({
  phone,
  onChangePhone,
  testers,
  onReloadTesters,
  mode,
  onSetMode,
  typing,
  error,
  onDismissError,
}: {
  phone: string;
  onChangePhone: (phone: string) => void;
  testers: Tester[];
  onReloadTesters: () => void;
  mode: string;
  onSetMode: (mode: 'bot' | 'live') => Promise<void>;
  typing: TypingRecipient[];
  error: string;
  onDismissError: () => void;
}) {
  const [status, setStatus] = useState<string>('');
  const [picking, setPicking] = useState(false);
  const [checking, setChecking] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [changingMode, setChangingMode] = useState(false);

  useEffect(() => {
    if (!phone) { setStatus(''); return; }
    refreshStatus();
  }, [phone]);

  async function toggleMode() {
    if (!phone) return;
    setChangingMode(true);
    try { await onSetMode(mode === 'live' ? 'bot' : 'live'); }
    finally { setChangingMode(false); }
  }

  // Account-wide send health (e.g. the RCS monthly spend/quota limit) is
  // independent of which device is targeted, so this polls regardless of
  // whether a phone is selected — an operator should see it before they even
  // pick a recipient.
  useEffect(() => {
    const load = () => api.getHealth().then(setHealth).catch(() => {});
    load();
    const id = setInterval(load, HEALTH_POLL_MS);
    return () => clearInterval(id);
  }, []);

  async function refreshStatus() {
    setChecking(true);
    try { setStatus((await api.getTesterStatus(phone)).status); }
    catch { setStatus(''); }
    finally { setChecking(false); }
  }

  const current = testers.find((t) => t.phone === phone);
  const label = current?.name ? `${current.name} (${phone})` : phone;

  return (
    <Container disableContentPaddings>
      <Box padding={{ horizontal: 'l', vertical: 's' }}>
        {!picking && (
          // Flex rather than SpaceBetween because this row needs one thing
          // SpaceBetween cannot express: a gap that absorbs the leftover width,
          // so the mode control and the versions sit at the right end while
          // everything else stays packed on the left. Wraps on a narrow window
          // instead of scrolling.
          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 20 }}>
            {/* Status first, as a lamp: "can this device receive anything at
                all" is the question that explains a demo that does nothing, and
                it should be the first thing read, not a qualifier after the
                number. */}
            {phone && (
              <StatusIndicator type={statusType(status)}>
                {status || 'unknown'}
              </StatusIndicator>
            )}
            <Box>
              <Box variant="awsui-key-label" display="inline">Target:</Box>{' '}
              <Box fontWeight="bold" display="inline">{phone ? label : '(none selected)'}</Box>
            </Box>
            <SpaceBetween direction="horizontal" size="xs">
              <Button onClick={() => { onReloadTesters(); setPicking(true); }}>Change Target #</Button>
              {phone && (
                <Button
                  iconName="refresh"
                  variant="icon"
                  ariaLabel="Refresh device status"
                  loading={checking}
                  onClick={refreshStatus}
                />
              )}
            </SpaceBetween>
            <TypingIndicator typing={typing} testers={testers} />
            {error && <ErrorIndicator error={error} onDismiss={onDismissError} />}
            {health?.rcsQuotaAlert.active && <QuotaAlert health={health} />}
            {/* Everything from here is right-hand side. The mode control is
                pushed right but not flush to the edge: the version string is
                the last item, so mode ends up beside it rather than at the
                margin. */}
            <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 20 }}>
              {phone && mode && <ModeIndicator mode={mode} changing={changingMode} onToggle={toggleMode} />}
              <VersionIndicator />
            </div>
          </div>
        )}
        {picking && (
          <SpaceBetween direction="horizontal" size="s" alignItems="center">
            <Box variant="awsui-key-label">Target:</Box>
            <div style={{ minWidth: 280 }}>
              <Select
                selectedOption={
                  current ? { value: current.phone, label: current.name ? `${current.name} (${current.phone})` : current.phone } : null
                }
                onChange={({ detail }) => {
                  onChangePhone(detail.selectedOption.value || '');
                  setPicking(false);
                }}
                options={testers.map((t) => ({
                  value: t.phone,
                  label: t.name ? `${t.name} (${t.phone})` : t.phone,
                  description: t.status,
                }))}
                placeholder="Select a registered recipient"
                empty="No recipients registered yet — add one on the Recipients tab."
              />
            </div>
            <Button onClick={() => setPicking(false)}>Cancel</Button>
          </SpaceBetween>
        )}
      </Box>
    </Container>
  );
}

function statusType(status: string): 'success' | 'warning' | 'error' | 'info' {
  if (status === 'VERIFIED') return 'success';
  if (status === 'PENDING') return 'warning';
  if (status === 'NOT_FOUND' || status === 'UNKNOWN' || status === 'INVALID_PHONE' || status === 'ERROR') return 'error';
  return 'info';
}

// "Alex is typing…" — the signal a messaging app shows and a demo audience
// expects, sourced from the RCS_TYPING indicators the agent forwards
// (common.log_indicator → common.note_typing). Not scoped to the targeted
// device: any registered recipient composing a reply is worth knowing about,
// since the operator may be about to switch targets to them.
//
// No RCS_TYPING event was received during this sample's testing on a testing
// agent, so the indicator appears only when one arrives. It is wired end to
// end, so no code change is needed when typing events are delivered (the same
// applies to common.log_indicator).
function TypingIndicator({ typing, testers }: { typing: TypingRecipient[]; testers: Tester[] }) {
  if (!typing.length) return null;

  const nameFor = (hash: string) =>
    testers.find((t) => t.phone_hash === hash)?.name || 'A recipient';
  const names = typing.map((t) => nameFor(t.phone_hash));
  const who =
    names.length === 1 ? `${names[0]} is typing`
    : names.length === 2 ? `${names[0]} and ${names[1]} are typing`
    : `${names.length} recipients are typing`;

  return (
    <SpaceBetween direction="horizontal" size="xxs" alignItems="center">
      {/* Three drifting dots, the convention every messaging client uses, so it
          reads as activity rather than as another status word. Scoped <style>
          because the app imports no stylesheet of its own but Cloudscape's, and
          it honours reduced-motion. */}
      <style>{`
        @keyframes anyhealth-typing-dot { 0%,80%,100% { opacity: .25 } 40% { opacity: 1 } }
        .anyhealth-typing-dot { animation: anyhealth-typing-dot 1.2s ease-in-out infinite }
        @media (prefers-reduced-motion: reduce) { .anyhealth-typing-dot { animation: none } }
      `}</style>
      <Box color="text-status-info" fontSize="body-s">{who}</Box>
      <span aria-hidden="true" style={{ display: 'inline-flex', gap: 3, paddingBottom: 2 }}>
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="anyhealth-typing-dot"
            style={{
              width: 4,
              height: 4,
              borderRadius: 2,
              background: 'currentColor',
              color: '#0972d3',
              animationDelay: `${i * 0.18}s`,
            }}
          />
        ))}
      </span>
    </SpaceBetween>
  );
}

// The last error any view raised. It lives in the bar rather than in a
// full-width alert above the tabs because that alert pushed the whole page down
// and was routinely dismissed without being read; here it sits next to the
// device state that usually explains it. Full text is one click away —
// stringified fetch errors are far too long to inline.
function ErrorIndicator({ error, onDismiss }: { error: string; onDismiss: () => void }) {
  const short = error.length > 48 ? `${error.slice(0, 48)}…` : error;
  return (
    <SpaceBetween direction="horizontal" size="xs" alignItems="center">
      <Popover
        triggerType="text"
        size="medium"
        dismissAriaLabel="Close"
        header="Last error"
        content={<Box fontSize="body-s">{error}</Box>}
      >
        <SpaceBetween direction="horizontal" size="xxs" alignItems="center">
          <Icon name="status-negative" variant="error" />
          <Box color="text-status-error" fontSize="body-s">{short}</Box>
        </SpaceBetween>
      </Popover>
      <Button iconName="close" variant="icon" ariaLabel="Dismiss error" onClick={onDismiss} />
    </SpaceBetween>
  );
}

// Makes it unmistakable when the targeted device is in live-agent handover —
// every deterministic-flow button on the phone is silently dropped while in
// this mode (see channel_adapter.process_inbound), which is exactly the
// "nothing happens when I tap a button" confusion this surfaces up front.
// In bot mode this stays a quiet labeled pill matching the Select/In Use
// controls on the Recipients tab; in live mode it inverts to a filled warning
// badge, because a coloured word next to four other coloured words in the same
// bar was too easy to walk past. The app-wide banner in App.tsx is the primary
// signal — this is the in-place confirmation plus the release control.
function ModeIndicator({ mode, changing, onToggle }: { mode: string; changing: boolean; onToggle: () => void }) {
  const isLive = mode === 'live';
  return (
    <SpaceBetween direction="horizontal" size="xs" alignItems="center">
      {isLive ? (
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            height: 32,
            padding: '0 12px',
            borderRadius: 16,
            background: '#8d6605',
            color: '#fff',
            fontSize: 14,
            fontWeight: 700,
            whiteSpace: 'nowrap',
          }}
        >
          <Icon name="user-profile" variant="inverted" />
          Mode: LIVE — human handling
        </span>
      ) : (
        <Box>
          <Box variant="awsui-key-label" display="inline">Currently mode:</Box>{' '}
          <Box fontWeight="bold" display="inline">Bot</Box>
        </Box>
      )}
      <button
        type="button"
        disabled={changing}
        onClick={onToggle}
        aria-label={isLive ? 'Release this conversation back to the bot' : 'Take this conversation over as a live agent'}
        title={isLive ? 'Release to bot' : 'Take over as live agent'}
        style={{
          height: 32,
          minHeight: 32,
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          border: `2px solid ${isLive ? '#8d6605' : '#d5dbdb'}`,
          borderRadius: 16,
          background: '#fff',
          color: isLive ? '#8d6605' : '#5f6b7a',
          padding: '0 14px',
          fontSize: 14,
          fontWeight: 700,
          fontFamily: 'inherit',
          cursor: changing ? 'default' : 'pointer',
          opacity: changing ? 0.6 : 1,
          whiteSpace: 'nowrap',
        }}
      >
        {changing ? 'Updating…' : isLive ? 'Release to bot' : 'Take over'}
      </button>
    </SpaceBetween>
  );
}

// `fe:1.0.0.18 | be:1.0.0.22` — which build of each half is actually running.
// The frontend's is stamped in at build time; the backend's comes from the
// deployment the console is pointed at, which is the whole point: a stale build
// served from somewhere, or a deploy that never finished, shows up here instead
// of as mystifying behaviour. See scripts/version.mjs for the scheme (the fourth
// segment is a commit count, so it moves by itself).
function VersionIndicator() {
  const [backend, setBackend] = useState<string>('');
  const frontend = import.meta.env.VITE_FE_VERSION || 'unknown';

  useEffect(() => {
    api.getVersion().then((v) => setBackend(v.backend)).catch(() => setBackend('?'));
  }, []);

  // Only the hand-maintained part is compared. The commit counts are per-area
  // and count different paths, so they are never equal and a mismatch there
  // means nothing.
  const release = (v: string) => v.split('.').slice(0, 3).join('.');
  const drifted = !!backend && backend !== '?' && backend !== 'unknown'
    && release(frontend) !== release(backend);

  const content = (
    <SpaceBetween size="xs">
      <Box fontSize="body-s">
        The build running in this browser, and the build of the stack it is
        talking to. First three segments are maintained in{' '}
        <Box variant="code" display="inline">version.json</Box>; the fourth is
        the number of commits that have touched that half of the tree, so it
        advances on its own (<Box variant="code" display="inline">scripts/version.mjs</Box>).
      </Box>
      <Box fontSize="body-s" color="text-body-secondary">
        A <Box variant="code" display="inline">+dev</Box> suffix means that half
        had uncommitted changes when it was built;{' '}
        <Box variant="code" display="inline">+nogit</Box> means no git history was
        available to count. <Box variant="code" display="inline">be:?</Box> means
        the version call itself failed — the API URL is wrong, or the stack is
        not reachable.
      </Box>
      {drifted && (
        <Box fontSize="body-s" color="text-status-warning">
          These two releases differ. The frontend in this browser was built from
          a different version of the sample than the deployed backend — redeploy,
          or rebuild the console.
        </Box>
      )}
    </SpaceBetween>
  );

  return (
    <Popover triggerType="text" size="medium" dismissAriaLabel="Close" header="Demo version" content={content}>
      <Box
        fontSize="body-s"
        color={drifted ? 'text-status-warning' : 'text-body-secondary'}
      >
        <span style={{ fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>
          fe:{frontend} | be:{backend || '…'}
        </span>
      </Box>
    </Popover>
  );
}

// Account-wide alert: the RCS monthly spend/quota limit has rejected at
// least one send since it last cleared. This is unrelated to the targeted
// device's own status (which can show VERIFIED while every send still
// fails), so it's rendered as a separate item rather than folded into the
// device-status indicator above.
function QuotaAlert({ health }: { health: Health }) {
  const limit = health.rcsSpendLimit;
  const content = (
    <SpaceBetween size="xs">
      <Box>
        Every send to any device is currently being rejected by AWS End User
        Messaging with a monthly RCS spend/quota limit error. This is an
        account-level limit, not a problem with the targeted device.
      </Box>
      {limit && (
        <Box fontSize="body-s" color="text-body-secondary">
          Enforced limit: ${limit.enforcedLimit} (max: ${limit.maxLimit}
          {limit.overridden ? ', overridden' : ''})
        </Box>
      )}
      {health.rcsQuotaAlert.lastSeen && (
        <Box fontSize="body-s" color="text-body-secondary">
          Last seen: {new Date(health.rcsQuotaAlert.lastSeen).toLocaleString()}
        </Box>
      )}
      <Box fontSize="body-s" color="text-body-secondary">
        The override sets a cap at or below max. If max is $1, request an
        increase in Service Quotas (AWS End User Messaging SMS,
        RcsMessageMonthlySpend) or open an AWS Support case. After the
        increase, if the enforced limit is still lower than max, set it with
        set-rcs-message-spend-limit-override. If the limit is reached, sends
        resume when the monthly spend counter resets.
      </Box>
    </SpaceBetween>
  );
  return (
    <Popover triggerType="text" size="medium" dismissAriaLabel="Close" content={content}>
      <SpaceBetween direction="horizontal" size="xs" alignItems="center">
        <Icon name="status-warning" variant="warning" />
        <Box color="text-status-warning" fontSize="body-s">MONTHLY_SPEND_LIMIT_REACHED_FOR_RCS</Box>
      </SpaceBetween>
    </Popover>
  );
}
