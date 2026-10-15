import { useEffect, useState } from 'react';
import Header from '@cloudscape-design/components/header';
import Button from '@cloudscape-design/components/button';
import Alert from '@cloudscape-design/components/alert';
import Cards from '@cloudscape-design/components/cards';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import Popover from '@cloudscape-design/components/popover';
import Spinner from '@cloudscape-design/components/spinner';
import { api, AgentIdentity, Brand, LatestMedia, Tester, Vignette } from '../api';
import PhonePreviewPopover from '../components/PhonePreviewPopover';
import PiiGuidanceTooltip from '../components/PiiGuidanceTooltip';
import FeatureTag from '../components/FeatureTag';
import ImagePreviewModal from '../components/ImagePreviewModal';
import VideoVisitModal from '../components/VideoVisitModal';
import VideoPreviewModal from '../components/VideoPreviewModal';
import MysteryBoxModal from '../components/MysteryBoxModal';

// Vignette ids that get a PII/PHI guidance tooltip on their card — see
// PiiGuidanceTooltip.tsx and the matching server-side rationale in
// lambda/flows/photo_submission.py / insurance_upload.py / pharmacy.py.
// 'native' and 'webview' are the two *inbound* paths; 'outbound' is the same
// decision for a document the agent sends, which the Rx refill flow shows both
// ways in one exchange.
const PII_GUIDANCE_VARIANT: Record<string, 'native' | 'webview' | 'outbound'> = {
  photo_submission: 'native',
  insurance_upload: 'webview',
  rx_refill: 'outbound',
};

// Vignette ids whose card shows a "latest photo received" preview — the
// same two rich-media vignettes that have a PII_GUIDANCE_VARIANT entry
// above, kept as a separate set since the concepts are related but not
// identical (a card could plausibly want one badge without the other).
const MEDIA_PREVIEW_VIGNETTES = new Set(['photo_submission', 'insurance_upload']);

// The one vignette whose send button does not go through /api/trigger. A video
// visit has two live participants, so the dashboard has to hold the visit token
// the handset was sent — /api/video/start returns it — and join the same Chime
// meeting from here. Triggering it the normal way would let the flow mint its
// own token, leaving the operator and the member in separate empty meetings.
// See lambda/dashboard_handler.start_video_visit and VideoVisitModal.tsx.
const VIDEO_VISIT_VIGNETTE = 'video_visit';

// Vignette ids that are operator diagnostics, hidden from this Use Case
// Examples list and shown only in the Settings tab. media_probe (Camera & Mic
// Probe) opens one page three ways to find out whether an RCS webview can reach
// getUserMedia — a troubleshooting tool, not a scenario you would demo.
const DIAGNOSTIC_VIGNETTES = new Set(['media_probe']);

// Vignette ids rendered as a "Mystery Box": the card face shows no name,
// description, features or preview — only a single "." in its corner that opens
// a modal revealing what it is (and a Send button). The two IVS webview
// experiments are surfaced this way here, and ALSO appear (named, with a send
// control) in the Settings -> Diagnostics & experiments section.
const MYSTERY_VIGNETTES = new Set(['ivs_experiment', 'ivs_fitness']);

