import { useEffect, useState } from 'react';
import Table from '@cloudscape-design/components/table';
import CollectionPreferences from '@cloudscape-design/components/collection-preferences';
import Header from '@cloudscape-design/components/header';
import Button from '@cloudscape-design/components/button';
import Badge from '@cloudscape-design/components/badge';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Input from '@cloudscape-design/components/input';
import Popover from '@cloudscape-design/components/popover';
import Link from '@cloudscape-design/components/link';
import FormField from '@cloudscape-design/components/form-field';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import Container from '@cloudscape-design/components/container';
import Alert from '@cloudscape-design/components/alert';
import Modal from '@cloudscape-design/components/modal';
import type { CollectionPreferencesProps } from '@cloudscape-design/components/collection-preferences';
import { QRCodeSVG } from 'qrcode.react';
import { api, Brand, Tester } from '../api';
import { normalizePhone, getDeepLink, setDeepLink, deepLinkBody, withDeepLinkBody } from '../config';

// Column order shown by default (also the order options appear in the
// preferences dialog). "target" is pinned always-visible since hiding it
// would leave no way to change the current target from this table.
const CONTENT_DISPLAY_OPTIONS = [
  { id: 'target', label: 'Target', alwaysVisible: true },
  { id: 'name', label: 'User' },
  { id: 'phone', label: 'Number' },
  { id: 'status', label: 'Status' },
  { id: 'opted_out', label: 'Opt-out' },
  { id: 'created', label: 'Registered' },
  { id: 'last_activity', label: 'Last activity' },
  { id: 'sent', label: 'Sent' },
  { id: 'delivered', label: 'Delivered' },
  { id: 'read', label: 'Read' },
  { id: 'failed', label: 'Failed' },
  { id: 'fell_back_to_sms', label: 'Fell back to SMS' },
  { id: 'received', label: 'Received' },
  { id: 'remove', label: 'Remove' },
];

const DEFAULT_CONTENT_DISPLAY: ReadonlyArray<CollectionPreferencesProps.ContentDisplayItem> =
  CONTENT_DISPLAY_OPTIONS.map((o) => ({ id: o.id, visible: true }));

