// BrandSession: everything brand-scoped that the dashboard holds for the
// Active_Brand, below the top navigation.
//
// The shell renders it as `<BrandSession key={`${activeId}:${generation}`}>`,
// so a Brand_Switch or a URL save that changes the active URL unmounts the
// whole subtree: every `useState` starts again from its first-load value, every
// poll's cleanup clears its interval and every modal closes. Responses aimed at
// the old session come from a client whose binding is no longer current, so
// they never settle (api.ts `bound`).
//
// What survives a switch stays in the shell (App.tsx): the selected tab, the
// notices, the theme and the document title. The session reports the loaded
// brand (`onBrandLoaded` / `onBrandFailed`) and its conversation mode
// (`onModeChange`) up for those, and registers the switch guards
// (`registerGuards`) the shell reads before a switch.
//
// In single mode (one Available_Connection) the session is today's App body:
// `ready` is true from mount, `track` is a pass-through, `prefix` is a no-op,
// and the tab content renders with no wrapper.
import { useCallback, useEffect, useMemo, useRef, useState, type MutableRefObject, type ReactNode } from 'react';
import Tabs from '@cloudscape-design/components/tabs';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Spinner from '@cloudscape-design/components/spinner';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import { createApiClient, AgentIdentity, ApiClient, Brand, Tester, TypingRecipient } from '../api';
import { normalizePhone } from '../config';
import { aAgentRole } from '../agentRole';
import { registry } from '../connections/registry';
import { brandLabel, normalizeUrl, scrubKeys } from '../connections/resolve';
import type { BrandConnection } from '../connections/types';
import StatusBar from '../components/StatusBar';
import Demo from '../views/Demo';
import Conversations from '../views/Conversations';
import Guide from '../views/Guide';
import Recipients from '../views/Recipients';
import Settings from '../views/Settings';
import {
  SessionProvider,
  isTrackedLoadError,
  useSession,
  type ReportedVideo,
} from './SessionContext';
import { usePoll } from './usePoll';
import { useInert } from './useInert';

const MODE_POLL_MS = 5000;
// Typing is a live signal with a short shelf life (common.TYPING_STALE_SECONDS
// is 12), so it is polled faster than mode — but not so fast that an idle
// dashboard makes a request a second forever.
const TYPING_POLL_MS = 4000;

export type Tab = 'instructions' | 'recipients' | 'conversations' | 'demo' | 'settings';

/** What the shell checks before a Brand_Switch (design R7). */
export interface SwitchGuards {
  /** The video visit open in Demo, with the client it was started on. */
  video: ReportedVideo;
  /** Set while the target's last `GET /api/mode` said `live`. */
  live: { recipient: string } | null;
}

export interface BrandSessionProps {
  connection: BrandConnection;
  generation: number;
  multi: boolean;
  tab: Tab;
  setTab: (tab: Tab) => void;
  /** The session's `GET /api/brand` succeeded. Never called by a stale session. */
  onBrandLoaded: (brand: Brand, connectionId: string) => void;
  /** The session's `GET /api/brand` failed or timed out. */
  onBrandFailed: (connectionId: string) => void;
  /** Register the guard getter (null on unmount). */
  registerGuards: (getter: (() => SwitchGuards) | null) => void;
  /** The target's conversation mode, for the document title. */
  onModeChange?: (mode: string) => void;
}

export default function BrandSession(props: BrandSessionProps) {
  const { connection, generation, multi } = props;

  // The loaded brand name improves the label once known; until then the label
  // is the Brand_Id (or the Legacy_Connection's host).
  const [labelName, setLabelName] = useState<string>('');
  const label = brandLabel(connection, labelName ? { name: labelName } : undefined);
  const labelRef = useRef(label);
  labelRef.current = label;

  // One client per session, bound to this connection and generation.
  const api = useMemo<ApiClient>(
    () =>
      createApiClient({
        connectionId: connection.id,
        generation,
        baseUrl: normalizeUrl(connection.apiUrl),
        label: () => labelRef.current,
        multi,
      }),
    [connection.id, connection.apiUrl, generation, multi],
  );

  const [err, setErr] = useState<string>('');
  // A message already in its final (labelled) form: scrub keys only.
  const raise = useCallback((msg: string) => {
    setErr(scrubKeys(msg, registry.allKeys()));
  }, []);

  const videoRef = useRef<ReportedVideo>(null);
  const reportVideo = useCallback((v: ReportedVideo) => {
    videoRef.current = v;
  }, []);

  return (
    <SessionProvider
      api={api}
      multi={multi}
      label={label}
      connection={connection}
      raise={raise}
      reportVideo={reportVideo}
    >
      <SessionBody
        {...props}
        err={err}
        setErrRaw={setErr}
        raise={raise}
        videoRef={videoRef}
        onLabelName={setLabelName}
      />
    </SessionProvider>
  );
}

interface SessionBodyProps extends BrandSessionProps {
  err: string;
  setErrRaw: (msg: string) => void;
  raise: (msg: string) => void;
  videoRef: MutableRefObject<ReportedVideo>;
  onLabelName: (name: string) => void;
}

