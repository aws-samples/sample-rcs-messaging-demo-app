import { getApiUrl, getApiKey } from './config';

// One contact action submitted on the RCS registration. These render as the
// Call / Website / Email buttons on the agent profile in the recipient's
// messaging app -- `label` is the caption shown under the button.
export interface RcsContact {
  kind: 'Website' | 'Phone' | 'Email';
  label: string;
  value: string;
}

// The RCS testing-registration fields from content/brand.md frontmatter: the
// brand identity a recipient's messaging app renders. Separate from the
// dashboard theming fields above because these are submitted to AWS and
// reviewed, not local presentation.
export interface RcsRegistrationInfo {
  senderDisplayName: string;
  serviceName: string;
  agentDescription: string;
  useCase: string;
  logoImage: string;
  bannerImage: string;
  privacyPolicyUrl: string;
  termsAndConditionsUrl: string;
  averageMonthlyRcsFrequency: string;
  monthlyRcsVolume: string;
  contacts: RcsContact[];
}

// The identity read live off the AWS RCS registration — what a handset actually
// renders — as opposed to RcsRegistrationInfo above, which is what
// content/brand.md *says* was submitted. The two routinely differ: the demo's
// placeholder brand is "AnyHealth" while the agent doing the sending carries
// whatever was registered on the account.
//
// `source` is 'live' when the read succeeded and 'unavailable' otherwise (no
// API key, missing IAM permission, no testing registration yet), in which case
// `error` says why and callers fall back to the brand.md values.
export interface AgentIdentity {
  source: 'live' | 'unavailable';
  error: string;
  agentId: string;
  /**
   * SMS origination identity used for per-message RCS→SMS fallback, from the
   * stack's `-c smsFallbackNumber=+1…`. Empty when the deployer supplied none,
   * which means no message can carry a FallbackConfiguration at all. Populated
   * even when `source` is 'unavailable' — it is local deployment config, not
   * registration data.
   */
  smsFallbackNumber?: string;
  /**
   * The AWS account and Region this stack — the RCS agent, Lambdas, table and
   * bucket — is deployed in. Deployment config like smsFallbackNumber, so it is
   * populated even when `source` is 'unavailable'. Absent (or empty) on a
   * deployment whose Lambda predates it.
   */
  awsAccountId?: string;
  region?: string;
  agentStatus?: string;
  testingAgentStatus?: string;
  testingAgentId?: string;
  registrationId?: string;
  senderDisplayName?: string;
  brandName?: string;
  serviceName?: string;
  agentDescription?: string;
  accentColor?: string;
  useCase?: string;
  billingCategory?: string;
  /** Presigned CloudFront URL to the uploaded asset. Time-limited — don't persist it. */
  logoUrl?: string;
  bannerUrl?: string;
  contacts?: RcsContact[];
  privacyPolicyUrl?: string;
  termsAndConditionsUrl?: string;
}

export interface Brand {
  brandName: string;
  accentColor: string;
  tagline: string;
  memberServicesPhone: string;
  storeName: string;
  // The message body the agent's inbound deep link pre-populates, which the
  // channel adapter treats as "open the welcome message". Surfaced so the
  // Recipients tab can show the exact text and warn when a pasted deep link
  // carries a different one.
  deepLinkKeyword: string;
  /** Absent on older deployments whose Lambda predates the registration panel. */
  registration?: RcsRegistrationInfo;
}

// One documented AWS limit, as transcribed in content/rcs-features.json.
export interface RcsLimit {
  key?: string;
  label: string;
  value: number;
  unit?: string;
  note?: string;
  docUrl?: string;
}

// One RCS feature or demo pattern, resolved server-side from
// content/rcs-features.json. `status` distinguishes what this demo actually
// shows from what the service offers but the demo omits, so the dashboard can
// say so instead of implying everything on screen is everything RCS does.
export interface RcsFeature {
  key: string;
  name: string;
  kind: 'rcs-api' | 'demo-pattern' | 'caveat';
  blurb: string;
  gotcha?: string;
  apiShape?: string;
  status: 'demonstrated' | 'not-demonstrated' | 'planned-by-aws';
  statusNote?: string;
  docUrl?: string;
  limits?: RcsLimit[];
}