export default function Recipients({
  phone,
  onChangePhone,
  onError,
  onReloadTesters,
  brand,
}: {
  phone: string;
  onChangePhone: (phone: string) => void;
  onError: (e: string) => void;
  /** Refreshes the app-level tester list behind the target-phone picker. */
  onReloadTesters?: () => void;
  brand: Brand | null;
}) {
  const [testers, setTesters] = useState<Tester[]>([]);
  const [loading, setLoading] = useState(true);
  // The per-agent verified-device cap, read from the RCS registry
  // (content/rcs-features.json -> limits.testDevicesPerAgent) rather than
  // written here, so the number and its "not increasable" note have one home.
  const [cap, setCap] = useState<number | null>(null);
  const [pendingRemove, setPendingRemove] = useState<Tester | null>(null);
  const [removing, setRemoving] = useState(false);
  const [contentDisplay, setContentDisplay] =
    useState<ReadonlyArray<CollectionPreferencesProps.ContentDisplayItem>>(DEFAULT_CONTENT_DISPLAY);

  const load = () =>
    api.getTestersWithMetrics()
      .then(setTesters)
      .catch((e) => onError(String(e)))
      .finally(() => setLoading(false));

  useEffect(() => { load(); }, []);

  useEffect(() => {
    // Silent on failure: without it the count simply loses its denominator.
    api.getRcsFeatures()
      .then((r) => setCap(r.limits.find((l) => l.key === 'testDevicesPerAgent')?.value ?? null))
      .catch(() => {});
  }, []);

  const atCap = cap !== null && testers.length >= cap;

  async function saveName(phone: string, name: string) {
    await api.setTesterName(phone, name);
    await load();
  }

  async function removeRecipient() {
    const t = pendingRemove;
    if (!t) return;
    setRemoving(true);
    try {
      const r = await api.deleteTester(t.phone);
      if (r.error) {
        onError(r.error);
      } else if (t.phone === phone) {
        // The target now points at a device that can no longer receive
        // anything. Clear it rather than leave every send failing.
        onChangePhone('');
      }
      setPendingRemove(null);
      await load();
      onReloadTesters?.();
    } catch (e) {
      onError(String(e));
    } finally {
      setRemoving(false);
    }
  }

  return (
    <SpaceBetween size="m">
    {atCap && (
      <Alert type="info" header={`All ${cap} verified test devices are in use`}>
        <div style={{ maxWidth: 900 }}>
          AWS caps verified destination numbers at {cap} per RCS agent, and this quota is{' '}
          <b>not</b> adjustable, so registering an eleventh number fails with{' '}
          <Box variant="code" display="inline">ServiceQuotaExceededException</Box>. Remove a
          recipient to free a slot.
        </div>
      </Alert>
    )}
    <Table<Tester>
      header={
        <Header
          variant="h2"
          counter={cap !== null ? `(${testers.length}/${cap})` : `(${testers.length})`}
          description="Phone numbers registered as verified test recipients for this RCS agent. Assign a name to each so conversations are easy to identify. The agent holds a fixed number of these, so removing one is how you make room for another device."
          actions={
            <AddRecipient
              onAdded={() => { load(); onReloadTesters?.(); }}
              onError={onError}
              atCap={atCap}
              cap={cap}
            />
          }
        >
          Recipients
        </Header>
      }
      loading={loading}
      loadingText="Loading recipients…"
      items={testers}
      trackBy="phone_hash"
      sortingDisabled={false}
      resizableColumns
      columnDisplay={contentDisplay}
      empty={
        <Box textAlign="center" color="text-body-secondary" padding="l">
          No recipients yet. Use “Add recipient” to register a phone number.
        </Box>
      }
      submitEdit={async (item, _column, newValue) => {
        try {
          await saveName(item.phone, String(newValue ?? ''));
        } catch (e) {
          onError(String(e));
          throw e;
        }
      }}
      preferences={
        <CollectionPreferences
          title="Preferences"
          confirmLabel="Confirm"
          cancelLabel="Cancel"
          preferences={{ contentDisplay }}
          onConfirm={({ detail }) => {
            if (detail.contentDisplay) setContentDisplay(detail.contentDisplay);
          }}
          contentDisplayPreference={{
            title: 'Column visibility',
            description: 'Choose which columns to show and their order.',
            options: CONTENT_DISPLAY_OPTIONS,
          }}
        />
      }
      columnDefinitions={[
        {
          id: 'target',
          header: 'Target',
          width: 140,
          minWidth: 140,
          cell: (t) =>
            t.phone === phone ? (
              <button
                type="button"
                disabled
                aria-label={`${t.name || t.phone} is the current target recipient`}
                style={{
                  width: 96,
                  minWidth: 96,
                  height: 44,
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  border: '2px solid #0f7b6c',
                  borderRadius: 22,
                  background: '#e7f6f3',
                  color: '#0f7b6c',
                  padding: 0,
                  opacity: 1,
                  cursor: 'default',
                }}
              >
                <svg width="70" height="24" viewBox="0 0 70 24" aria-hidden="true" focusable="false">
                  <text
                    x="35"
                    y="17"
                    textAnchor="middle"
                    fill="currentColor"
                    fontSize="15"
                    fontWeight="700"
                    fontFamily="Arial, sans-serif"
                  >
                    In Use
                  </text>
                </svg>
              </button>
            ) : (
              <button
                type="button"
                aria-label={`Select ${t.name || t.phone} as the target recipient`}
                title="Select this recipient"
                onClick={() => onChangePhone(t.phone)}
                style={{
                  width: 112,
                  minWidth: 112,
                  height: 44,
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  border: '2px solid #0972d3',
                  borderRadius: 22,
                  background: '#fff',
                  color: '#0972d3',
                  padding: 0,
                  cursor: 'pointer',
                }}
              >
                <svg width="82" height="24" viewBox="0 0 82 24" aria-hidden="true" focusable="false">
                  <text
                    x="41"
                    y="17"
                    textAnchor="middle"
                    fill="currentColor"
                    fontSize="16"
                    fontWeight="700"
                    fontFamily="Arial, sans-serif"
                  >
                    Select
                  </text>
                </svg>
              </button>
            ),
        },
        {
          id: 'name',
          header: 'User',
          // minWidth has to clear the header label *plus* the sort and
          // edit-pencil icons, or the label itself renders truncated ("User…")
          // however wide the page is.
          minWidth: 130,
          sortingField: 'name',
          cell: (t) => t.name || <Box color="text-body-secondary">(unnamed)</Box>,
          editConfig: {
            ariaLabel: 'User',
            editIconAriaLabel: 'Edit user',
            editingCell: (item, { currentValue, setValue }) => (
              <Input
                autoFocus
                value={currentValue ?? item.name}
                onChange={({ detail }) => setValue(detail.value)}
                placeholder="Assign a name"
              />
            ),
          },
        },
        {
          id: 'phone',
          header: 'Number',
          // Full E.164 ("+12065550100") rather than a truncated number, which
          // is useless for identifying a recipient.
          minWidth: 155,
          sortingField: 'phone',
          cell: (t) => t.phone,
        },
        {
          id: 'status',
          header: 'Status',
          minWidth: 120,
          sortingField: 'status',
          cell: (t) => <StatusIndicator type={statusType(t.status)}>{t.status || 'UNKNOWN'}</StatusIndicator>,
        },
        {
          id: 'opted_out',
          header: (
            <AsyncMetricHeader
              label="Opt-out"
              teaches="A recipient opts out by texting a keyword whose action is OPT_OUT — the built-in STOP, or any custom OPT_OUT keyword you register on the Settings tab. End User Messaging records the number on the Default opt-out list until they opt back in with an OPT_IN keyword such as UNSTOP (one must be registered), or an admin deletes the entry. Observed on a testing agent: the service then refuses every send to a listed number with DESTINATION_PHONE_NUMBER_OPTED_OUT. The bot reads this same list before it answers (cached for 30 seconds, fail-open) and skips a listed sender, so the channel adapter spends no model call on them (a photo they send is still converted and classified by media_convert); this sample keeps no opt-out list of its own. The Default list belongs to the account, not to one agent."
              docUrl="https://docs.aws.amazon.com/sms-voice/latest/userguide/keywords.html"
              reason="Read live from the account's Default opt-out list (DescribeOptedOutNumbers). A use case example triggered at an opted-out number fails with DESTINATION_PHONE_NUMBER_OPTED_OUT (observed on a testing agent)."
            />
          ),
          minWidth: 120,
          sortingField: 'opted_out',
          cell: (t) =>
            t.opted_out ? (
              <Badge color="red">Opted out</Badge>
            ) : (
              <StatusIndicator type="success">Subscribed</StatusIndicator>
            ),
        },
        {
          id: 'created',
          header: 'Registered',
          minWidth: 130,
          sortingField: 'created',
          cell: (t) => (t.created ? new Date(t.created).toLocaleDateString() : '—'),
        },
        {
          id: 'last_activity',
          header: 'Last activity',
          minWidth: 190,
          sortingField: 'last_activity',
          cell: (t) => (t.last_activity ? new Date(t.last_activity).toLocaleString() : '—'),
        },
        {
          id: 'sent',
          header: 'Sent',
          minWidth: 90,
          sortingField: 'messages_sent',
          cell: (t) => t.messages_sent ?? 0,
        },
        {
          id: 'delivered',
          header: (
            <AsyncMetricHeader
              label="Delivered"
              teaches="RCS confirms delivery from the recipient's device, not from the carrier network the way an SMS DLR does — which is also the billing basis: you are charged only for messages confirmed delivered to a device. The RCS_DELIVERED event carries a messageStatus of DELIVERED, PENDING, UNDELIVERABLE or REJECTED; read messageStatus for the outcome."
              docUrl="https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-events.html#rcs-events-delivery-status"
              reason="Per-recipient delivery comes from RCS_DELIVERED events. On a testing agent, delivery events appear once the agent is launched in a country. This was tested with the destination subscribed to RCS_ALL and the agent set to ALL. The RCSMessagesDelivered CloudWatch metric counts deliveries in aggregate."
            />
          ),
          // Wider than the plain counters: the header carries an ⓘ popover
          // trigger alongside the label as well as the sort icon.
          minWidth: 135,
          sortingField: 'delivered',
          cell: (t) => <Box color="text-body-secondary">{t.delivered ?? 0}</Box>,
        },
        {
          id: 'read',
          header: (
            <AsyncMetricHeader
              label="Read"
              teaches="Read rate is READ divided by DELIVERED — the two columns side by side. What you see here is the member's client reporting; SendRcsMessage carries message content only, so this sample sends no typing or read signals of its own (agent-initiated ones are documented as planned). The member's own typing is delivered inbound as RCS_TYPING; this sample records it as an indicator line in the conversation transcript when it arrives."
              docUrl="https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-events.html#rcs-events-read-receipts"
              reason="Read receipt (RCS_READ). On a testing agent, read events appear once the agent is launched in a country, as with Delivered. Even once launched, not every messaging client reports read status, so treat it as a relative engagement signal rather than an exact count."
            />
          ),
          minWidth: 105,
          sortingField: 'read',
          cell: (t) => <Box color="text-body-secondary">{t.read ?? 0}</Box>,
        },
        {
          id: 'failed',
          header: 'Failed',
          minWidth: 95,
          sortingField: 'failed',
          cell: (t) => (t.failed ? <Badge color="red">{t.failed}</Badge> : 0),
        },
        {
          id: 'fell_back_to_sms',
          header: (
            <AsyncMetricHeader
              label="Fell back to SMS"
              teaches="SendRcsMessage fallback is opt-in, not automatic: it fires only when you pass a FallbackConfiguration, and then only if the RCS leg fails or TimeToLive expires without a delivery confirmation. A count here means the member was still reached — as plain SMS, without the card. The same message also counts under Failed, because the RCS attempt genuinely did fail."
              docUrl="https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-fallback-per-message.html"
              reason="Comes from RCS_FALLEN_BACK_TO_SMS on the configuration set's event destination. On a testing agent these events appear once the agent is launched in a country, as with Delivered and Read. It also needs the stack deployed with an SMS origination identity, since a FallbackConfiguration without one is a ValidationException."
            />
          ),
          minWidth: 170,
          sortingField: 'fell_back_to_sms',
          cell: (t) => (t.fell_back_to_sms
            ? <Badge color="blue">{t.fell_back_to_sms}</Badge>
            : <Box color="text-body-secondary">0</Box>),
        },
        {
          id: 'received',
          header: 'Received',
          minWidth: 120,
          sortingField: 'messages_received',
          cell: (t) => t.messages_received ?? 0,
        },
        {
          id: 'remove',
          header: 'Remove',
          minWidth: 110,
          cell: (t) => (
            <Button
              variant="inline-link"
              iconName="remove"
              ariaLabel={`Remove ${t.name || t.phone}`}
              onClick={() => setPendingRemove(t)}
            >
              Remove
            </Button>
          ),
        },
      ]}
    />
    <InboundDeepLink keyword={brand?.deepLinkKeyword || ''} />
    <RemoveRecipientModal
      tester={pendingRemove}
      isTarget={!!pendingRemove && pendingRemove.phone === phone}
      busy={removing}
      onDismiss={() => setPendingRemove(null)}
      onConfirm={removeRecipient}
    />
    </SpaceBetween>
  );
}