export default function Demo({
  phone,
  brand,
  // The live identity read off the RCS registration, used only to give the
  // device previews the real logo and display name. Null when the API key
  // isn't set, in which case the previews fall back to content/brand.md.
  identity,
  onError,
}: {
  phone: string;
  brand: Brand | null;
  identity: AgentIdentity | null;
  onError: (e: string) => void;
}) {
  const [vignettes, setVignettes] = useState<Vignette[]>([]);
  const [testers, setTesters] = useState<Tester[]>([]);
  const [busy, setBusy] = useState<string>('');
  const [msg, setMsg] = useState<string>('');
  const [latestMedia, setLatestMedia] = useState<LatestMedia>({});
  const [visitToken, setVisitToken] = useState<string | null>(null);
  // Which Mystery Box's reveal modal is open (null = none).
  const [mysteryBox, setMysteryBox] = useState<Vignette | null>(null);

  useEffect(() => { api.getVignettes().then(setVignettes).catch((e) => onError(String(e))); }, []);
  useEffect(() => { api.getTesters().then(setTesters).catch(() => {}); }, [phone]);

  // Polled rather than fetched once — a member can send a native photo or
  // finish a webview upload at any time while this tab is open, and there's
  // no push channel into the dashboard to react to that immediately.
  useEffect(() => {
    if (!phone) { setLatestMedia({}); return; }
    const load = () => api.getLatestMedia(phone).then(setLatestMedia).catch(() => {});
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, [phone]);

  // Same "name (phone)" label used by the status bar, so the button text
  // matches whatever the operator sees as their current target there.
  const currentLabel = (() => {
    if (!phone) return '';
    const t = testers.find((x) => x.phone === phone);
    return t?.name ? `${t.name} (${phone})` : phone;
  })();

  async function trigger(t: string) {
    setBusy(t); setMsg('');
    try { await api.trigger(phone, t); setMsg(`Sent “${t}” to your device.`); }
    catch (e) { onError(String(e)); } finally { setBusy(''); }
  }
  // Sends the invitation and opens the clinician-side client on the same visit
  // token, so the operator is already in the room when the member taps the chip.
  async function startVideoVisit() {
    setBusy(VIDEO_VISIT_VIGNETTE); setMsg('');
    try {
      const r = await api.startVideoVisit(phone);
      setVisitToken(r.visit);
      setMsg(`Video visit invitation sent to ${currentLabel}.`);
    } catch (e) { onError(String(e)); } finally { setBusy(''); }
  }
  async function reset() {
    if (!confirm('Clear all demo conversations, carts, codes, and uploaded media?')) return;
    try {
      const result = await api.reset();
      setLatestMedia({});
      const noun = result.deleted_media_objects === 1 ? 'object' : 'objects';
      setMsg(`Demo data reset. Cleared ${result.deleted_media_objects} uploaded media ${noun}.`);
    } catch (e) {
      onError(String(e));
    }
  }

  return (
    <SpaceBetween size="m">
      <Header
        variant="h2"
        actions={
          <SpaceBetween direction="horizontal" size="xs" alignItems="center">
            <Button onClick={reset}>Reset demo data</Button>
            <Popover
              triggerType="text"
              size="medium"
              dismissAriaLabel="Close"
              content="Clears all demo conversations, carts, and one-time codes for every recipient. Registered recipients and their verification status are not affected."
            >
              <Box color="text-body-secondary" fontSize="body-s">ⓘ</Box>
            </Popover>
          </SpaceBetween>
        }
      >
        Use Case Examples
      </Header>

      {!phone && <Alert type="warning">Select a target recipient above to send demos.</Alert>}
      {msg && <Alert type="success" dismissible onDismiss={() => setMsg('')}>{msg}</Alert>}

      {(() => {
        const cardsPerRow = [{ cards: 1 }, { minWidth: 500, cards: 2 }, { minWidth: 900, cards: 3 }];
        const cardDefinition = {
          header: (v: Vignette) =>
            MYSTERY_VIGNETTES.has(v.id) ? (
              // Subtly mysterious: a muted label and a small glyph, no real name,
              // category or tooltip. The "." in the footer is the only way in.
              <SpaceBetween direction="horizontal" size="xs" alignItems="center">
                <Box variant="strong" color="text-body-secondary">Mystery Box</Box>
                <Box color="text-status-inactive" fontSize="body-s">?</Box>
              </SpaceBetween>
            ) : (
              <SpaceBetween direction="horizontal" size="xs" alignItems="center">
                <Box variant="strong">{v.name}</Box>
                <CategoryBadge category={v.category} />
                {PII_GUIDANCE_VARIANT[v.id] && <PiiGuidanceTooltip variant={PII_GUIDANCE_VARIANT[v.id]} />}
              </SpaceBetween>
            ),
          sections: [
            {
              id: 'description',
              content: (v: Vignette) =>
                MYSTERY_VIGNETTES.has(v.id) ? (
                  // No description on the face — a Mystery Box gives nothing away.
                  // A faint hint keeps the card from looking broken/empty.
                  <Box color="text-status-inactive" fontSize="body-s"><i>Contents hidden.</i></Box>
                ) : (
                  <Box color="text-body-secondary" fontSize="body-s">{v.description}</Box>
                ),
            },
            {
              id: 'features',
              // Each tag is a popover explaining the feature, its documented
              // limits and its AWS doc link — all served from
              // content/rcs-features.json, never written here.
              content: (v: Vignette) =>
                MYSTERY_VIGNETTES.has(v.id) ? null : (
                  <Box color="text-body-secondary" fontSize="body-s">
                    {v.features.map((f, i) => (
                      <span key={f.key}>
                        {i > 0 && ' · '}
                        <FeatureTag feature={f} />
                      </span>
                    ))}
                  </Box>
                ),
            },
            {
              id: 'action',
              content: (v: Vignette) =>
                MYSTERY_VIGNETTES.has(v.id) ? (
                  // The only affordance on a Mystery Box face: a single "."
                  // pushed to the lower-right corner. Tapping it opens the reveal
                  // modal. A plain link-styled button keeps it visually quiet;
                  // aria-label so it isn't an unlabelled "." to a screen reader.
                  <Box textAlign="right">
                    <Button
                      variant="inline-link"
                      ariaLabel="Reveal this mystery box"
                      onClick={() => setMysteryBox(v)}
                    >
                      .
                    </Button>
                  </Box>
                ) : (
                <SpaceBetween direction="horizontal" size="s" alignItems="center">
                  {v.id === VIDEO_VISIT_VIGNETTE ? (
                    <Button
                      disabled={!phone}
                      loading={busy === VIDEO_VISIT_VIGNETTE}
                      onClick={startVideoVisit}
                    >
                      {phone ? `Start visit with ${currentLabel}` : 'Start video visit'}
                    </Button>
                  ) : (
                    <Button
                      disabled={!phone}
                      loading={busy === v.trigger}
                      onClick={() => trigger(v.trigger)}
                    >
                      {phone ? `Send to ${currentLabel}` : 'Send to my phone'}
                    </Button>
                  )}
                  <PhonePreviewPopover vignetteId={v.id} brand={brand} identity={identity} />
                  {/* Only this vignette has a second thing to preview: the card is
                      just the doorway, and the webview behind it is what actually
                      needs looking at. See VideoPreviewModal.tsx. */}
                  {v.id === VIDEO_VISIT_VIGNETTE && <VideoPreviewModal />}
                </SpaceBetween>
                ),
            },
            {
              id: 'latest_media',
              content: (v: Vignette) =>
                MYSTERY_VIGNETTES.has(v.id)
                  ? null
                  : MEDIA_PREVIEW_VIGNETTES.has(v.id)
                    ? <LatestMediaPreview entry={latestMedia[v.id as 'photo_submission' | 'insurance_upload']} />
                    : null,
            },
          ],
        };
        return (
          <SpaceBetween size="l">
            <Cards
              cardDefinition={cardDefinition}
              cardsPerRow={cardsPerRow}
              items={vignettes.filter((v) => !DIAGNOSTIC_VIGNETTES.has(v.id))}
              trackBy="id"
              empty="No use case examples configured."
            />
          </SpaceBetween>
        );
      })()}

      <VideoVisitModal
        visit={visitToken}
        phoneLabel={currentLabel}
        onDismiss={() => setVisitToken(null)}
      />

      <MysteryBoxModal
        vignette={mysteryBox}
        phone={phone}
        currentLabel={currentLabel}
        busy={busy === mysteryBox?.trigger}
        onSend={(t) => { trigger(t); setMysteryBox(null); }}
        onDismiss={() => setMysteryBox(null)}
      />
    </SpaceBetween>
  );
}

// "Latest photo received" preview shown on the two rich-media vignette
// cards (photo_submission = native RCS, insurance_upload = webview upload).
// Absent entirely until that recipient has actually sent/uploaded a photo
// through this specific vignette — there's nothing to show before then.
function LatestMediaPreview({ entry }: { entry?: import('../api').LatestMediaEntry }) {
  const [imagePreview, setImagePreview] = useState<{ src: string; alt: string } | null>(null);
  if (!entry) return null;
  // An iPhone HEIC is stored before media_convert has produced anything a
  // browser can show, so the backend withholds preview_url for that window
  // (a second or two) and flags it. Showing the wait explicitly beats both a
  // broken image and a card that pops into existence unannounced.
  if (!entry.preview_url) {
    return entry.converting ? (
      <SpaceBetween direction="horizontal" size="xs" alignItems="center">
        <Spinner />
        <Box fontSize="body-s" color="text-body-secondary">Converting photo for preview…</Box>
      </SpaceBetween>
    ) : null;
  }
  const alt = entry.file_name || 'Latest received photo';
  return (
    <>
      <SpaceBetween size="xs">
        <button
          type="button"
          aria-label={`Open ${alt} full size`}
          title="Open full size"
          onClick={() => setImagePreview({ src: entry.preview_url!, alt })}
          style={{ display: 'block', width: '100%', maxWidth: 280, border: 0, padding: 0, background: 'transparent', cursor: 'zoom-in' }}
        >
          <img
            src={entry.preview_url}
            alt={alt}
            style={{ display: 'block', width: '100%', height: 150, objectFit: 'cover', borderRadius: 8, border: '1px solid #e4e9e9' }}
          />
        </button>
        <div style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
          <Box fontWeight="bold" fontSize="body-s">Photo received</Box>
          <Box fontSize="body-s" color={entry.classification ? undefined : 'text-body-secondary'}>
            {/* A JPEG/PNG previews immediately but its Bedrock description
                lands a moment later — say it's coming rather than claiming it
                is unavailable, which is only true once conversion is done. */}
            {entry.classification || (entry.converting ? 'Analyzing photo…' : '(classification unavailable)')}
          </Box>
        </div>
      </SpaceBetween>
      <ImagePreviewModal image={imagePreview} onDismiss={() => setImagePreview(null)} />
    </>
  );
}

function CategoryBadge({ category }: { category: string }) {
  // Plain low-contrast label instead of a solid-fill Badge — the category
  // (deterministic vs ai-driven) is informational, not a status worth
  // competing visually with the card's primary content.
  return (
    <div style={{ border: '1px solid #d5dbdb', borderRadius: 12, background: '#f7f8f8', padding: '2px 10px' }}>
      <Box color="text-body-secondary" fontSize="body-s" display="inline">{category}</Box>
    </div>
  );
}