export interface Vignette {
  id: string;
  name: string;
  category: string;
  audience: string;
  trigger: string;
  description: string;
  /** Resolved by the API from the feature keys in dashboard_handler.VIGNETTES. */
  features: RcsFeature[];
}

export interface RcsRegistry {
  /** YYYY-MM-DD: when a person last read the limits against the AWS user guide. */
  reviewedOn?: string;
  features: RcsFeature[];
  limits: RcsLimit[];
}

// Mirrors the RCS Content shapes used across lambda/flows/*.py and
// common.build_suggestions — enough structure to render a preview, not a
// full typing of the SendRcsMessage API.
export interface RcsSuggestion {
  Reply?: { Text: string; PostbackData: string };
  OpenUrl?: { Text: string; PostbackData: string; Url: string };
  DialPhone?: { Text: string; PostbackData: string; PhoneNumber: string };
  CreateCalendarEvent?: { Text: string; PostbackData: string; Title?: string; Description?: string };
  ShowLocation?: { Text: string; PostbackData: string; Label?: string };
  RequestLocation?: { Text: string; PostbackData: string };
}

export interface RcsCardContent {
  Title?: string;
  Description?: string;
  Media?: { FileUrl: string; Height?: string };
  Suggestions?: RcsSuggestion[];
}

export interface RcsMessage {
  Content?: {
    TextMessage?: { Body: string };
    RichCard?: { CardOrientation?: string; CardContent: RcsCardContent };
    Carousel?: { CardWidth?: string; CardContents: RcsCardContent[] };
  };
  Suggestions?: RcsSuggestion[];
}

export interface VignettePreview {
  available: boolean;
  messages?: RcsMessage[];
  // Set when the vignette builds content the RCS API would reject (e.g. a
  // carousel outside the 2-10 card range). Distinct from a plain unavailable
  // preview, which just means the vignette has no fixed content to show.
  error?: string;
}

export interface RcsSpendLimit {
  enforcedLimit: number;
  maxLimit: number;
  overridden: boolean;
}

export interface Health {
  rcsQuotaAlert: { active: boolean; error: string; lastSeen: string };
  rcsSpendLimit: RcsSpendLimit | null;
}

/** One recipient the RCS client says is composing a reply right now. */
export interface TypingRecipient {
  /** Conversation hash, not a phone number — resolve it against Tester.phone_hash. */
  phone_hash: string;
  /** Unix seconds of the most recent typing signal from that recipient. */
  at: number;
}

export interface LatestMediaEntry {
  preview_url: string | null;
  // media_convert still owes this photo its JPEG and/or its GenAI description.
  // preview_url is null for the window where the only stored key is a HEIC no
  // browser can render — see dashboard_handler.get_latest_media_for_demo.
  converting?: boolean;
  classification: string;
  file_name: string;
  updated: string;
}

// Keyed by vignette id (photo_submission | insurance_upload) — see
// dashboard_handler.get_latest_media_for_demo. A vignette id is absent
// entirely if that recipient hasn't sent/uploaded a photo through it yet.
export type LatestMedia = Partial<Record<'photo_submission' | 'insurance_upload', LatestMediaEntry>>;

// What GET /api/video/join returns: the two opaque blobs the Chime SDK needs to
// construct a MeetingSessionConfiguration. Typed as `unknown` rather than
// restated field by field — the SDK owns their shape, and a partial local
// re-declaration would be a second source of truth that silently rots.
// `error` is set instead (with no Meeting/Attendee) when the token is unknown,
// expired, or the visit is already full.
export interface VideoJoin {
  Meeting?: unknown;
  Attendee?: unknown;
  error?: string;
}

