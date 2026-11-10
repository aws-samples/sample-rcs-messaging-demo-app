// usePoll: the one place a session view starts a repeating request.
//
// - With `trackAs`, the first call goes through the session's `track()` at
//   once, so it counts toward the switch's loading state (and, in multi mode,
//   raises "Couldn't load <trackAs>." on failure or after 30 s).
// - Without `trackAs`, the first call waits until the session is `ready`.
// - The interval starts only when the session is `ready`.
// - `enabled: false` makes no call and starts no interval (for example the
//   mode poll while no target phone is set).
// - Effect cleanup clears the interval. A Brand_Switch remounts the session,
//   so its cleanup stops every poll aimed at the previous brand's stack.
//
// In single mode `ready` is true from mount, so this is `fn(); setInterval(fn, ms)`
// with a `clearInterval` cleanup, the same as the effects it replaces.
//
// `fn` handles its own errors (as today's poll callbacks do); a tracked first
// call's rejection is swallowed here after `track` has reported it.
import { useEffect, useRef, type DependencyList } from 'react';
import { useSession } from './SessionContext';

export interface UsePollOptions {
  /** Track the first call as this load ("recipients", "conversations", ...). */
  trackAs?: string;
  /** When false, no call is made and no interval runs. Default true. */
  enabled?: boolean;
}

export function usePoll(
  fn: () => unknown,
  ms: number,
  deps: DependencyList,
  { trackAs, enabled = true }: UsePollOptions = {},
): void {
  const { ready, track } = useSession();

  const fnRef = useRef(fn);
  fnRef.current = fn;
  const trackRef = useRef(track);
  trackRef.current = track;

  // Whether the first call for the current deps has been made.
  const firstDone = useRef(false);

  // Declared before the main effect so it runs first when deps change.
  useEffect(() => {
    firstDone.current = false;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, enabled]);

  useEffect(() => {
    if (!enabled) return;
    const run = () => {
      try {
        void fnRef.current();
      } catch {
        /* fn reports its own errors */
      }
    };

    if (!firstDone.current) {
      if (trackAs !== undefined) {
        firstDone.current = true;
        let p: Promise<unknown>;
        try {
          p = Promise.resolve(fnRef.current());
        } catch (e) {
          p = Promise.reject(e);
        }
        trackRef.current(p, trackAs).catch(() => {});
      } else if (ready) {
        firstDone.current = true;
        run();
      }
    }

    if (!ready) return;
    const id = setInterval(run, ms);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, enabled, ready, ms, trackAs]);
}
