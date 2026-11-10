import { useCallback, useEffect, useRef, useState } from 'react';
import TopNavigation from '@cloudscape-design/components/top-navigation';
import Container from '@cloudscape-design/components/container';
import Form from '@cloudscape-design/components/form';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Button from '@cloudscape-design/components/button';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import { probeBrand, type Brand } from './api';
import { setApiUrl } from './config';
import { accentFor, applyBrandTheme, DEFAULT_TITLE, documentTitle } from './theme';
import { registry, useRegistry } from './connections/registry';
import { brandLabel } from './connections/resolve';
import type { BrandConnection } from './connections/types';
import BrandSession, { type SwitchGuards, type Tab } from './session/BrandSession';
import BrandPicker, { type BrandLabels, type BrandPickerHandle } from './components/BrandPicker';
import Notices from './components/Notices';
import SwitchConfirmModal from './components/SwitchConfirmModal';

// How long the switch waits for the old video visit to end before it goes on.
const VIDEO_END_BUDGET_MS = 5000;

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

// A switch waiting for the operator's confirmation (R7.1, R7.4, R7.5).
interface PendingSwitch {
  target: string;
  guards: SwitchGuards;
}

// The shell: what survives a Brand_Switch. Connection discovery (the
// registry), the top navigation, the selected tab, the theme and the document
// title. Everything brand-scoped (state, polls, the status bar, every tab's
// content) lives in <BrandSession>, keyed by `activeId:generation`, so a switch
// or a URL save remounts it from first-load values.
export default function App() {
  const reg = useRegistry();
  // The Active_Brand's `GET /api/brand`, reported up by its session. Drives the
  // theme, the top-bar title and the document title.
  const [activeBrand, setActiveBrand] = useState<Brand | null>(null);
  // The session's conversation mode, for the document title's live prefix.
  const [mode, setMode] = useState<string>('');
  const [tab, setTab] = useState<Tab>('instructions');
  // The session's switch guards, read when a Brand_Switch is requested.
  const guardsRef = useRef<(() => SwitchGuards) | null>(null);

  // No API request precedes this: the session mounts only once it is `ready`.
  useEffect(() => {
    void registry.load();
  }, []);

  // Quietly look again when the tab regains focus: a brand wired or redeployed
  // in the meantime appears, and a brand that was briefly down comes back. It
  // only ever adds, and it never swaps out the brand in use (registry.recheck).
  useEffect(() => {
    const again = () => void registry.recheck();
    window.addEventListener('focus', again);
    return () => window.removeEventListener('focus', again);
  }, []);

  // The theme follows the Active_Brand. `activeBrand` is null before its load
  // resolves, after a failure and from the start of a switch, so the theme is
  // neutral in all three (R8.3, R8.4, R8.8). It also runs on mount, so the
  // API-gate screen and the first paint get the neutral accent instead of
  // Cloudscape's stock blue.
  const accent = accentFor(activeBrand);
  useEffect(() => {
    applyBrandTheme(accent);
  }, [accent]);

  // The name is whatever GET /api/brand returns for the Active_Brand; no brand
  // literal is baked into the UI, so until that load resolves the titles stay
  // neutral (R8.2, R8.3, R8.5, R8.6, R8.10).
  const brandName = activeBrand?.brandName || DEFAULT_TITLE;
  useEffect(() => {
    document.title = documentTitle(activeBrand?.brandName, mode === 'live');
  }, [mode, activeBrand?.brandName]);

  // Label cache for the picker: connection id -> loaded name / reachability.
  const [labels, setLabels] = useState<BrandLabels>({});
  // Connections already probed (or covered by the active session) in this page
  // load, so a probe is never repeated (R3.10).
  const probedRef = useRef<Set<string>>(new Set());
  // Connections whose own session reported a result; a later probe answer must
  // not overwrite it (R3.6).
  const sessionWrittenRef = useRef<Set<string>>(new Set());
  const pickerRef = useRef<BrandPickerHandle>(null);
  const [pending, setPending] = useState<PendingSwitch | null>(null);
  const [switching, setSwitching] = useState(false);

  // Only the Active_Brand's current session may write: a session that has been
  // switched away from can still deliver a late callback.
  const isActiveSession = (id: string) => registry.get().activeId === id;

  const onBrandLoaded = useCallback((b: Brand, connectionId: string) => {
    if (!isActiveSession(connectionId)) return;
    sessionWrittenRef.current.add(connectionId);
    setLabels((prev) => ({
      ...prev,
      [connectionId]: { name: b.brandName || prev[connectionId]?.name, unreachable: false },
    }));
    setActiveBrand(b);
  }, []);
  const onBrandFailed = useCallback((connectionId: string) => {
    if (!isActiveSession(connectionId)) return;
    sessionWrittenRef.current.add(connectionId);
    setLabels((prev) => ({ ...prev, [connectionId]: { ...prev[connectionId], unreachable: true } }));
    setActiveBrand(null);
  }, []);
  const registerGuards = useCallback((g: (() => SwitchGuards) | null) => {
    guardsRef.current = g;
  }, []);

  // On entering multi mode: one labelling request per non-active connection,
  // never repeated. The active connection's own session labels it.
  useEffect(() => {
    if (reg.status !== 'ready' || reg.mode !== 'multi') return;
    if (reg.activeId) probedRef.current.add(reg.activeId);
    for (const c of reg.connections) {
      if (probedRef.current.has(c.id)) continue;
      probedRef.current.add(c.id);
      probeBrand(c)
        .then((b) => {
          if (sessionWrittenRef.current.has(c.id)) return;
          setLabels((prev) => ({
            ...prev,
            [c.id]: { name: b.brandName || undefined, unreachable: false },
          }));
        })
        .catch(() => {
          if (sessionWrittenRef.current.has(c.id)) return;
          setLabels((prev) => ({ ...prev, [c.id]: { ...prev[c.id], unreachable: true } }));
        });
    }
  }, [reg.status, reg.mode, reg.activeId, reg.connections]);

  // Start the Brand_Switch: new Active_Brand and generation, neutral brand
  // state, tab kept, no change to any recipient's conversation mode.
  const beginSwitch = useCallback((target: string) => {
    registry.setActive(target);
    setActiveBrand(null);
  }, []);

  const requestSwitch = useCallback(
    (target: string) => {
      if (switching || target === registry.get().activeId) return;
      const g = guardsRef.current?.() ?? { video: null, live: null };
      if (g.video || g.live) {
        setPending({ target, guards: g });
        return;
      }
      beginSwitch(target);
    },
    [switching, beginSwitch],
  );

  const confirmSwitch = useCallback(async () => {
    if (!pending || switching) return;
    const { target, guards } = pending;
    const video = guards.video;
    if (video) {
      setSwitching(true);
      try {
        await Promise.race([video.client.videoEnd(video.token), sleep(VIDEO_END_BUDGET_MS)]);
      } catch {
        /* the switch goes on whatever the end call said */
      }
      setSwitching(false);
    }
    setPending(null);
    beginSwitch(target);
  }, [pending, switching, beginSwitch]);

  const cancelSwitch = useCallback(() => {
    setPending(null);
    // Let the dialog's focus trap release first, then return focus (R7.6).
    setTimeout(() => pickerRef.current?.focus(), 0);
  }, []);

  if (reg.status !== 'ready') return null;
  if (reg.mode === 'none') return reg.noneUsable ? <NoneAnswering /> : <ApiGate />;

  const active = reg.connections.find((c) => c.id === reg.activeId);
  if (!active) return null;

  const labelFor = (c: BrandConnection | undefined) => {
    if (!c) return '';
    const entry = labels[c.id];
    return brandLabel(c, entry?.unreachable ? undefined : entry);
  };
  const pendingTarget = pending ? reg.connections.find((c) => c.id === pending.target) : undefined;

  return (
    <div>
      <TopNavigation
        identity={{
          href: '#',
          // The Active_Brand's name from GET /api/brand — never a brand
          // literal; neutral until the brand load resolves.
          title: brandName,
        }}
        // Default visualContext ("top-navigation") forces a dark bar tinted
        // with the brand accent color, which combined with the rest of the
        // UI reads as too heavy. "none" keeps the top bar on the same light
        // background as the rest of the page.
        visualContext="none"
        // The picker appears only with two or more connections; in single mode
        // the prop is omitted so the top bar is unchanged.
        {...(reg.mode === 'multi'
          ? {
              search: (
                <div style={{ minWidth: 240 }}>
                  <BrandPicker
                    ref={pickerRef}
                    connections={reg.connections}
                    activeId={active.id}
                    labels={labels}
                    requestSwitch={requestSwitch}
                  />
                </div>
              ),
            }
          : {})}
      />

      <Notices />

      <SwitchConfirmModal
        guards={pending?.guards ?? null}
        fromLabel={labelFor(active)}
        toLabel={labelFor(pendingTarget)}
        busy={switching}
        onConfirm={() => void confirmSwitch()}
        onCancel={cancelSwitch}
      />

      <BrandSession
        key={`${reg.activeId}:${reg.generation}`}
        connection={active}
        generation={reg.generation}
        multi={reg.mode === 'multi'}
        tab={tab}
        setTab={setTab}
        onBrandLoaded={onBrandLoaded}
        onBrandFailed={onBrandFailed}
        registerGuards={registerGuards}
        onModeChange={setMode}
      />
    </div>
  );
}

