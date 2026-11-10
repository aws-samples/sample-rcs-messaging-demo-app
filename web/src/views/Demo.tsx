import { useEffect, useRef, useState } from 'react';
import Header from '@cloudscape-design/components/header';
import Button from '@cloudscape-design/components/button';
import Alert from '@cloudscape-design/components/alert';
import Cards from '@cloudscape-design/components/cards';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import Popover from '@cloudscape-design/components/popover';
import Spinner from '@cloudscape-design/components/spinner';
import type { AgentIdentity, ApiClient, Brand, LatestMedia, Tester, Vignette } from '../api';
import { isTrackedLoadError, useApi, useSession } from '../session/SessionContext';
import { usePoll } from '../session/usePoll';
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
// two rich-media vignettes that have a PII_GUIDANCE_VARIANT entry above, plus
// Identity Capture, which previews one or two sides (IdCapturePreview), and
// Site Evidence, which previews the latest ticket's items (SiteEvidencePreview).
// Kept as a separate set since the concepts are related but not identical (a
// card can want one badge without the other).
const MEDIA_PREVIEW_VIGNETTES = new Set(['photo_submission', 'insurance_upload', 'identity_capture', 'site_evidence']);

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
  // The open video visit, with the client it was started on: every later join,
  // status, ping and end request stays bound to that brand's stack.
  const [visit, setVisit] = useState<{ token: string; client: ApiClient } | null>(null);
  // Which Mystery Box's reveal modal is open (null = none).
  const [mysteryBox, setMysteryBox] = useState<Vignette | null>(null);

  const api = useApi();
  const { track, prefix, reportVideo } = useSession();

  // Only the first tester load counts toward the switch's loading state; the
  // reloads after a target change stay silent on failure, as before.
  const testersTracked = useRef(false);

  useEffect(() => {
    track(api.getVignettes(), 'use case examples')
      .then(setVignettes)
      // A tracked failure was already raised (labelled) by the session.
      .catch((e) => { if (!isTrackedLoadError(e)) onError(String(e)); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api]);
  useEffect(() => {
    let p = api.getTesters();
    if (!testersTracked.current) {
      testersTracked.current = true;
      p = track(p, 'recipients');
    }
    p.then(setTesters).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, phone]);

  // Polled rather than fetched once — a member can send a native photo or
  // finish a webview upload at any time while this tab is open, and there's
  // no push channel into the dashboard to react to that immediately. Runs only
  // while a target phone is set. The first call of each run is tracked, so it
  // must reject on failure; later ticks stay silent.
  const mediaFirst = useRef(true);
  useEffect(() => {
    mediaFirst.current = true;
    if (!phone) setLatestMedia({});
  }, [api, phone]);
  usePoll(
    () => {
      const first = mediaFirst.current;
      mediaFirst.current = false;
      return api.getLatestMedia(phone).then(setLatestMedia).catch((e) => { if (first) throw e; });
    },
    5000,
    [api, phone],
    { trackAs: 'latest media', enabled: !!phone },
  );

  // A visit this view no longer shows is no longer open to the switch guard.
  useEffect(() => () => reportVideo(null), [reportVideo]);

  // Same "name (phone)" label used by the status bar, so the button text
  // matches whatever the operator sees as their current target there.
  const currentLabel = (() => {
    if (!phone) return '';
    const t = testers.find((x) => x.phone === phone);
    return t?.name ? `${t.name} (${phone})` : phone;
  })();

  async function trigger(t: string) {
    const client = api; // bound at the confirming action
    setBusy(t); setMsg('');
    try { await client.trigger(phone, t); setMsg(prefix(`Sent “${t}” to your device.`)); }
    catch (e) { onError(String(e)); } finally { setBusy(''); }
  }
  // Sends the invitation and opens the clinician-side client on the same visit
  // token, so the operator is already in the room when the member taps the chip.
  async function startVideoVisit() {
    const client = api; // bound at the confirming click
    setBusy(VIDEO_VISIT_VIGNETTE); setMsg('');
    try {
      const r = await client.startVideoVisit(phone);
      const v = { token: r.visit, client };
      setVisit(v);
      reportVideo(v);
      setMsg(prefix(`Video visit invitation sent to ${currentLabel}.`));
    } catch (e) { onError(String(e)); } finally { setBusy(''); }
  }
  function dismissVisit() {
    setVisit(null);
    reportVideo(null);
  }
  async function reset() {
    if (!confirm(prefix('Clear all demo conversations, carts, codes, and uploaded media?'))) return;
    const client = api; // bound at the confirming action
    try {
      const result = await client.reset();
      setLatestMedia({});
      const noun = result.deleted_media_objects === 1 ? 'object' : 'objects';
      setMsg(prefix(`Demo data reset. Cleared ${result.deleted_media_objects} uploaded media ${noun}.`));
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
                  : v.id === 'identity_capture'
                    ? <IdCapturePreview entry={latestMedia.identity_capture} />
                    : v.id === 'site_evidence'
                    ? <SiteEvidencePreview entry={latestMedia.site_evidence} />
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
        visit={visit}
        phoneLabel={currentLabel}
        onDismiss={dismissVisit}
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

// Identity Capture preview: the ID type the recipient chose and one slot per
// side it needs (one for a passport, two for a license), from the latest visit
// to the capture page. A side not uploaded yet shows an empty slot, so the
// operator can see the capture is still waiting on it.
function IdCapturePreview({ entry }: { entry?: import('../api').IdCaptureEntry }) {
  const [imagePreview, setImagePreview] = useState<{ src: string; alt: string } | null>(null);
  if (!entry || entry.images.length === 0) return null;
  const done = entry.images.filter((img) => img.preview_url).length;
  const total = entry.images.length;
  return (
    <>
      <SpaceBetween size="xs">
        <Box fontWeight="bold" fontSize="body-s">
          {entry.id_label}: {done} of {total} {total === 1 ? 'photo' : 'photos'}
        </Box>
        <div style={{ display: 'grid', gridTemplateColumns: `repeat(${total}, minmax(0, 1fr))`, gap: 8, maxWidth: total * 180 }}>
          {entry.images.map((img) => {
            const alt = `${entry.id_label}, ${img.label}`;
            return (
              <div key={img.side} style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
                {img.preview_url ? (
                  <button
                    type="button"
                    aria-label={`Open ${alt} full size`}
                    title="Open full size"
                    onClick={() => setImagePreview({ src: img.preview_url!, alt })}
                    style={{ display: 'block', width: '100%', border: 0, padding: 0, background: 'transparent', cursor: 'zoom-in' }}
                  >
                    <img
                      src={img.preview_url}
                      alt={alt}
                      style={{ display: 'block', width: '100%', height: 110, objectFit: 'cover', borderRadius: 8, border: '1px solid #e4e9e9' }}
                    />
                  </button>
                ) : (
                  <div style={{ height: 110, borderRadius: 8, border: '1px dashed #c6cdcd', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 6, textAlign: 'center' }}>
                    {img.converting ? (
                      <SpaceBetween direction="horizontal" size="xxs" alignItems="center">
                        <Spinner />
                        <Box fontSize="body-s" color="text-body-secondary">Converting…</Box>
                      </SpaceBetween>
                    ) : (
                      <Box fontSize="body-s" color="text-body-secondary">
                        {img.status === 'FAILED' ? 'Upload failed' : 'Waiting for this side'}
                      </Box>
                    )}
                  </div>
                )}
                <Box fontWeight="bold" fontSize="body-s">{img.label}</Box>
                {img.preview_url && (
                  <Box fontSize="body-s" color={img.classification ? undefined : 'text-body-secondary'}>
                    {img.classification || (img.converting ? 'Analyzing photo…' : '(classification unavailable)')}
                  </Box>
                )}
              </div>
            );
          })}
        </div>
      </SpaceBetween>
      <ImagePreviewModal image={imagePreview} onDismiss={() => setImagePreview(null)} />
    </>
  );
}

// Site Evidence preview: the latest ticket (number and evidence type) and one
// tile per item logged on it, in order. A photo shows as a thumbnail with its
// description; a video or other file gets a labelled tile, because the
// converter makes no preview for it. The ticket stays after the sender taps
// Done, so the operator can still see what was logged.
function SiteEvidencePreview({ entry }: { entry?: import('../api').SiteEvidenceEntry }) {
  const [imagePreview, setImagePreview] = useState<{ src: string; alt: string } | null>(null);
  if (!entry || entry.items.length === 0) return null;
  const count = entry.items.length;
  return (
    <>
      <SpaceBetween size="xs">
        <Box fontWeight="bold" fontSize="body-s">
          Ticket {entry.ticket} · {entry.kind_label} · {count} {count === 1 ? 'item' : 'items'}
        </Box>
        <div style={{ display: 'grid', gridTemplateColumns: `repeat(${Math.min(count, 3)}, minmax(0, 1fr))`, gap: 8, maxWidth: Math.min(count, 3) * 180 }}>
          {entry.items.map((item) => {
            const alt = `Ticket ${entry.ticket}, item ${item.n}`;
            return (
              <div key={item.n} style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
                {item.preview_url ? (
                  <button
                    type="button"
                    aria-label={`Open ${alt} full size`}
                    title="Open full size"
                    onClick={() => setImagePreview({ src: item.preview_url!, alt })}
                    style={{ display: 'block', width: '100%', border: 0, padding: 0, background: 'transparent', cursor: 'zoom-in' }}
                  >
                    <img
                      src={item.preview_url}
                      alt={alt}
                      style={{ display: 'block', width: '100%', height: 110, objectFit: 'cover', borderRadius: 8, border: '1px solid #e4e9e9' }}
                    />
                  </button>
                ) : (
                  <div style={{ height: 110, borderRadius: 8, border: '1px dashed #c6cdcd', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 6, textAlign: 'center' }}>
                    <Box fontSize="body-s" color="text-body-secondary">
                      {item.type === 'video' ? 'Video received (no preview)' : item.type === 'file' ? 'File received (no preview)' : 'No preview available'}
                    </Box>
                  </div>
                )}
                <Box fontWeight="bold" fontSize="body-s">Item {item.n}</Box>
                {item.classification && <Box fontSize="body-s">{item.classification}</Box>}
              </div>
            );
          })}
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