// Removing a recipient is not a local edit — it calls
// DeleteVerifiedDestinationNumber, so the device loses the ability to receive
// anything from this agent until it accepts a fresh tester invitation. That is
// worth a confirmation step, and worth saying what does *not* get deleted.
function RemoveRecipientModal({
  tester,
  isTarget,
  busy,
  onDismiss,
  onConfirm,
}: {
  tester: Tester | null;
  isTarget: boolean;
  busy: boolean;
  onDismiss: () => void;
  onConfirm: () => void;
}) {
  return (
    <Modal
      visible={!!tester}
      onDismiss={onDismiss}
      header="Remove recipient"
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" disabled={busy} onClick={onDismiss}>Cancel</Button>
            <Button variant="primary" loading={busy} onClick={onConfirm}>Remove</Button>
          </SpaceBetween>
        </Box>
      }
    >
      {tester && (
        <SpaceBetween size="s">
          <Box>
            Unregister <b>{tester.name || 'this recipient'}</b> (
            <Box variant="code" display="inline">{tester.phone}</Box>) as a verified test device and
            free one of the agent's slots.
          </Box>
          <Box color="text-body-secondary" fontSize="body-s">
            The device stops being able to receive RCS from this agent. Adding it back sends a new
            tester invitation, which someone has to accept on the handset again — so this is not a
            one-click undo. The conversation transcript is kept (it is stored against a hash of the
            number, not the number), but the name is not: the thread will show as unnamed on
            Conversations until you re-add and rename.
          </Box>
          {isTarget && (
            <Alert type="warning">
              This is the current target recipient. Removing it clears the target, and you will need
              to select another before triggering a use case example.
            </Alert>
          )}
        </SpaceBetween>
      )}
    </Modal>
  );
}

