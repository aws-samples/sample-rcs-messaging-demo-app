import { useEffect, useState } from 'react';
import TopNavigation from '@cloudscape-design/components/top-navigation';
import Tabs from '@cloudscape-design/components/tabs';
import Container from '@cloudscape-design/components/container';
import Form from '@cloudscape-design/components/form';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Button from '@cloudscape-design/components/button';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import { api, AgentIdentity, Brand, Tester, TypingRecipient } from './api';
import { getApiUrl, setApiUrl, normalizePhone } from './config';
import { applyBrandTheme } from './theme';
import StatusBar from './components/StatusBar';
import Demo from './views/Demo';
import Conversations from './views/Conversations';
import Guide from './views/Guide';
import Recipients from './views/Recipients';
import Settings from './views/Settings';

const PHONE_KEY = 'anyhealth_phone';
const DEFAULT_ACCENT = '#0B6E6F';
const MODE_POLL_MS = 5000;
// Typing is a live signal with a short shelf life (common.TYPING_STALE_SECONDS
// is 12), so it is polled faster than mode — but not so fast that an idle
// dashboard makes a request a second forever.
const TYPING_POLL_MS = 4000;

type Tab = 'instructions' | 'recipients' | 'conversations' | 'demo' | 'settings';

export default function App() {
  const [apiReady, setApiReady] = useState<boolean>(!!getApiUrl());
  const [brand, setBrand] = useState<Brand | null>(null);
  // The sending agent's registered identity, read live from AWS. Optional
  // everywhere: it needs the API key and the Describe*Registration*
  // permissions, so every consumer falls back to the brand.md values.
  const [identity, setIdentity] = useState<AgentIdentity | null>(null);
  // Normalize on load: older stored values (from before phone normalization
  // was added, or otherwise malformed) could be missing the leading "+",
  // which AWS's DescribeVerifiedDestinationNumbers 404s on — self-heal here
  // rather than leaving a stale bad value in place forever.
  const [phone, setPhone] = useState<string>(() => {
    const stored = localStorage.getItem(PHONE_KEY) || '';
    const normalized = normalizePhone(stored);
    if (normalized && normalized !== stored) localStorage.setItem(PHONE_KEY, normalized);
    return normalized || stored;
  });
  const [tab, setTab] = useState<Tab>('instructions');
  const [err, setErr] = useState<string>('');
  const [testers, setTesters] = useState<Tester[]>([]);
  const [testerReload, setTesterReload] = useState(0);
  // Conversation mode for the targeted device. Polled here rather than inside
  // StatusBar because it drives more than the bar: the app-wide handover banner
  // and the tab-label flag read it too. While a device is in live mode the bot
  // has stopped answering and every flow button the member taps is dropped
  // (channel_adapter.process_inbound), so it must be visible everywhere.
  const [mode, setMode] = useState<string>('');
  // Which recipients are composing a reply right now — app-wide rather than
  // per-target, since any registered recipient can start typing. Owned here for
  // the same reason as `mode`: one poll, and the status bar it feeds is now on
  // every tab.
  const [typing, setTyping] = useState<TypingRecipient[]>([]);

  useEffect(() => {
    // Apply the default theme immediately so the API-gate screen (before any
    // brand is loaded) and the first paint aren't stuck on Cloudscape's
    // stock blue.
    applyBrandTheme(DEFAULT_ACCENT);
  }, []);

  useEffect(() => {
    if (!apiReady) return;
    api.getBrand().then(setBrand).catch((e) => setErr(String(e)));
    // Deliberately silent on failure: a missing API key is the common case and
    // it only costs the previews their real logo, so it must not raise a
    // page-level error the way a failed brand load does.
    api.getAgentIdentity().then(setIdentity).catch(() => setIdentity(null));
  }, [apiReady]);

  useEffect(() => {
    applyBrandTheme(brand?.accentColor || DEFAULT_ACCENT);
  }, [brand?.accentColor]);

  useEffect(() => {
    if (!apiReady) return;
    api.getTesters().then(setTesters).catch(() => {});
  }, [apiReady, testerReload]);

  useEffect(() => {
    if (!phone) { setMode(''); return; }
    const load = () => api.getMode(phone).then((r) => setMode(r.mode)).catch(() => {});
    load();
    const id = setInterval(load, MODE_POLL_MS);
    return () => clearInterval(id);
  }, [phone]);

  // Silent on failure, unlike the brand load: without an API key this call 401s
  // on every tick, and a typing indicator is not worth a page-level error.
  useEffect(() => {
    if (!apiReady) return;
    const load = () => api.getTyping().then((r) => setTyping(r.typing)).catch(() => {});
    load();
    const id = setInterval(load, TYPING_POLL_MS);
    return () => clearInterval(id);
  }, [apiReady]);

  // The operator is usually looking at their phone, not the dashboard, when the
  // handover fires — so put it in the browser tab title too, which is the only
  // part of the app visible from another window.
  const brandName = brand?.brandName || 'AnyHealth';
  useEffect(() => {
    document.title = mode === 'live' ? `🔴 Live agent needed — ${brandName}` : `${brandName} RCS Demo`;
  }, [mode, brandName]);

  if (!apiReady) return <ApiGate onSet={() => setApiReady(!!getApiUrl())} />;

  const targetName = testers.find((t) => t.phone === phone)?.name || '';

  async function releaseToBot() {
    if (!phone) return;
    await api.setMode(phone, 'bot');
    setMode('bot');
  }

  const savePhone = (p: string) => {
    localStorage.setItem(PHONE_KEY, p);
    setPhone(p);
  };

  // Built once and included at the top of every tab's content. One element
  // rather than five call sites: the props are identical everywhere, and the
  // bar's own state (which recipient the picker has open, the last device-status
  // check) has no business differing by tab.
  const statusBar = (
    <StatusBar
      phone={phone}
      onChangePhone={savePhone}
      testers={testers}
      onReloadTesters={() => setTesterReload((n) => n + 1)}
      mode={mode}
      onSetMode={async (next) => { await api.setMode(phone, next); setMode(next); }}
      typing={typing}
      error={err}
      onDismissError={() => setErr('')}
    />
  );

  return (
    <div>
      <TopNavigation
        identity={{
          href: '#',
          title: brand?.brandName || 'AnyHealth',
        }}
        // Default visualContext ("top-navigation") forces a dark bar tinted
        // with the brand accent color, which combined with the rest of the
        // UI reads as too heavy. "none" keeps the top bar on the same light
        // background as the rest of the page.
        visualContext="none"
      />

      {/* Errors are no longer a full-width alert here: they live in the status
          bar, beside the device state that usually explains them. See
          StatusBar's ErrorIndicator. */}

      {mode === 'live' && (
        <HandoverBanner
          who={targetName || phone}
          onOpenConversations={() => setTab('conversations')}
          onRelease={releaseToBot}
        />
      )}

      {/* Wide enough for the Recipients table's eleven columns and the
          Conversations transcript without horizontal scrolling, but still
          capped: unbounded width on an ultrawide monitor stretches table rows
          so far that the Target button and the Received count are hard to
          associate. Prose-heavy views set their own narrower measure (Guide
          caps itself at 780). */}
      <div style={{ maxWidth: 1760, margin: '0 auto', padding: 22 }}>
        <Tabs
          activeTabId={tab}
          onChange={({ detail }) => setTab(detail.activeTabId as Tab)}
          tabs={[
            {
              id: 'instructions',
              label: 'Instructions',
              content: (
                <SpaceBetween size="m">
                  {statusBar}
                  <Guide brand={brand} phone={phone} />
                </SpaceBetween>
              ),
            },
            {
              id: 'demo',
              label: 'Interactive Demos',
              content: (
                <SpaceBetween size="m">
                  {statusBar}
                  <Demo phone={phone} brand={brand} identity={identity} onError={setErr} />
                </SpaceBetween>
              ),
            },
            {
              id: 'conversations',
              // Flagged in the tab label itself so a handover is visible while
              // the operator is on another tab, not only once they get here.
              label: mode === 'live' ? '2-way Conversations 🔴' : '2-way Conversations',
              content: (
                <SpaceBetween size="m">
                  {statusBar}
                  <Conversations onError={setErr} />
                </SpaceBetween>
              ),
            },
            {
              id: 'recipients',
              label: 'Recipients',
              content: (
                <SpaceBetween size="m">
                  {statusBar}
                  <Recipients
                    phone={phone}
                    onChangePhone={savePhone}
                    onError={setErr}
                    // Adding or removing a recipient here changes the target
                    // picker in the status bar, which reads this list.
                    onReloadTesters={() => setTesterReload((n) => n + 1)}
                    brand={brand}
                  />
                </SpaceBetween>
              ),
            },
            {
              id: 'settings',
              label: 'Settings',
              content: (
                <SpaceBetween size="m">
                  {statusBar}
                  <Settings brand={brand} identity={identity} phone={phone} onError={setErr} />
                </SpaceBetween>
              ),
            },
          ]}
        />
      </div>
    </div>
  );
}

