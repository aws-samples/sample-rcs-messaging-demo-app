import { useEffect, useState } from 'react';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Form from '@cloudscape-design/components/form';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Button from '@cloudscape-design/components/button';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import Alert from '@cloudscape-design/components/alert';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import KeyValuePairs from '@cloudscape-design/components/key-value-pairs';
import Link from '@cloudscape-design/components/link';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Select from '@cloudscape-design/components/select';
import Table from '@cloudscape-design/components/table';
import Badge from '@cloudscape-design/components/badge';
import Textarea from '@cloudscape-design/components/textarea';
import Modal from '@cloudscape-design/components/modal';
import { api, AgentIdentity, ApiError, Brand, Keyword, KeywordAction, Tester } from '../api';
import { getApiUrl, setApiUrl, getApiKey, setApiKey } from '../config';
import PhonePreviewPopover from '../components/PhonePreviewPopover';

export default function Settings({
  brand,
  identity,
  phone,
  onError,
}: {
  brand: Brand | null;
  identity: AgentIdentity | null;
  phone: string;
  onError: (e: string) => void;
}) {
  const [apiUrl, setApiUrlVal] = useState(getApiUrl());
  const [apiKey, setApiKeyVal] = useState(getApiKey());
  const [savedMsg, setSavedMsg] = useState('');

  // Operator diagnostics/experiments live here rather than in the Use Case
  // Examples list. Each sends the same way the Demo tab sends anything —
  // api.trigger(phone, "Start: <Trigger>") — so they share the target phone,
  // one "which trigger is in flight" busy flag, and a message line. The tester
  // list is only for the "name (phone)" label the status bar also shows.
  const [testers, setTesters] = useState<Tester[]>([]);
  const [diagBusy, setDiagBusy] = useState('');
  const [diagMsg, setDiagMsg] = useState('');

  useEffect(() => { api.getTesters().then(setTesters).catch(() => {}); }, [phone]);

  const currentLabel = (() => {
    if (!phone) return '';
    const t = testers.find((x) => x.phone === phone);
    return t?.name ? `${t.name} (${phone})` : phone;
  })();

  async function sendDiagnostic(trigger: string, label: string) {
    setDiagBusy(trigger);
    setDiagMsg('');
    try {
      await api.trigger(phone, trigger);
      setDiagMsg(`Sent ${label} to ${currentLabel}.`);
    } catch (e) {
      onError(String(e));
    } finally {
      setDiagBusy('');
    }
  }

  function saveApiUrl() {
    if (!apiUrl.trim()) return;
    setApiUrl(apiUrl.trim());
    setSavedMsg('API URL saved. Reload the page for it to take effect everywhere.');
  }
  function saveApiKey() {
    setApiKey(apiKey.trim());
    setSavedMsg('API key saved.');
  }

  return (
    <SpaceBetween size="l">
      <Header variant="h2">Settings</Header>

      {savedMsg && <Alert type="success" dismissible onDismiss={() => setSavedMsg('')}>{savedMsg}</Alert>}

      <LiveAgentIdentityPanel identity={identity} />

      <RcsRegistrationPanel brand={brand} />

      <BrandIdentityPanel />

      <Container header={<Header variant="h3">Deployment connection</Header>}>
        <SpaceBetween size="m">
          <KeyValuePairs
            columns={2}
            items={[
              {
                label: 'AWS account',
                value: identity?.awsAccountId
                  ? <Box variant="code">{identity.awsAccountId}</Box>
                  : '—',
              },
              {
                label: 'Region',
                value: identity?.region ? <Box variant="code">{identity.region}</Box> : '—',
              },
            ]}
          />
          <Box color="text-body-secondary" fontSize="body-s">
            The account and Region the API below runs in — where the RCS agent, Lambdas, table and
            bucket are deployed. Shown once a valid API key is set and the page has been reloaded.
            A dash means the key is missing or wrong, or the deployed backend is an older build that
            does not return this field (redeploy to update it).
          </Box>
          <Box color="text-body-secondary" fontSize="body-s">
            The base URL of your deployed AnyHealth API — the <Box variant="code" display="inline">ApiUrl</Box>{' '}
            output from <Box variant="code" display="inline">cdk deploy</Box>. A URL saved here is used only
            when <Box variant="code" display="inline">VITE_API_URL</Box> was not set in{' '}
            <Box variant="code" display="inline">web/.env</Box>; if it was, that value wins.
          </Box>
          <Form>
            <FormField label="API URL">
              <Input
                value={apiUrl}
                onChange={({ detail }) => setApiUrlVal(detail.value)}
                placeholder="https://xxxx.execute-api.us-east-1.amazonaws.com"
              />
            </FormField>
          </Form>
          <Button variant="primary" onClick={saveApiUrl}>Save API URL</Button>
        </SpaceBetween>
      </Container>

      <Container header={<Header variant="h3">API key</Header>}>
        <SpaceBetween size="m">
          <Box color="text-body-secondary" fontSize="body-s">
            Shared secret required for anything that sends messages, changes demo data, <em>or
            returns recipient data</em>. That means sending use case examples, replying as a care advocate,
            taking over/releasing conversations, adding recipients and resetting demo data — and also
            loading the Recipients list, conversation transcripts, received media, and the account's
            RCS spend limit. Without it those tabs will show an error rather than data. Retrieve it
            with{' '}
            <Box variant="code" display="inline">
              aws secretsmanager get-secret-value --secret-id &lt;prefix&gt;-demo-api-key --query
              SecretString --output text --region &lt;deploy region&gt;
            </Box>
            {' '}— the{' '}
            <Box variant="code" display="inline">--region</Box> is required, because the secret is in
            the region you deployed to rather than your CLI default.
          </Box>
          <Form>
            <FormField label="API key">
              <Input
                value={apiKey}
                onChange={({ detail }) => setApiKeyVal(detail.value)}
                type="password"
                placeholder="API key"
              />
            </FormField>
          </Form>
          <Button variant="primary" onClick={saveApiKey}>Save API key</Button>
        </SpaceBetween>
      </Container>

      <CustomKeywordsPanel />

      <Container header={<Header variant="h3">Diagnostics &amp; experiments</Header>}>
        <SpaceBetween size="l">
          <Box color="text-body-secondary" fontSize="body-s">
            Operator tools, not customer-facing examples, so they live here rather than in the Use
            Case Examples list. Each sends to the current target device; set one on the Recipients tab
            to enable the buttons.
          </Box>
          {diagMsg && <Alert type="success" dismissible onDismiss={() => setDiagMsg('')}>{diagMsg}</Alert>}

          <div>
            <Box variant="strong">Camera &amp; Mic Probe</Box>
            <Box color="text-body-secondary" fontSize="body-s" margin={{ bottom: 'xs' }}>
              Opens one page three ways — an RCS webview at{' '}
              <Box variant="code" display="inline">FULL</Box> and{' '}
              <Box variant="code" display="inline">HALF</Box> height, and the device's own browser —
              and reports <Box variant="code" display="inline">isSecureContext</Box>, whether{' '}
              <Box variant="code" display="inline">getUserMedia</Box> exists, and the exact{' '}
              <Box variant="code" display="inline">DOMException</Box> when the camera or mic is
              blocked. Answers whether an RCS webview can reach the camera and microphone on a given
              handset — the question the Video Visit example depends on.
            </Box>
            <SpaceBetween direction="horizontal" size="s" alignItems="center">
              <Button
                disabled={!phone}
                loading={diagBusy === 'Start: Media_Probe'}
                onClick={() => sendDiagnostic('Start: Media_Probe', 'the Camera & Mic Probe')}
              >
                {phone ? `Send to ${currentLabel}` : 'Send to target device'}
              </Button>
              <PhonePreviewPopover vignetteId="media_probe" brand={brand} identity={identity} />
            </SpaceBetween>
          </div>

          <div>
            <Box variant="strong">IVS iCasino Webview (experiment)</Box>
            <Box color="text-body-secondary" fontSize="body-s" margin={{ bottom: 'xs' }}>
              An off-theme experiment: can an RCS in-conversation webview host a live{' '}
              <Link href="https://icasino.ivsdemos.com/" external>Amazon IVS iCasino</Link> video
              stream? It sends the external URL as a full-height webview plus a
              device-browser control. RCS cards can't embed a live page — this opens the site as a
              top-level webview, which also sidesteps the site's{' '}
              <Box variant="code" display="inline">X-Frame-Options: SAMEORIGIN</Box> (it refuses to be
              iframed, but a webview opens it as a top-level document). Open it on your device to
              see how IVS low-latency video plays in the webview.
            </Box>
            <SpaceBetween direction="horizontal" size="s" alignItems="center">
              <Button
                disabled={!phone}
                loading={diagBusy === 'Start: IVS_Experiment'}
                onClick={() => sendDiagnostic('Start: IVS_Experiment', 'the IVS iCasino experiment')}
              >
                {phone ? `Send to ${currentLabel}` : 'Send to target device'}
              </Button>
              <PhonePreviewPopover vignetteId="ivs_experiment" brand={brand} identity={identity} />
            </SpaceBetween>
          </div>

          <div>
            <Box variant="strong">IVS Interactive Fitness Webview (experiment)</Box>
            <Box color="text-body-secondary" fontSize="body-s" margin={{ bottom: 'xs' }}>
              The same experiment against a different Amazon IVS surface: the hosted{' '}
              <Link href="https://fitness.ivsdemos.com/" external>Interactive Fitness</Link> demo —
              a live low-latency stream with a leaderboard and user interactions. Sends the external
              URL as a full-height webview plus a device-browser control. Tests whether the
              fitness stream and its interactivity survive an RCS webview.
            </Box>
            <SpaceBetween direction="horizontal" size="s" alignItems="center">
              <Button
                disabled={!phone}
                loading={diagBusy === 'Start: IVS_Fitness'}
                onClick={() => sendDiagnostic('Start: IVS_Fitness', 'the IVS Interactive Fitness experiment')}
              >
                {phone ? `Send to ${currentLabel}` : 'Send to target device'}
              </Button>
              <PhonePreviewPopover vignetteId="ivs_fitness" brand={brand} identity={identity} />
            </SpaceBetween>
          </div>
        </SpaceBetween>
      </Container>
    </SpaceBetween>
  );
}

