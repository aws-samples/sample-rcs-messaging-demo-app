import { useState } from 'react';
import Modal from '@cloudscape-design/components/modal';
import Button from '@cloudscape-design/components/button';
import Box from '@cloudscape-design/components/box';
import ExpandableSection from '@cloudscape-design/components/expandable-section';
import SegmentedControl from '@cloudscape-design/components/segmented-control';
import Spinner from '@cloudscape-design/components/spinner';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import { api, AgentIdentity, Brand, RcsCardContent, RcsMessage } from '../api';
import PhonePreview, { Platform } from './PhonePreview';

// GET /api/vignettes/preview returns Media.FileUrl as a bare S3 object key
// (e.g. "media/rx-refill.png") rather than a full URL, since the backend has
// no reliable base URL of its own to build one from (API_BASE_URL is only
// injected on the channel-adapter Lambda). Resolve it here via the same
// api.mediaUrl() helper the rest of the dashboard uses.
function resolveMediaKeys(message: RcsMessage): RcsMessage {
  const fix = (card?: RcsCardContent): RcsCardContent | undefined =>
    card?.Media?.FileUrl && !card.Media.FileUrl.startsWith('http')
      ? { ...card, Media: { ...card.Media, FileUrl: api.mediaUrl(card.Media.FileUrl) } }
      : card;

  if (!message.Content) return message;
  return {
    ...message,
    Content: {
      ...message.Content,
      RichCard: message.Content.RichCard
        ? { ...message.Content.RichCard, CardContent: fix(message.Content.RichCard.CardContent)! }
        : undefined,
      Carousel: message.Content.Carousel
        ? { ...message.Content.Carousel, CardContents: message.Content.Carousel.CardContents.map((c) => fix(c)!) }
        : undefined,
    },
  };
}

// Renders the "device preview" trigger shown on each vignette card.
//
// A Modal rather than a Popover: a popover is sized by its own max-width and
// clipped by the viewport, which for a portrait phone mockup is exactly the
// wrong shape — too wide for a 260px frame and too short to show a thread
// without the composer being cut off. `size="small"` keeps the dialog roughly
// phone-width, and a modal is free to be tall.
//
// Fetches GET /api/vignettes/preview lazily (only when the modal is actually
// opened, not on every card render) and caches the result for the lifetime of
// the component so re-opening doesn't re-fetch.
export default function PhonePreviewPopover({
  vignetteId,
  brand,
  identity,
}: {
  vignetteId: string;
  brand?: Brand | null;
  identity?: AgentIdentity | null;
}) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<'idle' | 'loading' | 'ready' | 'unavailable' | 'invalid' | 'error'>('idle');
  const [messages, setMessages] = useState<RcsMessage[]>([]);
  const [invalidReason, setInvalidReason] = useState('');
  // Android first: it's the platform that renders the most RCS surface, so it
  // shows more of what the payload can do.
  const [platform, setPlatform] = useState<Platform>('android');

  // Prefer the identity read live off the AWS registration — that is what a
  // handset will actually render. content/brand.md is the fallback, and it is
  // usually a different brand entirely (the demo ships "AnyHealth"; the agent
  // sending the message carries whatever the account registered), so the two
  // are labelled differently below rather than blended.
  const live = identity?.source === 'live';
  const agentName =
    (live && identity?.senderDisplayName) ||
    brand?.registration?.senderDisplayName ||
    brand?.brandName ||
    'Your agent';
  const logoUrl =
    (live && identity?.logoUrl) ||
    (brand?.registration?.logoImage ? api.mediaUrl(brand.registration.logoImage) : undefined);

  async function open_() {
    setOpen(true);
    if (state !== 'idle') return;
    setState('loading');
    try {
      const preview = await api.previewVignette(vignetteId);
      // The vignette builds content the RCS API would reject. Say so instead
      // of implying there's simply nothing to preview -- this is a content
      // problem that would stop the message from being sent.
      if (preview.error) { setInvalidReason(preview.error); setState('invalid'); return; }
      if (!preview.available || !preview.messages?.length) { setState('unavailable'); return; }
      setMessages(preview.messages.map(resolveMediaKeys));
      setState('ready');
    } catch {
      setState('error');
    }
  }

  return (
    <>
      <Button iconName="contact" onClick={open_} style={{ root: { borderRadius: '999px' } }}>
        Device preview
      </Button>
      <Modal
        visible={open}
        onDismiss={() => setOpen(false)}
        size="small"
        header="Device preview"
      >
        {state === 'loading' && (
          <Box textAlign="center" padding="l"><Spinner size="normal" /></Box>
        )}
        {state === 'ready' && (
          <div>
            {/* One payload, two renders. The same content genuinely looks
                different per platform -- most visibly, card suggestions sit
                inside the card on Android and detach into separate bubbles on
                iOS -- so offering a single mockup would teach the wrong lesson
                about where a chip appears. */}
            <Box padding={{ bottom: 's' }} textAlign="center">
              <SegmentedControl
                selectedId={platform}
                onChange={({ detail }) => setPlatform(detail.selectedId as Platform)}
                label="Preview platform"
                options={[
                  { id: 'android', text: 'Android' },
                  { id: 'ios', text: 'iOS' },
                ]}
              />
            </Box>
            <Box textAlign="center">
              <PhonePreview
                messages={messages}
                platform={platform}
                agentName={agentName}
                logoUrl={logoUrl}
              />
            </Box>
            <Box padding={{ top: 'xs' }} fontSize="body-s">
              {live ? (
                <StatusIndicator type="success">
                  Brand identity read live from the agent's RCS registration
                </StatusIndicator>
              ) : (
                <StatusIndicator type="info">
                  Placeholder brand from content/brand.md — the live registration wasn't readable
                  {identity?.error ? ` (${identity.error})` : ' (needs the API key in Settings)'}
                </StatusIndicator>
              )}
            </Box>
            {/* Collapsed by default: the detail matters when you're designing a
                layout, but expanding it every time would make the dialog taller
                than the phone it's explaining. */}
            <ExpandableSection headerText="How accurate is this?" variant="footer">
              <Box color="text-body-secondary" fontSize="body-s">
                This is a local render of the payload, checked against the same limits the send path
                enforces — but it is not a send. Nothing reaches SendRcsMessage, so there is no
                delivery event and no charge, and the recipient's own messaging app makes the final
                layout decisions.
                <br /><br />
                Both mockups follow one testing agent observed on real hardware, but layout, theme
                and chrome vary by OS version, handset and messaging-app build — treat them as
                approximations. The differences that are consistent and worth designing for:
                Android draws card suggestions as buttons inside the card while iOS detaches them
                into chips below it, and iOS shows a carousel one card at a time instead of as a
                swipe strip. Send to a verified test device before signing off on a layout.
              </Box>
            </ExpandableSection>
          </div>
        )}
        {state === 'unavailable' && (
          <Box color="text-body-secondary" fontSize="body-s" padding="s">
            This example's content is generated live by the AI assistant per conversation, so
            there's no fixed message to preview here.
          </Box>
        )}
        {state === 'invalid' && (
          <Box color="text-status-error" fontSize="body-s" padding="s">
            This example builds a message the RCS API would reject, so it would fail to send:
            {' '}{invalidReason}.
          </Box>
        )}
        {state === 'error' && (
          <Box color="text-status-error" fontSize="body-s" padding="s">
            Couldn't load a preview for this example.
          </Box>
        )}
      </Modal>
    </>
  );
}