// Presence, from heartbeats rather than from Chime: the dashboard has to be able
// to say "the patient is waiting" *before* the clinician joins, at which point
// there is no local meeting session to ask. Booleans only — the route is
// unauthenticated, so it must not describe the member any further than this.
export interface VideoStatus {
  exists: boolean;
  started?: boolean;
  member: boolean;
  clinician: boolean;
}

export interface Tester {
  phone: string;
  phone_hash: string;
  name: string;
  status: string;
  /** VerifiedDestinationNumberId — the handle AWS deletes by. */
  id?: string;
  created?: string;
  messages_sent?: number;
  messages_received?: number;
  delivered?: number;
  read?: number;
  failed?: number;
  /**
   * RCS_FALLEN_BACK_TO_SMS count. Overlaps `failed` on purpose — the RCS leg
   * failed and the SMS fallback then reached the member, and two separate
   * events say so. See _conversation_metrics in dashboard_handler.py.
   */
  fell_back_to_sms?: number;
  last_activity?: string;
  /**
   * True when this number is on the account's Default opt-out list — the
   * recipient texted STOP or a custom OPT_OUT keyword. Observed on a testing
   * agent: the service then refuses every send to a listed number with
   * DESTINATION_PHONE_NUMBER_OPTED_OUT. The channel adapter reads this same list
   * before it answers (cached 30 s, fails open) and skips such a sender; this
   * sample keeps no opt-out record of its own. See
   * dashboard_handler.opted_out_numbers.
   */
  opted_out?: boolean;
}

// A keyword registered on the RCS agent (PutKeyword/DescribeKeywords).
// End User Messaging sends its response and applies its action when a recipient
// texts it, and also forwards the message to the demo's Lambda (a keyword you
// register arrives with messageKeyword set; the built-in HELP and STOP arrive
// without it) — distinct from the app-side greeting router in
// channel_adapter.py. `action` is what the service does when a recipient texts
// it; `reserved` marks the built-in HELP/STOP, which the dashboard shows
// read-only (the deploy registers their text, or it is set by hand with
// put-keyword, see AGENTS.md).
export type KeywordAction = 'AUTOMATIC_RESPONSE' | 'OPT_IN' | 'OPT_OUT';

export interface Keyword {
  keyword: string;
  message: string;
  action: KeywordAction | string;
  reserved: boolean;
}

// Result of creating or deleting a keyword. A failed write is a non-2xx answer
// and rejects with an ApiError. `error` stays optional so a 2xx body that still
// carries one is shown to the operator instead of being read as success.
export interface KeywordMutation {
  status?: 'created' | 'deleted';
  keyword?: string;
  message?: string;
  action?: string;
  note?: string;
  error?: string;
}

// Result of adding or deleting a verified test device. The handler reports
// failure in the body, so `error` can be set on an HTTP 200.
export interface TesterMutation {
  status?: 'created' | 'already_exists' | 'deleted' | 'not_ours';
  phone?: string;
  name?: string;
  id?: string;
  ids?: string[];
  note?: string;
  error?: string;
  reason?: 'QUOTA_EXCEEDED';
}

export interface ConversationSummary {
  phone_hash: string;
  name: string;
  last_message: string;
  last_direction: string;
  mode: string;
}

export interface Message {
  type: 'message' | 'event';
  direction?: string;
  body?: string;
  timestamp: string;
  actor?: string;
  event_type?: string;
  rcs_content?: any;
  // Native inbound RCS media (see common.log_inbound_media): the raw
  // mediaStatus/s3Key/mimeType/etc dict AWS published to the inbound SNS
  // topic, distinct from rcs_content (which is only ever an outbound send).
  media_content?: any;
}

export interface ConversationDetail {
  phone_hash: string;
  name: string;
  mode: string;
  messages: Message[];
}

/**
 * A non-2xx answer from the API. `message` is "<status> <raw body>", which is
 * what callers that show the thrown error have always displayed. When the body
 * is the handler's `{ error, code }` shape (ApiError in dashboard_handler.py),
 * `userMessage` is its short operator-safe text and `code` its stable code;
 * gateway answers such as the authorizer's 401/403 carry neither.
 */