// Inside the provider, so it can use `track` and `prefix`. Its effects run
// before the provider's own mount effect, so every first load below is tracked
// before the provider decides whether the session is already ready.
function SessionBody({
  connection,
  tab,
  setTab,
  onBrandLoaded,
  onBrandFailed,
  registerGuards,
  onModeChange,
  err,
  setErrRaw,
  raise,
  videoRef,
  onLabelName,
}: SessionBodyProps) {
  const { api, multi, label, prefix, storage, track } = useSession();

  const [brand, setBrand] = useState<Brand | null>(null);
  // The sending agent's registered identity, read live from AWS. Optional
  // everywhere: it needs the API key and the Describe*Registration*
  // permissions, so every consumer falls back to the brand.md values.
  const [identity, setIdentity] = useState<AgentIdentity | null>(null);
  // Read synchronously at mount, before any effect sends a request, from this
  // connection's own entry. Normalize on load: older stored values (from before
  // phone normalization was added, or otherwise malformed) could be missing the
  // leading "+", which AWS's DescribeVerifiedDestinationNumbers 404s on —
  // self-heal here rather than leaving a stale bad value in place forever.
  const [phone, setPhone] = useState<string>(() => {
    const stored = storage.getPhone() || '';
    const normalized = normalizePhone(stored);
    if (normalized && normalized !== stored) storage.setPhone(normalized);
    return normalized || stored;
  });
  const [testers, setTesters] = useState<Tester[]>([]);
  const [testerReload, setTesterReload] = useState(0);
  // Conversation mode for the targeted device. Polled here rather than inside
  // StatusBar because it drives more than the bar: the session-wide handover
  // banner and the tab-label flag read it too, and the shell's document title.
  // While a device is in live mode the bot has stopped answering and every
  // flow button they tap is dropped (channel_adapter.process_inbound), so it
  // must be visible everywhere.
  const [mode, setMode] = useState<string>('');
  // Only what `GET /api/mode` last said, for the switch guard (R7.4): a local
  // set from the status bar or the banner is not recorded here.
  const modeFromGetRef = useRef<string>('');
  // Which recipients are composing a reply right now — session-wide rather
  // than per-target, since any registered recipient can start typing.
  const [typing, setTyping] = useState<TypingRecipient[]>([]);

  // Every message a view raises: labelled in multi mode (unless it already
  // carries the label, as a missing-key message does), with keys scrubbed.
  const onError = useCallback(
    (msg: string) => {
      const text = String(msg);
      const labelled = multi && text.startsWith(`${label}: `) ? text : prefix(text);
      raise(labelled);
    },
    [multi, label, prefix, raise],
  );

  // Latest callbacks from the shell, so the mount-time loads need no deps.
  const shellRef = useRef({ onBrandLoaded, onBrandFailed, onLabelName, onError });
  shellRef.current = { onBrandLoaded, onBrandFailed, onLabelName, onError };
  const connectionId = connection.id;

  useEffect(() => {
    track(api.getBrand(), 'brand')
      .then((b) => {
        setBrand(b);
        if (b?.brandName) shellRef.current.onLabelName(b.brandName);
        shellRef.current.onBrandLoaded(b, connectionId);
      })
      .catch((e) => {
        shellRef.current.onBrandFailed(connectionId);
        // A tracked failure was already raised (labelled) by the session.
        if (!isTrackedLoadError(e)) shellRef.current.onError(String(e));
      });
    // Deliberately silent on failure in single mode: a missing API key is the
    // common case and it only costs the previews their real logo, so it must
    // not raise a page-level error the way a failed brand load does.
    track(api.getAgentIdentity(), 'agent identity')
      .then(setIdentity)
      .catch(() => setIdentity(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api]);

  // Only the first tester load counts toward the switch's loading state; the
  // reloads after an add or a removal stay silent on failure, as today.
  const testersTracked = useRef(false);
  useEffect(() => {
    let p = api.getTesters();
    if (!testersTracked.current) {
      testersTracked.current = true;
      p = track(p, 'recipients');
    }
    p.then(setTesters).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, testerReload]);

  useEffect(() => {
    if (!phone) {
      setMode('');
      modeFromGetRef.current = '';
    }
  }, [phone]);

  usePoll(
    () =>
      api
        .getMode(phone)
        .then((r) => {
          modeFromGetRef.current = r.mode;
          setMode(r.mode);
        })
        .catch(() => {}),
    MODE_POLL_MS,
    [api, phone],
    { enabled: !!phone },
  );

  // Silent on failure, unlike the brand load: without an API key this call 401s
  // on every tick, and a typing indicator is not worth a page-level error.
  usePoll(
    () => api.getTyping().then((r) => setTyping(r.typing)).catch(() => {}),
    TYPING_POLL_MS,
    [api],
  );

  useEffect(() => {
    onModeChange?.(mode);
  }, [mode, onModeChange]);
  // A session that goes away no longer has a live conversation to flag.
  useEffect(() => () => onModeChange?.(''), [onModeChange]);

  const targetName = testers.find((t) => t.phone === phone)?.name || '';

  // Guards read at the moment a switch is requested.
  const guardState = useRef({ phone, targetName });
  guardState.current = { phone, targetName };
  useEffect(() => {
    registerGuards(() => ({
      video: videoRef.current,
      live:
        modeFromGetRef.current === 'live'
          ? { recipient: guardState.current.targetName || guardState.current.phone }
          : null,
    }));
    return () => registerGuards(null);
  }, [registerGuards, videoRef]);

  async function releaseToBot() {
    if (!phone) return;
    await api.setMode(phone, 'bot');
    setMode('bot');
  }

  const savePhone = (p: string) => {
    storage.setPhone(p);
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
      onDismissError={() => setErrRaw('')}
    />
  );

  return (
    <>
      {/* Errors are no longer a full-width alert here: they live in the status
          bar, beside the device state that usually explains them. See
          StatusBar's ErrorIndicator. */}

      {mode === 'live' && (
        <HandoverBanner
          who={targetName || phone}
          role={aAgentRole(brand)}
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
                <SessionContent>
                  {statusBar}
                  <Guide brand={brand} phone={phone} />
                </SessionContent>
              ),
            },
            {
              id: 'demo',
              label: 'Interactive Demos',
              content: (
                <SessionContent>
                  {statusBar}
                  <Demo phone={phone} brand={brand} identity={identity} onError={onError} />
                </SessionContent>
              ),
            },
            {
              id: 'conversations',
              // Flagged in the tab label itself so a handover is visible while
              // the operator is on another tab, not only once they get here.
              label: mode === 'live' ? '2-way Conversations 🔴' : '2-way Conversations',
              content: (
                <SessionContent>
                  {statusBar}
                  <Conversations brand={brand} onError={onError} />
                </SessionContent>
              ),
            },
            {
              id: 'recipients',
              label: 'Recipients',
              content: (
                <SessionContent>
                  {statusBar}
                  <Recipients
                    phone={phone}
                    onChangePhone={savePhone}
                    onError={onError}
                    // Adding or removing a recipient here changes the target
                    // picker in the status bar, which reads this list.
                    onReloadTesters={() => setTesterReload((n) => n + 1)}
                    brand={brand}
                  />
                </SessionContent>
              ),
            },
            {
              id: 'settings',
              label: 'Settings',
              content: (
                <SessionContent>
                  {statusBar}
                  <Settings brand={brand} identity={identity} phone={phone} onError={onError} />
                </SessionContent>
              ),
            },
          ]}
        />
      </div>
    </>
  );
}