// Renders a QR code for the agent's inbound deep link, so a registered
// recipient can start the conversation from their own phone instead of waiting
// for the operator to trigger a vignette.
//
// The link itself is generated in the console's Testing tab and pasted in (see
// config.ts). Both the "who can use this" caveat and the keyword check below
// exist because each is a way to get a QR code that scans fine and then does
// nothing.
function InboundDeepLink({ keyword }: { keyword: string }) {
  const [link, setLink] = useState(getDeepLink());
  const [draft, setDraft] = useState(getDeepLink());
  const [editing, setEditing] = useState(!getDeepLink());

  function save(url: string) {
    const trimmed = url.trim();
    setDeepLink(trimmed);
    setLink(trimmed);
    setDraft(trimmed);
    setEditing(!trimmed);
  }

  const body = deepLinkBody(link);
  const normalize = (s: string) => s.trim().toLowerCase().replace(/\s+/g, ' ');
  const bodyMatches = !!body && !!keyword && normalize(body) === normalize(keyword);

  return (
    <Container
      header={
        <Header
          variant="h3"
          description="Let a registered recipient start the conversation themselves — the phone sends first, and the channel adapter answers with the welcome message."
          actions={link && !editing && <Button onClick={() => setEditing(true)}>Change link</Button>}
        >
          Start from the phone — inbound deep link
        </Header>
      }
    >
      <SpaceBetween size="m">
        {/* Own measure: the page is as wide as the Recipients table needs,
            which is far wider than a readable line of prose. */}
        <Box color="text-body-secondary" fontSize="body-s">
          <div style={{ maxWidth: 900 }}>
          Generate the link in the AWS console under your RCS agent → <b>Testing</b> →{' '}
          <b>Inbound deep link</b>: set the pre-populated message body to{' '}
          <Box variant="code" display="inline">{keyword || '(loading…)'}</Box>, choose{' '}
          <b>Generate link</b>, and paste the resulting <Box variant="code" display="inline">sms:</Box>{' '}
          URL here. It's stored in this browser only. Note that a testing agent
          delivers only to <b>registered test devices</b>, so this QR code does nothing for a phone
          that hasn't accepted the tester invitation — it isn't a way to onboard a stranger's handset.
          </div>
        </Box>

        {editing || !link ? (
          <SpaceBetween size="xs">
            <FormField label="Inbound deep link URL">
              <Input
                value={draft}
                onChange={({ detail }) => setDraft(detail.value)}
                onKeyDown={({ detail }) => { if (detail.key === 'Enter') save(draft); }}
                placeholder="sms:…?body=Get%20started"
              />
            </FormField>
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="primary" disabled={!draft.trim()} onClick={() => save(draft)}>Save</Button>
              {link && <Button onClick={() => { setDraft(link); setEditing(false); }}>Cancel</Button>}
            </SpaceBetween>
          </SpaceBetween>
        ) : (
          <SpaceBetween size="m">
            {!bodyMatches && (
              <Alert
                type="warning"
                header="This link won't open the welcome message"
                action={
                  <Button onClick={() => save(withDeepLinkBody(link, keyword))}>
                    Set body to “{keyword}”
                  </Button>
                }
              >
                Its pre-populated body is{' '}
                {body ? <Box variant="code" display="inline">{body}</Box> : <i>empty</i>}, but the
                channel adapter opens the welcome message on{' '}
                <Box variant="code" display="inline">{keyword}</Box> (brand.md{' '}
                <Box variant="code" display="inline">deepLinkKeyword</Box>). Anything else falls
                through to the intent router — a plain greeting still reaches the welcome, but
                arbitrary text lands on the AI benefits assistant instead.
              </Alert>
            )}
            <SpaceBetween direction="horizontal" size="l" alignItems="center">
              <div style={{ background: '#fff', padding: 12, border: '1px solid #e4e9e9', borderRadius: 8 }}>
                <QRCodeSVG value={link} size={168} level="M" />
              </div>
              <SpaceBetween size="xs">
                <Box fontSize="body-s" color="text-body-secondary">
                  Scanning opens the messaging app with this message ready to send:
                </Box>
                <Box variant="code">{body || '(no pre-populated body)'}</Box>
                <Box fontSize="body-s" color="text-body-secondary" >
                  <span style={{ overflowWrap: 'anywhere' }}>{link}</span>
                </Box>
              </SpaceBetween>
            </SpaceBetween>
          </SpaceBetween>
        )}
      </SpaceBetween>
    </Container>
  );
}