export class ApiError extends Error {
  status: number;
  code?: string;
  userMessage?: string;

  constructor(status: number, body: string) {
    super(`${status} ${body}`);
    this.status = status;
    try {
      const parsed = JSON.parse(body);
      if (typeof parsed?.error === 'string') this.userMessage = parsed.error;
      if (typeof parsed?.code === 'string') this.code = parsed.code;
    } catch {
      // Not JSON (a gateway or proxy page): only status and message are known.
    }
  }
}

async function req<T>(path: string, init?: RequestInit, authed = false): Promise<T> {
  const base = getApiUrl();
  if (!base) throw new Error('API URL not configured');
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (authed) {
    const key = getApiKey();
    if (!key) throw new Error('This action requires the API key. Set it in Settings.');
    headers['X-Api-Key'] = key;
  }
  const res = await fetch(base + path, { headers, ...init });
  if (!res.ok) throw new ApiError(res.status, await res.text());
  return (await res.json()) as T;
}

export const api = {
  // Unauthenticated: static demo metadata only.
  getBrand: () => req<Brand>('/api/brand'),
  getVignettes: () => req<Vignette[]>('/api/vignettes'),
  getRcsFeatures: () => req<RcsRegistry>('/api/vignettes/features'),
  previewVignette: (id: string) => req<VignettePreview>(`/api/vignettes/preview?id=${encodeURIComponent(id)}`),
  // Build metadata about the deployment this console is pointed at — no account
  // or recipient data, so it needs no key. The frontend's own version needs no
  // call: vite.config.ts stamps it in as import.meta.env.VITE_FE_VERSION.
  getVersion: () => req<{ backend: string }>('/api/version'),
  // Authenticated reads — these return phone numbers, transcripts, member media
  // or account limits. The `true` argument sends x-api-key; it must stay in step
  // with the authorized GET route list in cdk/lib/anyhealth-stack.ts.
  getHealth: () => req<Health>('/api/health', undefined, true),
  getAgentIdentity: () => req<AgentIdentity>('/api/agent-identity', undefined, true),
  getTesters: () => req<Tester[]>('/api/testers', undefined, true),
  getTestersWithMetrics: () => req<Tester[]>('/api/testers/metrics', undefined, true),
  // add/delete return 200 with an `error` field rather than an HTTP error, so
  // callers must check it — `req` only throws on a non-2xx status. `reason` is
  // 'QUOTA_EXCEEDED' when the agent's 10 verified test devices are all taken.
  addTester: (phone: string, name: string) =>
    req<TesterMutation>('/api/testers', { method: 'POST', body: JSON.stringify({ phone, name }) }, true),
  deleteTester: (phone: string) =>
    req<TesterMutation>(`/api/testers/${encodeURIComponent(phone)}`, { method: 'DELETE' }, true),
  setTesterName: (phone: string, name: string) =>
    req(`/api/testers/${encodeURIComponent(phone)}/name`, { method: 'PUT', body: JSON.stringify({ name }) }, true),
  // Custom keywords registered on the RCS agent. A failed create/delete is a
  // non-2xx answer, so these reject with an ApiError whose `userMessage` is safe
  // to show (unlike the tester mutations above, which report failure in a 200
  // body). createKeyword is an upsert (PutKeyword replaces an existing keyword's
  // message/action), so it doubles as edit.
  getKeywords: () => req<{ keywords: Keyword[]; error?: string }>('/api/keywords', undefined, true),
  createKeyword: (keyword: string, message: string, action: KeywordAction) =>
    req<KeywordMutation>('/api/keywords', { method: 'POST', body: JSON.stringify({ keyword, message, action }) }, true),
  deleteKeyword: (keyword: string) =>
    req<KeywordMutation>(`/api/keywords/${encodeURIComponent(keyword)}`, { method: 'DELETE' }, true),
  getTesterStatus: (phone: string) =>
    req<{ phone: string; status: string }>(`/api/testers/status?phone=${encodeURIComponent(phone)}`, undefined, true),
  getConversations: () => req<{ conversations: ConversationSummary[] }>('/api/conversations', undefined, true),
  getConversation: (hash: string, events = false) =>
    req<ConversationDetail>(`/api/conversations/${hash}?include_events=${events}`, undefined, true),
  trigger: (phone: string, trigger: string) =>
    req('/api/trigger', { method: 'POST', body: JSON.stringify({ phone, trigger }) }, true),
  // Sends the video-visit invitation card and returns the visit token the
  // handset's chip will carry, so the operator console can join the *same* Chime
  // meeting. Deliberately not `trigger('Start: Video_Visit')`: that path lets the
  // flow mint its own token, which the dashboard never sees — both sides would
  // then sit in separate, empty meetings.
  startVideoVisit: (phone: string) =>
    req<{ status: string; phone: string; visit: string }>(
      '/api/video/start', { method: 'POST', body: JSON.stringify({ phone }) }, true),
  // Mints a visit token without sending anything, for the "Video preview" modal —
  // the video-visit counterpart of the device preview on every other card.
  previewVideoVisit: () =>
    req<{ visit: string }>('/api/video/preview', { method: 'POST', body: '{}' }, true),
  // The URL of the member's own webview for a given token. Absolute and
  // cross-origin (the API domain, not the dashboard's), because that page is
  // served by the dashboard Lambda behind API Gateway — which is also why the
  // iframe embedding it has to delegate camera and microphone explicitly.
  videoVisitWebviewUrl: (visit: string, preview = false) =>
    `${getApiUrl()}/webview/video-visit?visit=${encodeURIComponent(visit)}${preview ? '&preview=1' : ''}`,
  // The visit lifecycle the modal drives. Unauthenticated on the server because
  // the member's webview shares these routes and holds no API key; see
  // video_visit.py. Every one carries role=clinician — the role is what makes
  // "Leave and end visit" end it for both sides while the member's page
  // backgrounding does not.
  videoJoin: (visit: string) =>
    req<VideoJoin>(`/api/video/join?visit=${encodeURIComponent(visit)}&role=clinician`),
  videoStatus: (visit: string) =>
    req<VideoStatus>(`/api/video/status?visit=${encodeURIComponent(visit)}`),
  videoPing: (visit: string) =>
    req(`/api/video/ping?visit=${encodeURIComponent(visit)}&role=clinician`),
  videoEnd: (visit: string) =>
    req(`/api/video/end?visit=${encodeURIComponent(visit)}&role=clinician`),
  reply: (phone: string, message: string, agent = 'Care Advocate') =>
    req('/api/reply', { method: 'POST', body: JSON.stringify({ phone, message, agent }) }, true),
  setMode: (phone: string, mode: 'bot' | 'live') =>
    req('/api/mode', { method: 'POST', body: JSON.stringify({ phone, mode }) }, true),
  // Who is composing right now, across every registered recipient. Hashes only;
  // the status bar maps them to names from the tester list it already holds.
  getTyping: () =>
    req<{ typing: TypingRecipient[]; staleAfterSeconds: number }>('/api/typing', undefined, true),
  getMode: (phone: string) => req<{ phone: string; mode: string }>(`/api/mode?phone=${encodeURIComponent(phone)}`, undefined, true),
  reset: () => req<{ status: string; deleted: number; deleted_media_objects: number }>('/api/reset', { method: 'POST' }, true),
  // Unauthenticated by necessity: the return value is used directly as an
  // <img src>, which cannot carry an x-api-key header. The server restricts
  // which key prefixes it will presign — see dashboard_handler.get_media_url.
  mediaUrl: (key: string) => `${getApiUrl()}/api/media?key=${encodeURIComponent(key)}`,
  getLatestMedia: (phone: string) => req<LatestMedia>(`/api/media/latest?phone=${encodeURIComponent(phone)}`, undefined, true),
};