function ApiGate() {
  const [val, setVal] = useState('');

  // Saves the URL where it is saved today, then re-resolves the connections:
  // the dashboard appears without a page reload.
  function connect() {
    if (val.trim()) {
      setApiUrl(val.trim());
      void registry.reload();
    }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center' }}>
      <div style={{ width: 460, maxWidth: '90vw' }}>
        <Container header={<Box variant="h2">Connect to your deployment</Box>}>
          <SpaceBetween size="m">
            <Box color="text-body-secondary" fontSize="body-s">
              After <Box variant="code" display="inline">cdk deploy</Box>, connect the brand you
              deployed from the repository root, then reload this page:{' '}
              <Box variant="code" display="inline">
                node scripts/wire-dashboard-brand.mjs &lt;brand&gt; &lt;region&gt;
              </Box>
              . It reads the API URL and key for you, and only brands that are deployed appear
              here.
            </Box>
            <Box color="text-body-secondary" fontSize="body-s">
              Or connect a single deployment by hand. Paste the{' '}
              <Box variant="code" display="inline">ApiUrl</Box> output from{' '}
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

// Shown when brands are wired but none could be used (none answered), as
// opposed to nothing being wired at all. Names no brand: it says nothing about
// which brands exist, only that none could be reached. Retry checks again now.
function NoneAnswering() {
  const [busy, setBusy] = useState(false);

  async function retry() {
    setBusy(true);
    try {
      await registry.recheck({ force: true });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center' }}>
      <div style={{ width: 460, maxWidth: '90vw' }}>
        <Container header={<Box variant="h2">Couldn't reach a deployed brand</Box>}>
          <SpaceBetween size="m">
            <Box color="text-body-secondary" fontSize="body-s">
              Nothing connected to this dashboard answered. Check that you're online and that your
              stack is deployed, then try again. To connect a brand, run{' '}
              <Box variant="code" display="inline">
                node scripts/wire-dashboard-brand.mjs &lt;brand&gt; &lt;region&gt;
              </Box>{' '}
              and reload.
            </Box>
            <Button variant="primary" loading={busy} onClick={() => void retry()}>
              Retry
            </Button>
          </SpaceBetween>
        </Container>
      </div>
    </div>
  );
}