// Column header for a metric that comes from an async platform event rather
// than from the synchronous SendRcsMessage result. A value that trails "Sent",
// or stays at zero on a testing agent, is expected, and the tooltip says which
// case applies. `teaches` explains what the RCS event behind the column means:
// the column is the only place in the dashboard where delivery semantics are
// visible, so it is the right place to say that RCS confirms delivery from the
// device itself and bills on that confirmation. `docUrl` links the AWS
// documentation for the event.
function AsyncMetricHeader({
  label,
  reason,
  teaches,
  docUrl,
}: {
  label: string;
  reason: string;
  teaches?: string;
  docUrl?: string;
}) {
  return (
    <SpaceBetween direction="horizontal" size="xxs" alignItems="center">
      <span>{label}</span>
      <Popover
        triggerType="text"
        size="medium"
        dismissAriaLabel="Close"
        content={
          <SpaceBetween size="xs">
            {teaches && <Box>{teaches}</Box>}
            <Box>{reason}</Box>
            {docUrl && (
              <Link href={docUrl} external externalIconAriaLabel="Opens in a new tab">
                AWS documentation
              </Link>
            )}
          </SpaceBetween>
        }
      >
        <Box color="text-body-secondary" fontSize="body-s">ⓘ</Box>
      </Popover>
    </SpaceBetween>
  );
}