// Custom keywords registered on the RCS agent (PutKeyword / DescribeKeywords /
// DeleteKeyword). When a recipient texts one, End User Messaging sends the
// configured response and applies the action, and also publishes the message to
// the two-way topic with messageKeyword set (observed with an UNSTOP OPT_IN
// keyword on a testing agent). So the message still reaches this stack's
// Lambda, which treats a message that begins with its messageKeyword as already
// answered: it sends no reply and calls no model (_screen_freetext in
// channel_adapter.py), so a custom keyword is answered once. The adapter treats
// a message as a keyword reply only when its text begins with that keyword. That
// is a different mechanism from the app-side greeting router in
// channel_adapter.py, which only sees messages the service forwards inbound and
// decides which flow to open.
//
// HELP and STOP are the service's built-in keywords: always present, and
// answered with the service's default text ("Default Help Message", "Default
// Stop Message") until real text is registered. They arrive without a
// messageKeyword. This dashboard's API does not edit or delete them, so they are
// shown read-only; the deploy registers their text, or it is set from the CLI
// (AGENTS.md, "Register the keyword replies"). A recipient who
// texted STOP can opt back in by text only if an OPT_IN keyword is registered
// here. Self-fetching, like Recipients — it holds the API key requirement
// itself rather than being passed data down.
const KEYWORD_ACTION_OPTIONS: { value: KeywordAction; label: string; description: string }[] = [
  { value: 'AUTOMATIC_RESPONSE', label: 'Automatic response', description: 'Reply with the message; no opt-in/out change.' },
  { value: 'OPT_IN', label: 'Opt in', description: 'Subscribe the recipient, then reply with the message.' },
  { value: 'OPT_OUT', label: 'Opt out', description: 'Unsubscribe the recipient, then reply with the message.' },
];

