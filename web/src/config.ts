// Normalize a user-entered phone number to E.164 (e.g. "+12065550100").
// SendRcsMessage rejects anything else with INVALID_PARAMETER on
// destinationPhoneNumber, so the dashboard must not send raw/unformatted input.
// Returns null if the input can't be confidently normalized.
export function normalizePhone(raw: string): string | null {
  const trimmed = (raw || '').trim();
  if (!trimmed) return null;
  const digits = trimmed.replace(/[^\d+]/g, '');
  let candidate: string;
  if (digits.startsWith('+')) {
    candidate = digits;
  } else if (digits.length === 10) {
    // Bare 10-digit US number, e.g. "2065550100".
    candidate = `+1${digits}`;
  } else if (digits.length === 11 && digits.startsWith('1')) {
    // 11-digit with US country code but no "+", e.g. "12065550100".
    candidate = `+${digits}`;
  } else {
    candidate = `+${digits}`;
  }
  return /^\+[1-9]\d{6,14}$/.test(candidate) ? candidate : null;
}

// API base URL — never hardcoded. Comes from VITE_API_URL (set from the CDK
// stack's ApiUrl output) or a value the user enters in the dashboard (stored in
// localStorage). This lets the same build point at any deployment.
const LS_KEY = 'anyhealth_api_url';
// Shared API key for the write routes (trigger/push/reply/reset/etc) and for the
// reads that return recipient data (testers/conversations/media-latest/mode/
// health). Comes from
// the CDK-created Secrets Manager secret `<prefix>-demo-api-key` — retrieve it
// with `aws secretsmanager get-secret-value` and paste it into the dashboard.
const LS_KEY_APIKEY = 'anyhealth_api_key';

// The agent's inbound deep link — a GSMA-standard `sms:` URI that opens the
// member's messaging app with a message to the agent pre-populated. The deep
// link is generated in the console under the agent's Testing tab and pasted here.
const LS_KEY_DEEPLINK = 'anyhealth_deep_link';

function stored(key: string): string {
  try {
    return localStorage.getItem(key) || '';
  } catch {
    return '';
  }
}

export function getApiUrl(): string {
  const fromEnv = import.meta.env.VITE_API_URL || '';
  return (fromEnv || stored(LS_KEY)).replace(/\/$/, '');
}

export function setApiUrl(url: string): void {
  try {
    localStorage.setItem(LS_KEY, url.replace(/\/$/, ''));
  } catch {
    /* ignore */
  }
}

export function getDeepLink(): string {
  return import.meta.env.VITE_DEEP_LINK || stored(LS_KEY_DEEPLINK);
}

export function setDeepLink(url: string): void {
  try {
    localStorage.setItem(LS_KEY_DEEPLINK, url.trim());
  } catch {
    /* ignore */
  }
}

// Pulls the pre-populated message body out of an `sms:` deep link, and rewrites
// it. Kept here rather than in the view because both the QR panel and its
// mismatch warning need the same parse, and `sms:` URIs are not parseable by
// `new URL()` consistently across browsers (no `//` authority), so the query
// string is split off by hand.
export function deepLinkBody(url: string): string {
  const q = (url || '').split('?')[1];
  if (!q) return '';
  return new URLSearchParams(q).get('body') || '';
}

export function withDeepLinkBody(url: string, body: string): string {
  const [base, q] = (url || '').split('?');
  const params = new URLSearchParams(q || '');
  params.set('body', body);
  // URLSearchParams encodes spaces as "+", which messaging apps show literally
  // in the pre-populated message; %20 is what the console's own links use.
  return `${base}?${params.toString().replace(/\+/g, '%20')}`;
}

export function getApiKey(): string {
  return import.meta.env.VITE_API_KEY || stored(LS_KEY_APIKEY);
}

export function setApiKey(key: string): void {
  try {
    localStorage.setItem(LS_KEY_APIKEY, key);
  } catch {
    /* ignore */
  }
}