function statusType(status: string): 'success' | 'warning' | 'error' | 'info' {
  if (status === 'VERIFIED') return 'success';
  if (status === 'PENDING') return 'warning';
  if (status === 'NOT_FOUND' || status === 'UNKNOWN') return 'error';
  return 'info';
}

function AddRecipient({
  onAdded,
  onError,
  atCap,
  cap,
}: {
  onAdded: () => void;
  onError: (e: string) => void;
  atCap: boolean;
  cap: number | null;
}) {
  const [phone, setPhone] = useState('');
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function add() {
    const normalized = normalizePhone(phone);
    if (!normalized) {
      setError('Enter a valid phone number, e.g. +12065550100');
      return;
    }
    setError('');
    setBusy(true);
    try {
      const r = await api.addTester(normalized, name.trim());
      // The handler reports failure in the body on an HTTP 200, so an unchecked
      // response is how a rejected add used to look like a successful one — the
      // form cleared and the recipient never appeared.
      if (r.error) {
        setError(
          r.reason === 'QUOTA_EXCEEDED'
            ? `All ${cap ?? 10} verified test device slots on this agent are taken. Remove a recipient first — this quota is not adjustable.`
            : r.error
        );
        return;
      }
      setPhone('');
      setName('');
      onAdded();
    } catch (e) {
      onError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Popover
      triggerType="custom"
      header="Add recipient"
      content={
        <SpaceBetween size="s">
          {atCap && (
            <Alert type="warning">
              All {cap} slots on this agent are in use. Remove a recipient before adding one.
            </Alert>
          )}
          <FormField label="Mobile number" errorText={error || undefined}>
            <Input
              value={phone}
              onChange={({ detail }) => setPhone(detail.value)}
              placeholder="+1XXXXXXXXXX"
            />
          </FormField>
          <FormField label="User name (optional)">
            <Input value={name} onChange={({ detail }) => setName(detail.value)} placeholder="e.g. Alex Rivera" />
          </FormField>
          <Box color="text-body-secondary" fontSize="body-s">
            Sends a verification invitation to this number. It must accept the invite before it can
            receive RCS messages.
          </Box>
          <Button variant="primary" loading={busy} disabled={atCap} onClick={add}>Add recipient</Button>
        </SpaceBetween>
      }
      dismissAriaLabel="Close"
    >
      <Button iconName="add-plus">Add recipient</Button>
    </Popover>
  );
}