function actionLabel(action: string): string {
  return KEYWORD_ACTION_OPTIONS.find((o) => o.value === action)?.label ?? action;
}

function actionBadgeColor(action: string): 'green' | 'red' | 'grey' {
  if (action === 'OPT_IN') return 'green';
  if (action === 'OPT_OUT') return 'red';
  return 'grey';
}

// The text shown when a keyword write is rejected. The server's own short message
// when it sent one (dashboard_handler.ApiError); a rejected API key is named as
// such, because the gateway answers that before the handler runs and sends no
// message; anything else gets a generic line rather than the raw response body.
function keywordFailure(e: unknown, verb: 'save' | 'delete'): string {
  if (e instanceof ApiError) {
    if (e.userMessage) return e.userMessage;
    if (e.status === 401 || e.status === 403) {
      return 'The API key was rejected. Check the key above and try again.';
    }
    return `Could not ${verb} the keyword (HTTP ${e.status}).`;
  }
  // Setup problems req() raises itself ("API URL not configured", the missing-key
  // prompt) and network failures; both read fine as they are.
  return e instanceof Error ? e.message : `Could not ${verb} the keyword.`;
}

function CustomKeywordsPanel() {
  const [keywords, setKeywords] = useState<Keyword[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [keyword, setKeyword] = useState('');
  const [message, setMessage] = useState('');
  const [action, setAction] = useState<KeywordAction>('AUTOMATIC_RESPONSE');
  const [formError, setFormError] = useState('');
  const [savedMsg, setSavedMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<Keyword | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState('');

  const load = () => {
    setLoading(true);
    return api.getKeywords()
      .then((r) => {
        setKeywords(r.keywords || []);
        // A permission/config problem comes back as an `error` on an HTTP 200,
        // not a thrown non-2xx — surface it inline rather than as a blank list.
        setLoadError(r.error || '');
      })
      .catch((e) => setLoadError(String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  async function submit() {
    if (!keyword.trim()) { setFormError('Enter a keyword.'); return; }
    if (!message.trim()) { setFormError('Enter a response message.'); return; }
    setFormError('');
    setSavedMsg('');
    setBusy(true);
    try {
      const r = await api.createKeyword(keyword.trim(), message.trim(), action);
      if (r.error) { setFormError(r.error); return; }
      setSavedMsg(`Saved keyword "${r.keyword}".`);
      setKeyword('');
      setMessage('');
      setAction('AUTOMATIC_RESPONSE');
      await load();
    } catch (e) {
      // Shown under the form, where the operator just clicked Save; the typed
      // keyword and message stay put so they can fix them and retry.
      setFormError(keywordFailure(e, 'save'));
    } finally {
      setBusy(false);
    }
  }

  async function confirmDelete() {
    const k = pendingDelete;
    if (!k) return;
    setDeleting(true);
    setDeleteError('');
    setSavedMsg('');
    try {
      const r = await api.deleteKeyword(k.keyword);
      if (r.error) { setDeleteError(r.error); return; }
      setSavedMsg(`Deleted keyword "${k.keyword}".`);
      setPendingDelete(null);
      await load();
    } catch (e) {
      // Shown inside the dialog, which stays open, so the failure is in front
      // of the operator rather than behind a closed modal.
      setDeleteError(keywordFailure(e, 'delete'));
    } finally {
      setDeleting(false);
    }
  }

  function askDelete(k: Keyword | null) {
    setDeleteError('');
    setPendingDelete(k);
  }

  return (
    <Container
      header={
        <Header
          variant="h3"
          counter={`(${keywords.length})`}
          description="Keywords registered on the RCS agent are answered by AWS End User Messaging, which sends the response and applies the action. The message also reaches this demo's Lambda with messageKeyword set; the demo sends no reply of its own."
        >
          Custom keywords
        </Header>
      }
    >
      <SpaceBetween size="l">
        <Box color="text-body-secondary" fontSize="body-s">
          <div style={{ maxWidth: 900 }}>
            This is distinct from the demo's in-app greeting router: these keywords are configured on
            the agent itself, so the reply and the opt-in/out change happen at the service. An{' '}
            <Box variant="code" display="inline">OPT_OUT</Box> keyword records the sender as opted out
            at the service; the Recipients tab shows numbers on the Default opt-out list. Observed on
            a testing agent, the service then refuses every send to that number. The bot checks that
            list before it answers (cached for 30 seconds, and it fails open), so an opted-out sender
            gets no replies and costs the channel adapter no model call (a photo they send is still
            converted and classified by media_convert), but this sample keeps no opt-out list of its
            own, so keep yours.{' '}
            <Box variant="code" display="inline">OPT_IN</Box> is the matching opt-in, and a member who
            texted STOP can come back by text only if one is registered. Add{' '}
            <Box variant="code" display="inline">UNSTOP</Box> as an opt-in, as the deploy does.{' '}
            <Box variant="code" display="inline">HELP</Box> and{' '}
            <Box variant="code" display="inline">STOP</Box> are the service's built-ins and shown
            read-only here. The deploy registers their text from brand.md (or you set it by hand with{' '}
            <Box variant="code" display="inline">put-keyword</Box>, see AGENTS.md); until real text
            exists, the service replies with "Default Help Message" and "Default Stop Message".{' '}
            Do not register the demo's own greeting words ("hi", "hello", "start", "demo") or the
            deep-link keyword: the service's fixed reply would replace the welcome card.
          </div>
        </Box>

        {loadError && (
          <Alert type="error" header="Couldn't load keywords">
            {loadError}
            {' '}This read needs the API key — set it above and reload if it isn't set.
          </Alert>
        )}
        {savedMsg && <Alert type="success" dismissible onDismiss={() => setSavedMsg('')}>{savedMsg}</Alert>}

        <Table<Keyword>
          variant="embedded"
          loading={loading}
          loadingText="Loading keywords…"
          items={keywords}
          trackBy="keyword"
          empty={
            <Box textAlign="center" color="text-body-secondary" padding="m">
              No keywords registered yet. Add one below.
            </Box>
          }
          columnDefinitions={[
            {
              id: 'keyword',
              header: 'Keyword',
              minWidth: 140,
              cell: (k) => (
                <SpaceBetween direction="horizontal" size="xs" alignItems="center">
                  <Box variant="code">{k.keyword}</Box>
                  {k.reserved && <Badge color="grey">reserved</Badge>}
                </SpaceBetween>
              ),
            },
            {
              id: 'action',
              header: 'Action',
              minWidth: 150,
              cell: (k) => <Badge color={actionBadgeColor(k.action)}>{actionLabel(k.action)}</Badge>,
            },
            {
              id: 'message',
              header: 'Response message',
              cell: (k) => k.message || <Box color="text-body-secondary">—</Box>,
            },
            {
              id: 'remove',
              header: '',
              width: 110,
              cell: (k) =>
                k.reserved ? (
                  <Box color="text-body-secondary" fontSize="body-s">—</Box>
                ) : (
                  <Button
                    variant="inline-link"
                    iconName="remove"
                    ariaLabel={`Delete keyword ${k.keyword}`}
                    onClick={() => askDelete(k)}
                  >
                    Delete
                  </Button>
                ),
            },
          ]}
        />

        <div>
          <Box variant="h4" padding={{ bottom: 'xs' }}>Add or update a keyword</Box>
          <Box color="text-body-secondary" fontSize="body-s" margin={{ bottom: 's' }}>
            Registering an existing keyword replaces its response and action.
          </Box>
          <Form>
            <SpaceBetween size="m">
              <ColumnLayout columns={2}>
                <FormField label="Keyword" description="What the recipient texts (case-insensitive).">
                  <Input
                    value={keyword}
                    onChange={({ detail }) => setKeyword(detail.value)}
                    placeholder="e.g. HOURS"
                  />
                </FormField>
                <FormField label="Action" description="What End User Messaging does when the keyword arrives.">
                  <Select
                    selectedOption={KEYWORD_ACTION_OPTIONS.find((o) => o.value === action) ?? null}
                    onChange={({ detail }) => setAction(detail.selectedOption.value as KeywordAction)}
                    options={KEYWORD_ACTION_OPTIONS}
                  />
                </FormField>
              </ColumnLayout>
              <FormField
                label="Response message"
                errorText={formError || undefined}
                description="The reply the service sends back to the recipient."
              >
                <Textarea
                  value={message}
                  onChange={({ detail }) => setMessage(detail.value)}
                  placeholder="e.g. Our clinic is open Mon-Fri, 8am-6pm. Reply STOP to opt out."
                  rows={3}
                />
              </FormField>
              <Button variant="primary" loading={busy} onClick={submit}>Save keyword</Button>
            </SpaceBetween>
          </Form>
        </div>
      </SpaceBetween>

      <Modal
        visible={!!pendingDelete}
        onDismiss={() => askDelete(null)}
        header="Delete keyword"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" disabled={deleting} onClick={() => askDelete(null)}>Cancel</Button>
              <Button variant="primary" loading={deleting} onClick={confirmDelete}>Delete</Button>
            </SpaceBetween>
          </Box>
        }
      >
        {pendingDelete && (
          <SpaceBetween size="s">
            <Box>
              Remove the keyword <Box variant="code" display="inline">{pendingDelete.keyword}</Box> from
              the agent? Recipients who text it will no longer get an automatic response.
            </Box>
            {deleteError && <Alert type="error" header="Couldn't delete the keyword">{deleteError}</Alert>}
          </SpaceBetween>
        )}
      </Modal>
    </Container>
  );
}

// The identity read live off the AWS registration — as opposed to the panel
// below, which shows what content/brand.md *says* was submitted. Both are worth
// showing because they routinely disagree: brand.md is the demo's fictional
// AnyHealth, while the agent doing the sending carries whatever this AWS account
// actually registered. The live values are the ones on the handset, and are what
// the device previews use.
//
// Retrieval is three calls (see
// lambda/dashboard_handler.get_agent_identity): DescribeRcsAgents gives the
// testing agent's RegistrationId, DescribeRegistrationFieldValues gives the
// agentDetails.* fields with the images as attachment ids, and
// DescribeRegistrationAttachments turns those ids into presigned URLs.
function LiveAgentIdentityPanel({ identity }: { identity: AgentIdentity | null }) {
  const header = (
    <Header
      variant="h3"
      description="Read from this AWS account's RCS registration — the brand a handset actually renders, and the source of the logo shown in the device previews."
    >
      Live agent identity
    </Header>
  );

  if (!identity || identity.source !== 'live') {
    return (
      <Container header={header}>
        <SpaceBetween size="s">
          <StatusIndicator type="info">Not readable — device previews fall back to content/brand.md</StatusIndicator>
          <Box color="text-body-secondary" fontSize="body-s">
            {identity?.error
              ? identity.error
              : 'This read is authenticated, so it needs the API key below. Set it and reload.'}
          </Box>
        </SpaceBetween>
      </Container>
    );
  }

  return (
    <Container header={header}>
      <SpaceBetween size="l">
        <KeyValuePairs
          columns={3}
          items={[
            { label: 'Sender display name', value: identity.senderDisplayName || '—' },
            { label: 'Brand name', value: identity.brandName || '—' },
            { label: 'Service name', value: identity.serviceName || '—' },
            { label: 'Use case', value: identity.useCase || '—' },
            { label: 'Billing category', value: identity.billingCategory || '—' },
            {
              label: 'Brand color',
              value: identity.accentColor ? (
                <span>
                  <span
                    style={{
                      display: 'inline-block',
                      width: 12,
                      height: 12,
                      borderRadius: 3,
                      background: identity.accentColor,
                      marginRight: 6,
                      verticalAlign: 'middle',
                    }}
                  />
                  {identity.accentColor}
                </span>
              ) : '—',
            },
            { label: 'Agent status', value: identity.agentStatus || '—' },
            { label: 'Testing agent status', value: identity.testingAgentStatus || '—' },
            { label: 'Registration', value: identity.registrationId || '—' },
            {
              // Deploy-time only: there is deliberately no control for this,
              // because it is a CDK context value baked into a Lambda env var
              // rather than anything the running stack can change. Shown here
              // because Settings is where someone looks to find out whether
              // fallback is on.
              label: 'SMS fallback',
              value: identity.smsFallbackNumber ? (
                <StatusIndicator type="success">
                  Active — {identity.smsFallbackNumber}
                </StatusIndicator>
              ) : (
                <StatusIndicator type="info">
                  Not configured — redeploy with -c smsFallbackNumber=+1…
                </StatusIndicator>
              ),
            },
          ]}
        />

        {!identity.smsFallbackNumber && (
          <Box color="text-body-secondary" fontSize="body-s">
            Use case example entry messages carry an SMS fallback body, but without an SMS-capable
            origination identity no <code>FallbackConfiguration</code> is attached, so the
            Fell back to SMS column on Recipients can never leave zero. A demo deployment often has no
            SMS-capable number configured, so this is an expected state rather than a
            misconfiguration — the RCS path is unaffected.
          </Box>
        )}

        {identity.agentDescription && (
          <Box color="text-body-secondary" fontSize="body-s">{identity.agentDescription}</Box>
        )}

        {identity.contacts && identity.contacts.length > 0 && (
          <div>
            <Box variant="h4" padding={{ bottom: 'xs' }}>Registered contact actions</Box>
            {/* These are real, operator-owned details rather than the fictional
                ones in content/brand.md, which is why /api/agent-identity is an
                authenticated route. */}
            <KeyValuePairs
              columns={3}
              items={identity.contacts.map((c) => ({ label: `${c.kind} — ${c.label}`, value: c.value }))}
            />
          </div>
        )}

        <div>
          <Box variant="h4" padding={{ bottom: 'xs' }}>Registered assets</Box>
          <ColumnLayout columns={2}>
            <SpaceBetween size="xs">
              <Box fontWeight="bold" fontSize="body-s">Logo (as uploaded to AWS)</Box>
              {identity.logoUrl ? (
                <img
                  src={identity.logoUrl}
                  alt="Registered agent logo"
                  style={{ width: 112, height: 112, borderRadius: '50%', objectFit: 'contain', background: '#fff' }}
                />
              ) : (
                <Box color="text-body-secondary" fontSize="body-s">No logo on the registration.</Box>
              )}
            </SpaceBetween>
            <SpaceBetween size="xs">
              <Box fontWeight="bold" fontSize="body-s">Banner (as uploaded to AWS)</Box>
              {identity.bannerUrl ? (
                <img
                  src={identity.bannerUrl}
                  alt="Registered agent banner"
                  style={{ width: '100%', maxWidth: 360, borderRadius: 8, display: 'block' }}
                />
              ) : (
                <Box color="text-body-secondary" fontSize="body-s">No banner on the registration.</Box>
              )}
            </SpaceBetween>
          </ColumnLayout>
          {/* Worth saying out loud: these are not the files in media/. If they
              differ, the handset follows these, and changing them means a
              registration update, not a redeploy. */}
          <Box color="text-body-secondary" fontSize="body-s" padding={{ top: 's' }}>
            These images come from the registration on AWS, not from{' '}
            <Box variant="code" display="inline">media/</Box>. If they differ from the panel below,
            the handset follows these — replacing them is a registration change, and some
            registration fields cannot be changed once submitted.
          </Box>
        </div>
      </SpaceBetween>
    </Container>
  );
}

// What was submitted on the RCS agent registration, and the two image assets
// that go with it. Brand identity is otherwise an invisible setup step: it's
// entered once in the console, never appears in the dashboard, and yet it is
// the first thing every recipient sees. Showing it here also makes
// senderDisplayName concrete -- it is the string on the handset, while the
// console's "friendly name" is only a tag.
function RcsRegistrationPanel({ brand }: { brand: Brand | null }) {
  const reg = brand?.registration;
  if (!reg) {
    return (
      <Container header={<Header variant="h3">RCS agent registration</Header>}>
        <Box color="text-body-secondary" fontSize="body-s">
          Not available. Either the API URL isn't set yet, or this deployment's Lambda predates the
          registration panel — redeploy to populate it from{' '}
          <Box variant="code" display="inline">content/brand.md</Box>.
        </Box>
      </Container>
    );
  }

  return (
    <Container
      header={
        <Header
          variant="h3"
          description="The identity this repo declares for the RCS testing registration, from content/brand.md and media/. Edit those and redeploy to change what's shown here — but note this is the intended registration, not necessarily the live one above."
        >
          Declared brand (content/brand.md)
        </Header>
      }
    >
      <SpaceBetween size="l">
        <KeyValuePairs
          columns={3}
          items={[
            {
              label: 'Sender display name',
              value: reg.senderDisplayName || '—',
              // senderDisplayName is the string shown on the handset.
              info: <Box fontSize="body-s">Shown on the handset (≤40 chars). Not the console friendly name, which is only a tag.</Box>,
            },
            { label: 'Service name', value: reg.serviceName || '—' },
            { label: 'Use case', value: reg.useCase || '—' },
            { label: 'Agent description', value: reg.agentDescription || '—' },
            { label: 'Average monthly frequency', value: reg.averageMonthlyRcsFrequency || '—' },
            { label: 'Monthly RCS volume', value: reg.monthlyRcsVolume || '—' },
            {
              label: 'Privacy policy',
              value: reg.privacyPolicyUrl ? (
                <Link href={reg.privacyPolicyUrl} external>{reg.privacyPolicyUrl}</Link>
              ) : '—',
            },
            {
              label: 'Terms and conditions',
              value: reg.termsAndConditionsUrl ? (
                <Link href={reg.termsAndConditionsUrl} external>{reg.termsAndConditionsUrl}</Link>
              ) : '—',
            },
          ]}
        />

        {reg.contacts.length > 0 && (
          <div>
            <Box variant="h4" padding={{ bottom: 'xs' }}>Contact actions</Box>
            <Box color="text-body-secondary" fontSize="body-s" padding={{ bottom: 's' }}>
              These render as buttons on the agent profile — the sheet a recipient reaches by tapping
              the agent name in the thread. The label is the caption; the value is what the button does.
            </Box>
            <KeyValuePairs
              columns={3}
              items={reg.contacts.map((c) => ({
                label: `${c.kind} — ${c.label}`,
                value: c.value,
              }))}
            />
          </div>
        )}

        <div>
          <Box variant="h4" padding={{ bottom: 'xs' }}>Brand assets</Box>
          <ColumnLayout columns={2}>
            <SpaceBetween size="xs">
              <Box fontWeight="bold" fontSize="body-s">Logo — 224×224 PNG with alpha, ≤50 KB</Box>
              {reg.logoImage ? (
                <img
                  src={api.mediaUrl(reg.logoImage)}
                  alt="Agent logo"
                  style={{ width: 112, height: 112, borderRadius: '50%', objectFit: 'cover', background: '#fff' }}
                />
              ) : (
                <Box color="text-body-secondary" fontSize="body-s">Not set.</Box>
              )}
              <Box color="text-body-secondary" fontSize="body-s">
                Rendered circular on both platforms, in the thread and on the agent profile — so a
                square logo loses its corners. Transparency is required.
              </Box>
            </SpaceBetween>
            <SpaceBetween size="xs">
              <Box fontWeight="bold" fontSize="body-s">Banner — 1440×448 PNG/JPEG, ≤200 KB</Box>
              {reg.bannerImage ? (
                <img
                  src={api.mediaUrl(reg.bannerImage)}
                  alt="Agent banner"
                  style={{ width: '100%', maxWidth: 360, borderRadius: 8, display: 'block' }}
                />
              ) : (
                <Box color="text-body-secondary" fontSize="body-s">Not set.</Box>
              )}
              {/* The Android-only display is documented ("only displayed on
                  Android devices", Managing RCS agents). The logo overlaying
                  the banner's bottom-center was observed on hardware. */}
              <Box color="text-body-secondary" fontSize="body-s">
                Android only: it appears at the top of the agent profile and nowhere on iOS. The
                circular logo is overlaid on its <strong>bottom-center</strong>, so keep that third
                clear — a centered wordmark gets covered.
              </Box>
            </SpaceBetween>
          </ColumnLayout>
        </div>
      </SpaceBetween>
    </Container>
  );
}

// Education, not configuration. A testing agent does not show the verified
// badge, so a demo built on one does not show that trust signal. Every claim
// below was observed on two handsets against one testing agent (2026-09-14).
function BrandIdentityPanel() {
  return (
    <Container
      header={
        <Header variant="h3" description="What recipients actually see, and how that changes between a testing agent and a launched one.">
          Brand identity: testing vs production
        </Header>
      }
    >
      <SpaceBetween size="m">
        <Alert type="info" header="A testing agent shows your brand, but not a verified badge">
          On a testing registration, the logo and display name render in the thread on both Android
          and iOS — so branding is real from day one. On the testing agent used here, <strong>no
          verified badge glyph appeared on either platform</strong>, in the thread or on the agent
          profile. Each platform shows text instead: iOS shows "Verified by Google" on the agent
          info sheet, and Android inserts "This is an RCS for Business chat." at the top of the
          thread.
        </Alert>

        <ColumnLayout columns={2}>
          <SpaceBetween size="xs">
            <Box variant="h4">Testing agent — what this demo runs on</Box>
            <Box fontSize="body-s" color="text-body-secondary">
              A sandbox RCS for Business ID with no carrier approval. Delivers only to verified
              destination numbers (max 10 per agent, not adjustable). Logo, display name,
              description, banner and contact actions all render as configured, which is why the
              registration panel above is worth reading before a demo. No verified badge. Agent{' '}
              <Box variant="code" display="inline">Status: TESTING</Box>.
            </Box>
          </SpaceBetween>
          <SpaceBetween size="xs">
            <Box variant="h4">Launched agent — production</Box>
            <Box fontSize="body-s" color="text-body-secondary">
              One country launch registration per country, each carrier-reviewed. Delivers to any
              RCS-capable number in an approved country; one approved carrier is enough to start
              sending there. Agent moves to{' '}
              <Box variant="code" display="inline">PARTIAL</Box>, then{' '}
              <Box variant="code" display="inline">ACTIVE</Box>. Brand assets should be final before
              submitting — several cannot be changed afterwards.
            </Box>
          </SpaceBetween>
        </ColumnLayout>

        <div>
          <Box variant="h4" padding={{ bottom: 'xs' }}>Where each element renders (one testing agent, on hardware)</Box>
          <Box color="text-body-secondary" fontSize="body-s">
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              <li><strong>Logo and display name</strong> — in-thread on both platforms.</li>
              <li><strong>Agent description</strong> — agent profile / info sheet only, never in the thread.</li>
              <li><strong>Banner</strong> — Android agent profile only; absent from the iOS info sheet.</li>
              <li><strong>Contact actions</strong> — agent profile / info sheet on both platforms.</li>
              <li><strong>"Verified by Google"</strong> — iOS info sheet only.</li>
              <li><strong>"This is an RCS for Business chat."</strong> — top of the Android thread, not configurable.</li>
              <li><strong>Verified badge glyph</strong> — nowhere, on either platform.</li>
            </ul>
          </Box>
        </div>

        <Box color="text-body-secondary" fontSize="body-s">
          Read-receipt caveat while you're testing: on iOS, <strong>Send Read Receipts</strong> is a
          per-recipient setting that is off by default, so a Read column at zero can reflect the
          recipient's toggle rather than the event wiring. On a testing agent, read events appear
          once the agent is launched in a country.
        </Box>
      </SpaceBetween>
    </Container>
  );
}
