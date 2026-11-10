// Is a wired brand really deployed and usable?
//
// The dashboard lists a brand only when it can load that brand's agent
// identity. That one call needs everything a brand has to have: an API URL and
// a key, a live stack that accepts the key, and a real RCS agent with a
// readable registration. A brand that fails it (a deleted stack, a wrong or
// missing key, a deleted agent, no answer in time) is simply not offered. The
// dashboard says nothing about it: a brand that is not deployed is not part of
// this dashboard.
//
// `GET /api/agent-identity` never raises on the server. For a deleted agent it
// answers 200 with `source: "unavailable"` and an `error`, so a 200 alone is
// not enough; the body has to say `source: "live"`.
//
// The key goes only to the connection's own URL, as every authenticated call
// does. This module logs nothing and returns only a boolean, so no key or
// response text can leave it.

import type { AgentIdentity } from '../api';
import { normalizeUrl } from './resolve';
import type { BrandConnection } from './types';

/** Long enough for a cold Lambda, short enough that a dead stack never stalls the first paint. */
export const VERIFY_TIMEOUT_MS = 4000;

/** What a verification needs from a connection. */
export type VerifiableConnection = Pick<BrandConnection, 'apiUrl' | 'apiKey'>;

export async function verifyConnection(
  conn: VerifiableConnection,
  timeoutMs: number = VERIFY_TIMEOUT_MS,
  fetchImpl: typeof fetch = fetch,
): Promise<boolean> {
  const base = normalizeUrl(conn.apiUrl);
  // No key means the authenticated read cannot be made: not usable.
  if (!base || !conn.apiKey) return false;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetchImpl(`${base}/api/agent-identity`, {
      headers: { 'X-Api-Key': conn.apiKey },
      signal: ctrl.signal,
    });
    if (!res.ok) return false;
    const body = (await res.json()) as Partial<AgentIdentity> | null;
    return !!body && body.source === 'live';
  } catch {
    // Network error, abort, or a body that is not JSON: not usable.
    return false;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Identity of a connection for caching a verdict: id, URL and key. A rewired
 * brand (new URL or key after a redeploy) has a new fingerprint and is checked
 * again. Held in memory only; never rendered or logged.
 */
export function fingerprint(c: BrandConnection): string {
  return `${c.id}\u0000${normalizeUrl(c.apiUrl)}\u0000${c.apiKey}`;
}