// The "a human is needed" banner. Deliberately loud and full-bleed above the
// tab strip: the previous signal was a single word ("Live (human)") inside the
// target bar, which an operator running a live demo reliably missed — and while
// the conversation sits in live mode the member gets no reply at all, so a
// missed handover looks like a broken demo.
function HandoverBanner({
  who,
  onOpenConversations,
  onRelease,
}: {
  who: string;
  onOpenConversations: () => void;
  onRelease: () => Promise<void>;
}) {
  const [releasing, setReleasing] = useState(false);

  async function release() {
    setReleasing(true);
    try { await onRelease(); } finally { setReleasing(false); }
  }

  return (
    <div
      className="anyhealth-handover-banner"
      style={{
        background: '#8d6605',
        color: '#fff',
        padding: '12px 22px',
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'center',
        gap: 16,
      }}
    >
      {/* Scoped so the attention pulse doesn't need a global stylesheet (the
          app imports only Cloudscape's), and so it honours reduced-motion. */}
      <style>{`
        @keyframes anyhealth-handover-pulse { 0%,100% { opacity: 1 } 50% { opacity: .35 } }
        .anyhealth-handover-dot { animation: anyhealth-handover-pulse 1.4s ease-in-out infinite }
        @media (prefers-reduced-motion: reduce) { .anyhealth-handover-dot { animation: none } }
      `}</style>
      <span
        className="anyhealth-handover-dot"
        aria-hidden="true"
        style={{ width: 12, height: 12, borderRadius: 6, background: '#fff', flex: '0 0 auto' }}
      />
      <Box variant="span" fontSize="heading-s" fontWeight="bold">
        <span style={{ color: '#fff' }}>{who} asked to talk to a person</span>
      </Box>
      <Box variant="span" fontSize="body-s">
        <span style={{ color: '#fff', opacity: 0.9 }}>
          You're the care advocate now — the bot has stopped replying, and every card and
          button the member taps is ignored until you release the conversation.
        </span>
      </Box>
      <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, flex: '0 0 auto' }}>
        <Button onClick={onOpenConversations}>Open 2-way Conversations</Button>
        <Button loading={releasing} onClick={release}>Release to bot</Button>
      </div>
    </div>
  );
}