// One tab's content. Single mode: exactly today's `SpaceBetween`. Multi mode:
// while the session's tracked loads are outstanding, the content is `inert`
// and `aria-busy` (every send action is disabled, the views stay mounted so
// their loads keep running) under a "Loading <label>…" status. The status sits
// outside the inert element, since inert content is hidden from assistive
// technology.
function SessionContent({ children }: { children: ReactNode }) {
  const { multi, ready, label } = useSession();
  const busy = multi && !ready;
  const inertRef = useInert<HTMLDivElement>(busy);
  const content = <SpaceBetween size="m">{children}</SpaceBetween>;
  if (!multi) return content;
  return (
    <div style={{ position: 'relative' }}>
      <div ref={inertRef} aria-busy={busy ? 'true' : undefined}>
        {content}
      </div>
      {busy && (
        <div
          role="status"
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'center',
            paddingTop: 120,
            background: 'rgba(255, 255, 255, 0.6)',
          }}
        >
          <Box variant="span" fontSize="heading-s">
            <Spinner size="large" /> Loading {label}…
          </Box>
        </div>
      )}
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
  role,
  onOpenConversations,
  onRelease,
}: {
  who: string;
  /** The brand's live-agent role with its article, e.g. "a support specialist". */
  role: string;
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
      className="rcs-demo-handover-banner"
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
        @keyframes rcs-demo-handover-pulse { 0%,100% { opacity: 1 } 50% { opacity: .35 } }
        .rcs-demo-handover-dot { animation: rcs-demo-handover-pulse 1.4s ease-in-out infinite }
        @media (prefers-reduced-motion: reduce) { .rcs-demo-handover-dot { animation: none } }
      `}</style>
      <span
        className="rcs-demo-handover-dot"
        aria-hidden="true"
        style={{ width: 12, height: 12, borderRadius: 6, background: '#fff', flex: '0 0 auto' }}
      />
      <Box variant="span" fontSize="heading-s" fontWeight="bold">
        <span style={{ color: '#fff' }}>{who} asked to talk to a person</span>
      </Box>
      <Box variant="span" fontSize="body-s">
        <span style={{ color: '#fff', opacity: 0.9 }}>
          You're {role} now — the bot has stopped replying, and every card and
          button they tap is ignored until you release the conversation.
        </span>
      </Box>
      <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, flex: '0 0 auto' }}>
        <Button onClick={onOpenConversations}>Open 2-way Conversations</Button>
        <Button loading={releasing} onClick={release}>Release to bot</Button>
      </div>
    </div>
  );
}
