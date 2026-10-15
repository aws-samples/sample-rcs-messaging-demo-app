import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import SpaceBetween from '@cloudscape-design/components/space-between';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Box from '@cloudscape-design/components/box';
import Link from '@cloudscape-design/components/link';
import { api, Brand, RcsRegistry, Tester } from '../api';

export default function Guide({ brand, phone }: { brand: Brand | null; phone: string }) {
  const name = brand?.brandName || 'AnyHealth';
  const [testers, setTesters] = useState<Tester[]>([]);
  // The RCS feature registry (content/rcs-features.json), served by the API.
  // Everything in section 7 and every number quoted in this page comes from it,
  // so a limit change is a JSON edit rather than a copy edit here.
  const [registry, setRegistry] = useState<RcsRegistry | null>(null);

  useEffect(() => { api.getTesters().then(setTesters).catch(() => {}); }, [phone]);
  useEffect(() => { api.getRcsFeatures().then(setRegistry).catch(() => {}); }, []);

  // Only the service's own features, not this demo's patterns: a builder
  // evaluating RCS needs to know which is which.
  const apiFeatures = (registry?.features ?? []).filter((f) => f.kind === 'rcs-api');
  const limits = registry?.limits ?? [];
  const limitValue = (key: string) => limits.find((l) => l.key === key)?.value;
  const testDeviceLimit = limitValue('testDevicesPerAgent');
  const countryLimit = limitValue('supportedCountries');

  const current = testers.find((t) => t.phone === phone);
  const targetLabel = phone ? (current?.name ? `${current.name} (${phone})` : phone) : 'none selected';

  return (
    // Fills the window instead of sitting in a 780px column with half the page
    // empty beside it: the steps run two abreast, so the page gets wider rather
    // than longer as the window does.
    <div>
      <SpaceBetween size="m">
        <Box variant="h2">How this demo works</Box>
        <Box color="text-body-secondary">
          {name} is a fictitious healthcare brand demonstrating AWS End User Messaging RCS. A message
          from a registered recipient reaches an RCS agent, which publishes to SNS. A Lambda routes the
          message to a deterministic flow, the AI assistant, the store, or a live human — then replies
          with rich RCS content.
        </Box>

        {/* Two columns, so the steps read 1 2 / 3 4 / 5 6 and step 7 gets the full
            width below. Deliberately a fixed count rather than auto-fitting as many
            tracks as the window allows: these are numbered steps, and three or four
            columns makes the reading order a puzzle. ColumnLayout collapses to one
            column on a narrow window by itself. */}
        <ColumnLayout columns={2}>
          <Section title="1 · Register devices to receive RCS messages">
            The Recipients tab is where you invite (and remove) mobile devices — up to{' '}
            <b>{testDeviceLimit ?? 10} per RCS agent</b>, a quota that cannot be increased — to test
            with this app. Add a phone number, then accept the invitation on that phone; status must
            read <b>VERIFIED</b> before it can receive messages. The invitation is an RBM Tester
            Management message with <b>Make me a tester</b> buttons, not a numeric code, and on
            iOS 18+ it often arrives under <b>Unknown Senders</b>.
          </Section>
          <Section title="2 · Set the device target">
            Pick which registered recipient you're demoing to from either the Recipients tab (tap{' '}
            <b>Select</b> on that row — the current target shows <b>In Use</b> instead) or the “Change
            Target #” control in the status bar, which appears at the top of every tab. Only one device
            can be targeted at a time, and it stays targeted as you move between tabs.
            <Box margin={{ top: 's' }}>
              The rest of that bar is the demo's live state, left to right: whether the targeted device
              can actually receive (it must read <b>VERIFIED</b>), who is typing a reply right now, the
              last error the app hit, who is answering the conversation — bot or you — and the version
              of the front end and back end you're running. That last pair is worth a glance if the app
              behaves unexpectedly: <Box variant="code" display="inline">be:?</Box> means the browser
              cannot reach the API at all.
            </Box>
            <Box margin={{ top: 's' }}>
              Current device target: <b>{targetLabel}</b>
            </Box>
          </Section>
          <Section title="3 · Send a use case example to the currently targeted device">
            On the Interactive Demos tab, each card pushes a use case example to the currently
            targeted device — one flat list covering both member-facing scenarios and internal staff
            self-service (clock in/out, schedule, PTO, shift swap). Between them they exercise rich
            cards, suggestion chips, a verification code that expires, the wellness store catalog
            (the one example that uses a swipeable carousel), and more. Use “Device preview” on a card
            to see its content before sending. “Reset demo data” clears every recipient's
            conversations, carts, and codes — and also deletes any photos sent through the two
            rich-media use case examples below, so a fresh demo starts with no leftover media in S3.
            <p>
              <b>Video Visit</b> is the one card that does more than send. Its button also opens the
              clinician's side of a live WebRTC call (Amazon Chime SDK) and tells you when the patient
              has joined, so you know when to walk in; “Video preview” opens the member's real webview
              in a phone frame on a throwaway visit token, which is how you see both ends without a
              handset. It's marked experimental because whether an in-conversation webview grants
              camera and microphone is up to the messaging app, not to RCS — confirmed working on
              iOS, untested on Android. The <b>Camera &amp; Mic Probe</b> on the Settings tab answers
              that narrower question on any device you're curious about.
            </p>
          </Section>
          <Section title="4 · Have a conversation with the currently targeted device">
            On the 2-way Conversations tab, reply to the currently targeted device as it messages back.
            Tapping chips or typing free text on the device drives the conversation: deterministic flows
            (Rx, appointments, store, verification) respond instantly; Benefits and Find Care are answered
            by the AI assistant grounded on the content files. Any photo the member sends renders inline
            in the transcript (click it to view full size) alongside its GenAI-generated description.
          </Section>
          <Section title="5 · Live-agent handover">
            From the currently targeted device, ask to “talk to a person” (or tap the chip). Use the
            demo's 2-way Conversations tab and reply to the currently targeted device (simulate a human
            taking over from the agent's pre-programmed replies). While a human is handling the
            conversation, a photo the member sends is still logged and shown in the transcript, but the
            bot stays silent — it sends a plain “picture received” receipt instead of its usual
            classification card, so it doesn't talk over the human. “Release to bot” hands control back
            to the assistant.
          </Section>
          <Section title="6 · Carrier or webview — choosing a transport for files">
            <b>Classify a Photo</b> demonstrates receiving a member-submitted photo directly in the RCS
            thread: the file crosses the public carrier network on the way to AWS — and Google is part of
            the RCS delivery chain, so that traffic is also subject to the Google RCS for Business terms.
            It's scoped to a generic, non-sensitive example for that reason. <b>Secure Document Upload</b>{' '}
            instead sends a webview link; the file uploads straight from that browser to a private S3
            bucket and never enters the message thread — the right transport for anything that could
            contain PII
            (an invoice, a driver's license) or PHI (an insurance card, a medical report). Both paths
            convert the photo (including iPhone HEIC, with automatic orientation correction) to a
            displayable JPEG and classify it with Bedrock; tap each card's “PII/PHI guidance” link for
            the full trade-off, and the “latest photo received” preview under each card for the most
            recent result. Note that a webview is only a browser window — the authentication in front of
            it is your application's job, and in this demo the upload page deliberately has none.
            <p>
              The same choice exists on the way <b>out</b>. A <code>FileMessage</code> is fetched from
              your bucket by AWS, rehosted, and carried over the carrier network, so what you attach
              has to be safe to send that way. <b>Pharmacy Rx Refill</b> shows both sides in one
              exchange: <b>Rx Documents</b> attaches a generic “Magic Medicine Facts” PDF — the same
              file for every member — and offers the member's own prescription record, which carries
              their name, address, prescriber and directions, through a webview instead. The bucket
              policy grants the RCS service read access to <code>media/</code> and the inbound prefixes
              only, and the channel adapter's role reads just those three prefixes. A file message
              naming that record was refused with RESOURCE_NOT_ACCESSIBLE on a test deployment. Tap that card's
              “PII/PHI guidance” link for the details.
            </p>
            <p>
              These transport patterns are illustrative, and this demo is not HIPAA-compliant.
              Choosing a transport is one control among several: if you handle real PHI, you are
              responsible for your own HIPAA compliance, including an AWS Business Associate
              Addendum (BAA), access controls, audit logging, and encryption in transit and at
              rest. See{' '}
              <Link
                href="https://aws.amazon.com/compliance/hipaa-compliance/"
                external
                externalIconAriaLabel="Opens in a new tab"
              >
                AWS HIPAA compliance
              </Link>
              .
            </p>
          </Section>
        </ColumnLayout>

        <Section title="7 · Learn RCS — what the service does, beyond this demo">
          Every feature tag on an Interactive Demos card is a link into the AWS End User Messaging
          documentation. This list is the same content in one place, including the capabilities this
          sample deliberately does not implement — a demo is not the shape of the service.
          <Box margin={{ top: 's' }}>
            <SpaceBetween size="xs">
              {apiFeatures.map((f) => (
                <Box key={f.key}>
                  <Box variant="strong" display="inline">
                    {f.docUrl ? (
                      <Link href={f.docUrl} external externalIconAriaLabel="Opens in a new tab">
                        {f.name}
                      </Link>
                    ) : (
                      f.name
                    )}
                  </Box>
                  {f.status !== 'demonstrated' && (
                    <Box
                      display="inline"
                      color={f.status === 'planned-by-aws' ? 'text-status-inactive' : 'text-status-warning'}
                      fontSize="body-s"
                    >
                      {f.status === 'planned-by-aws' ? ' — planned by AWS' : ' — not shown in this demo'}
                    </Box>
                  )}
                  <Box fontSize="body-s">{f.blurb}</Box>
                  {f.statusNote && (
                    <Box fontSize="body-s" color="text-body-secondary">
                      {f.statusNote}
                    </Box>
                  )}
                </Box>
              ))}
            </SpaceBetween>
          </Box>
          {!!limits.length && (
            <Box margin={{ top: 'm' }}>
              <Box variant="strong">Documented RCS limits</Box>
              <Box fontSize="body-s" color="text-body-secondary">
                Read straight from <Box variant="code" display="inline">content/rcs-features.json</Box>,
                the same file the send-path validator uses — so what this demo enforces and what it
                tells you are the same number.
                {registry?.reviewedOn && (
                  <>
                    {' '}These limits were last read against the{' '}
                    <Link
                      href="https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs.html"
                      external
                      externalIconAriaLabel="Opens in a new tab"
                    >
                      RCS user guide
                    </Link>{' '}
                    on {registry.reviewedOn}. Check the guide for anything newer.
                  </>
                )}
              </Box>
              <Box margin={{ top: 'xs' }} fontSize="body-s">
                {limits.map((l) => (
                  <Box key={l.key ?? l.label}>
                    {l.label}: <b>{l.value.toLocaleString()}{l.unit ? ` ${l.unit}` : ''}</b>
                    {l.note ? ` — ${l.note}` : ''}
                  </Box>
                ))}
              </Box>
            </Box>
          )}
          <Box margin={{ top: 'm' }} fontSize="body-s" color="text-body-secondary">
            RCS reaches {countryLimit ?? 22} countries today, against 200+ for SMS, on Android with RCS
            enabled and on iPhone from iOS 18. Plan for SMS fallback rather than assuming reach.
          </Box>
        </Section>

        <Box color="text-body-secondary" fontSize="body-s">
          Everything shown — brand, plan details, providers, and store products — is editable in the{' '}
          <Box variant="code" display="inline">content/*.md</Box> files. Nothing is hardcoded.
        </Box>

        {/* Where to go next. The two Markdown docs live in the repo you deployed
            this from, so they are named by path rather than linked; the AWS pages
            are linked and are the same URLs the registry cites. */}
        <Box color="text-body-secondary" fontSize="body-s">
          Going deeper: <Box variant="code" display="inline">docs/tutorial.md</Box> in this repo walks
          the build end to end, and <Box variant="code" display="inline">docs/architecture.md</Box>{' '}
          explains why each piece is shaped the way it is.{' '}
          <Box variant="code" display="inline">docs/updating-rcs-content.md</Box> is the procedure for
          refreshing everything on this page when AWS ships something new. From AWS:{' '}
          <Link
            href="https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs.html"
            external
            externalIconAriaLabel="Opens in a new tab"
          >
            the RCS user guide
          </Link>{' '}
          and{' '}
          <Link
            href="https://aws.amazon.com/end-user-messaging/rcs/"
            external
            externalIconAriaLabel="Opens in a new tab"
          >
            the AWS End User Messaging RCS product page
          </Link>
          .
        </Box>
      </SpaceBetween>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Container header={<Header variant="h3">{title}</Header>}>
      <Box color="text-body-secondary">{children}</Box>
    </Container>
  );
}
