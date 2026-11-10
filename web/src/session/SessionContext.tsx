// Session context: everything a view needs to talk to the Active_Brand's stack
// for the lifetime of one brand session.
//
// One <SessionProvider> is mounted per session (BrandSession renders it under
// `key={`${activeId}:${generation}`}`), so a Brand_Switch unmounts it: nothing
// it tracked raises a message after that, and the next session starts from a
// fresh, not-ready state.
//
// - `single` mode (one Available_Connection): `ready` is true from mount and
//   `track` returns the promise it was given, unchanged. Timing and messages
//   match the single-brand dashboard exactly.
// - `multi` mode: `track` races each first load against a 30 s budget. A load
//   that fails or times out counts as settled and raises
//   `prefix("Couldn't load <what>.")`. `ready` turns true once every tracked
//   load of the switch has settled, and then stays true for the session.
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import type { ApiClient } from '../api';
import type { BrandConnection } from '../connections/types';
import {
  getConnectionDeepLink,
  getPhone,
  setConnectionDeepLink,
  setPhone,
} from '../connections/storage';

/** How long one tracked load may take before it counts as failed. */
export const TRACK_TIMEOUT_MS = 30_000;

/** Per-connection target phone and inbound deep link. */
export interface SessionStorage {
  getPhone: () => string;
  setPhone: (phone: string) => void;
  getDeepLink: () => string;
  setDeepLink: (url: string) => void;
}

/** The video visit Demo has open, with the client it was started on. */
export type ReportedVideo = { token: string; client: ApiClient } | null;

export interface SessionContextValue {
  api: ApiClient;
  /** This session's connection (URL, key and where each came from), as last resolved. */
  connection: BrandConnection;
  /** True when two or more Available_Connections exist. */
  multi: boolean;
  /** Brand_Label of this session's connection. */
  label: string;
  /** `multi ? `${label}: ${msg}` : msg`. */
  prefix: (msg: string) => string;
  storage: SessionStorage;
  /** All tracked loads have settled (always true in single mode). */
  ready: boolean;
  /** Track a first load (30 s budget in multi mode; pass-through in single mode). */
  track: <T>(p: Promise<T>, what: string) => Promise<T>;
  reportVideo: (v: ReportedVideo) => void;
}

/**
 * The rejection `track` produces in multi mode for a failed or timed-out load.
 * Its message has already been raised (labelled) by the session, so a view's
 * own error handler should not show it a second time; see `isTrackedLoadError`.
 */
export class TrackedLoadError extends Error {
  readonly what: string;
  readonly timedOut: boolean;
  readonly original: unknown;
  constructor(message: string, what: string, timedOut: boolean, original: unknown) {
    super(message);
    this.name = 'TrackedLoadError';
    this.what = what;
    this.timedOut = timedOut;
    this.original = original;
  }
}

/** True for a rejection whose message the session already showed. */
export function isTrackedLoadError(e: unknown): e is TrackedLoadError {
  return e instanceof TrackedLoadError;
}

const Ctx = createContext<SessionContextValue | null>(null);

export interface SessionProviderProps {
  api: ApiClient;
  multi: boolean;
  label: string;
  /** The session's connection, for the per-connection storage entries. */
  connection: BrandConnection;
  /**
   * Shows a message that is already in its final (labelled) form. BrandSession
   * passes its error setter here; it still applies `scrubKeys`.
   */
  raise: (msg: string) => void;
  reportVideo: (v: ReportedVideo) => void;
  children: ReactNode;
}

export function SessionProvider({
  api,
  multi,
  label,
  connection,
  raise,
  reportVideo,
  children,
}: SessionProviderProps) {
  const [ready, setReady] = useState<boolean>(!multi);
  const readyRef = useRef<boolean>(!multi);
  const outstanding = useRef(0);
  const mounted = useRef(true);

  // Latest values for the stable callbacks below.
  const labelRef = useRef(label);
  labelRef.current = label;
  const raiseRef = useRef(raise);
  raiseRef.current = raise;

  const prefix = useCallback(
    (msg: string) => (multi ? `${labelRef.current}: ${msg}` : msg),
    [multi],
  );

  const markReady = useCallback(() => {
    if (readyRef.current || !mounted.current) return;
    readyRef.current = true;
    setReady(true);
  }, []);

  const track = useCallback(
    <T,>(p: Promise<T>, what: string): Promise<T> => {
      if (!multi) return p;
      const counts = !readyRef.current; // loads after ready don't hold the overlay
      if (counts) outstanding.current += 1;
      return new Promise<T>((resolve, reject) => {
        let settled = false;
        const settle = () => {
          if (settled) return false;
          settled = true;
          clearTimeout(timer);
          if (counts) {
            outstanding.current -= 1;
            if (outstanding.current <= 0) markReady();
          }
          return true;
        };
        const fail = (original: unknown, timedOut: boolean) => {
          if (!settle()) return;
          const msg = prefix(`Couldn't load ${what}.`);
          if (mounted.current) raiseRef.current(msg);
          reject(new TrackedLoadError(msg, what, timedOut, original));
        };
        const timer = setTimeout(() => fail(undefined, true), TRACK_TIMEOUT_MS);
        // The request itself is not cancelled on a timeout; its late result is ignored.
        p.then(
          (v) => { if (settle()) resolve(v); },
          (e) => fail(e, false),
        );
      });
    },
    [multi, prefix, markReady],
  );

  // Parent effects run after the children's, so every first load issued at
  // mount has been tracked by now. If none was, the switch is already done.
  useEffect(() => {
    if (outstanding.current === 0) markReady();
  }, [markReady]);

  // Timers are deliberately not cleared on cleanup: StrictMode runs this
  // cleanup and re-mounts in development, and a cleared timer would leave a
  // load that never answers counted as outstanding forever. After a real
  // unmount a timer only rejects a promise nobody reads; `mounted` keeps it
  // from raising a message into the next session.
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const storage = useMemo<SessionStorage>(
    () => ({
      getPhone: () => getPhone(connection),
      setPhone: (phone) => setPhone(connection, phone),
      getDeepLink: () => getConnectionDeepLink(connection),
      setDeepLink: (url) => setConnectionDeepLink(connection, url),
    }),
    [connection.brandId, connection.absorbsLegacy],
  );

  const value = useMemo<SessionContextValue>(
    () => ({ api, connection, multi, label, prefix, storage, ready, track, reportVideo }),
    [api, connection, multi, label, prefix, storage, ready, track, reportVideo],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** The whole session context. Throws outside a <SessionProvider>. */
export function useSession(): SessionContextValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('useSession() must be used inside a <SessionProvider>');
  return v;
}

/** The session's bound API client. */
export function useApi(): ApiClient {
  return useSession().api;
}