function ApiGate({ onSet }: { onSet: () => void }) {
  const [val, setVal] = useState('');

  function connect() {
    if (val.trim()) {
      setApiUrl(val.trim());
      onSet();
    }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center' }}>
      <div style={{ width: 460, maxWidth: '90vw' }}>
        <Container header={<Box variant="h2">Connect to your deployment</Box>}>
          <SpaceBetween size="m">
            <Box color="text-body-secondary" fontSize="body-s">
              Paste the <Box variant="code" display="inline">ApiUrl</Box> output from{' '}
              <Box variant="code" display="inline">cdk deploy</Box>. (You can also set{' '}
              <Box variant="code" display="inline">VITE_API_URL</Box> in{' '}
              <Box variant="code" display="inline">web/.env</Box> to skip this.) You'll also need the
              demo's API key (Settings tab, after connecting) — nearly every tab needs it, including
              Recipients and Conversations, not just sending. Retrieve it with{' '}
              <Box variant="code" display="inline">
                aws secretsmanager get-secret-value --secret-id &lt;prefix&gt;-demo-api-key --query
                SecretString --output text --region &lt;deploy region&gt;
              </Box>
              . The{' '}
              <Box variant="code" display="inline">--region</Box> matters: the secret lives in the
              region you deployed to, not your CLI default.
            </Box>
            <Form>
              <FormField label="API URL">
                <Input
                  value={val}
                  onChange={({ detail }) => setVal(detail.value)}
                  onKeyDown={({ detail }) => { if (detail.key === 'Enter') connect(); }}
                  placeholder="https://xxxx.execute-api.us-east-1.amazonaws.com"
                />
              </FormField>
            </Form>
            <Button variant="primary" onClick={connect}>Connect</Button>
          </SpaceBetween>
        </Container>
      </div>
    </div>
  );
}
