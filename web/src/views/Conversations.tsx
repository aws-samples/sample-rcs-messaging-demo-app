import { useEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import Grid from '@cloudscape-design/components/grid';
import Table from '@cloudscape-design/components/table';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Button from '@cloudscape-design/components/button';
import Input from '@cloudscape-design/components/input';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import Spinner from '@cloudscape-design/components/spinner';
import { api, ConversationSummary, ConversationDetail, Message, Tester } from '../api';
import { getAccentColor } from '../theme';
import MessageJsonModal from '../components/MessageJsonModal';
import ImagePreviewModal from '../components/ImagePreviewModal';

export default function Conversations({ onError }: { onError: (e: string) => void }) {
  const [list, setList] = useState<ConversationSummary[]>([]);
  const [sel, setSel] = useState<string>('');
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [testers, setTesters] = useState<Tester[]>([]);
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [jsonMessage, setJsonMessage] = useState<Message | null>(null);
  const [imagePreview, setImagePreview] = useState<{ src: string; alt: string } | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  // hash -> real phone (needed to reply / switch mode)
  const phoneFor = (hash: string) => testers.find((t) => t.phone_hash === hash)?.phone || '';

  useEffect(() => {
    api.getTesters().then(setTesters).catch(() => {});
    const load = () => api.getConversations().then((r) => setList(r.conversations)).catch((e) => onError(String(e)));
    load();
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (!sel) return;
    const load = () => api.getConversation(sel, true).then((d) => setDetail(d)).catch((e) => onError(String(e)));
    load();
    const id = setInterval(load, 3000);
    return () => clearInterval(id);
  }, [sel]);

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth' }); }, [detail?.messages.length]);

  const phone = detail ? phoneFor(detail.phone_hash) : '';

  async function send() {
    if (!draft.trim() || !phone) return;
    setSending(true);
    try { await api.reply(phone, draft.trim()); setDraft(''); await api.getConversation(sel, true).then(setDetail); }
    catch (e) { onError(String(e)); } finally { setSending(false); }
  }
  async function mode(m: 'bot' | 'live') {
    if (!phone) { onError('Cannot resolve phone for this conversation (not a known tester).'); return; }
    try { await api.setMode(phone, m); await api.getConversation(sel, true).then(setDetail); }
    catch (e) { onError(String(e)); }
  }

  const selected = list.find((c) => c.phone_hash === sel);

  return (
    <Grid gridDefinition={[{ colspan: 3 }, { colspan: 9 }]}>
      <Table<ConversationSummary>
        header={<Header variant="h3">Conversations</Header>}
        variant="container"
        items={list}
        trackBy="phone_hash"
        selectionType="single"
        selectedItems={selected ? [selected] : []}
        onSelectionChange={({ detail: d }) => setSel(d.selectedItems[0]?.phone_hash || '')}
        empty={
          <Box color="text-body-secondary" fontSize="body-s" padding="s">
            No conversations yet. Send a use case example from the Demo tab.
          </Box>
        }
        columnDefinitions={[
          {
            id: 'conversation',
            header: 'Conversation',
            cell: (c) => (
              <SpaceBetween size="xxs">
                <SpaceBetween direction="horizontal" size="xs" alignItems="center">
                  <Box fontWeight="bold" fontSize="body-s">
                    {c.name || `${c.phone_hash.slice(5, 13)}…`}
                  </Box>
                  {c.mode === 'live' && <StatusIndicator type="warning">LIVE</StatusIndicator>}
                </SpaceBetween>
                <Box color="text-body-secondary" fontSize="body-s">
                  {c.last_direction} · {fmt(c.last_message)}
                </Box>
              </SpaceBetween>
            ),
          },
        ]}
      />

      <Container disableContentPaddings fitHeight>
        {!detail && (
          <Box textAlign="center" color="text-body-secondary" padding="xxl">
            Select a conversation
          </Box>
        )}
        {detail && (
          <div style={{ display: 'flex', flexDirection: 'column', height: '72vh' }}>
            <div style={{ padding: '10px 14px', borderBottom: '1px solid #eef2f2' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <SpaceBetween direction="horizontal" size="s" alignItems="center">
                  <Box variant="strong">{detail.name || 'Member'}</Box>
                  <StatusIndicator type={detail.mode === 'live' ? 'warning' : 'info'}>
                    {detail.mode === 'live' ? 'LIVE — human handling' : 'BOT'}
                  </StatusIndicator>
                  {!phone && <StatusIndicator type="error">phone not resolvable</StatusIndicator>}
                </SpaceBetween>
                <SpaceBetween direction="horizontal" size="xs">
                  <Button disabled={detail.mode === 'live'} onClick={() => mode('live')}>
                    Take over
                  </Button>
                  <Button disabled={detail.mode === 'bot'} onClick={() => mode('bot')}>
                    Release to bot
                  </Button>
                </SpaceBetween>
              </div>
            </div>

            <div style={{ flex: 1, overflow: 'auto', padding: 14, display: 'flex', flexDirection: 'column', gap: 8 }}>
              {detail.messages.map((m, i) => {
                if (m.type === 'event') return <div key={i} style={eventStyle}>{m.event_type}</div>;
                const out = m.direction === 'outbound';
                return (
                  <div key={i} style={{ alignSelf: out ? 'flex-end' : 'flex-start', maxWidth: '75%' }}>
                    {m.actor && (
                      <Box textAlign="right" fontSize="body-s" color="text-status-warning">
                        {m.actor}
                      </Box>
                    )}
                    <div style={bubble(out)}>
                      {m.media_content?.mediaStatus === 'SUCCESS' && (m.media_content?.convertedS3Key || m.media_content?.s3Key) ? (
                        <SpaceBetween size="xxs">
                          {isBrowserRenderableImage(m.media_content.convertedMimeType || m.media_content.mimeType) ? (
                            <button
                              type="button"
                              aria-label={`Open ${m.media_content.fileName || 'received photo'} full size`}
                              title="Open full size"
                              onClick={() => setImagePreview({
                                src: api.mediaUrl(m.media_content.convertedS3Key || m.media_content.s3Key),
                                alt: m.media_content.fileName || 'Received photo',
                              })}
                              style={{ display: 'block', border: 0, padding: 0, background: 'transparent', cursor: 'zoom-in' }}
                            >
                              <img
                                src={api.mediaUrl(m.media_content.convertedS3Key || m.media_content.s3Key)}
                                alt={m.media_content.fileName || 'Received photo'}
                                style={{ display: 'block', maxWidth: '100%', maxHeight: 220, borderRadius: 8 }}
                              />
                            </button>
                          ) : isMediaConversionPending(m.media_content) ? (
                            // media_convert is still working on it. Transient,
                            // and it resolves into the <img> above on the next
                            // 3s poll — don't tell the operator the format is
                            // unpreviewable when it's about to be previewed.
                            <PendingMedia label="Converting for preview and analyzing…" />
                          ) : (
                            // A format a browser can't decode via <img> and
                            // media_convert doesn't handle either (HEIC/HEIF
                            // take the pending/converted branches above). The
                            // file still landed in S3, but this dashboard's
                            // preview and the bot's GenAI classification can't
                            // use it. Say so rather than showing a broken image
                            // icon.
                            <Box fontSize="body-s" color="text-body-secondary">
                              Preview not available for this format ({m.media_content.mimeType || 'unknown'}) in this
                              dashboard — the file is stored, but browsers can't render it directly.
                            </Box>
                          )}
                          <Box fontSize="body-s" color="text-body-secondary">{m.body}</Box>
                          {m.media_content.classification ? (
                            <div style={{ paddingTop: 4 }}>
                              <Box fontWeight="bold" fontSize="body-s">Photo received</Box>
                              <Box fontSize="body-s">{m.media_content.classification}</Box>
                            </div>
                          ) : (
                            // A photo the browser can already render (JPEG/PNG)
                            // still waits on the Bedrock description, so say
                            // it's coming instead of leaving a gap that fills
                            // itself in seconds later.
                            isBrowserRenderableImage(m.media_content.convertedMimeType || m.media_content.mimeType) &&
                            isMediaConversionPending(m.media_content) && <PendingMedia label="Analyzing photo…" />
                          )}
                        </SpaceBetween>
                      ) : (
                        m.body
                      )}
                    </div>
                    <div style={{ textAlign: out ? 'right' : 'left', marginTop: 2 }}>
                      <Button variant="inline-link" iconName="script" onClick={() => setJsonMessage(m)}>
                        View JSON
                      </Button>
                    </div>
                  </div>
                );
              })}
              <div ref={bottom} />
            </div>

            <div style={{ padding: 10, borderTop: '1px solid #eef2f2' }}>
              <div style={{ display: 'flex', gap: 8 }}>
                <div style={{ flex: 1 }}>
                  <Input
                    value={draft}
                    onChange={({ detail: d }) => setDraft(d.value)}
                    onKeyDown={({ detail: d }) => { if (d.key === 'Enter') send(); }}
                    placeholder={phone ? 'Reply as a care advocate…' : 'Phone not resolvable — add this number as a tester'}
                    disabled={!phone}
                  />
                </div>
                <Button variant="primary" disabled={!phone || !draft.trim()} loading={sending} onClick={send}>
                  Send
                </Button>
              </div>
            </div>
          </div>
        )}
      </Container>

      <MessageJsonModal message={jsonMessage} visible={!!jsonMessage} onDismiss={() => setJsonMessage(null)} />
      <ImagePreviewModal image={imagePreview} onDismiss={() => setImagePreview(null)} />
    </Grid>
  );
}

function PendingMedia({ label }: { label: string }) {
  return (
    <SpaceBetween direction="horizontal" size="xs" alignItems="center">
      <Spinner />
      <Box fontSize="body-s" color="text-body-secondary">{label}</Box>
    </SpaceBetween>
  );
}

// Formats a plain <img> tag can decode across current browsers. Notably
// excludes HEIC/HEIF — the format iPhones default to — which no browser will
// render. In practice the dashboard shouldn't see one for long:
// lambda/media_convert.py normalizes every convertible inbound image (HEIC
// included) to JPEG and the transcript then points at the converted key. This
// stays an explicit allowlist rather than an assumption about that, so a real
// conversion gap shows up as a "can't preview this" placeholder instead of a
// broken image icon.
const BROWSER_IMAGE_MIME_TYPES = new Set(['image/jpeg', 'image/jpg', 'image/png', 'image/gif']);
function isBrowserRenderableImage(mimeType?: string): boolean {
  return !!mimeType && BROWSER_IMAGE_MIME_TYPES.has(mimeType.toLowerCase());
}

// Mirrors channel_adapter._NATIVE_CONVERTIBLE_IMAGE_MIME_TYPES: the formats
// media_convert is expected to normalize to JPEG (and classify) after the
// channel adapter has already logged the raw inbound message.
const CONVERTIBLE_IMAGE_MIME_TYPES = new Set([...BROWSER_IMAGE_MIME_TYPES, 'image/heic', 'image/heif']);

// Conversion is asynchronous — the transcript poll picks the message up with
// only the raw key on it, and the converted JPEG plus the GenAI classification
// arrive a second or two later (common.record_native_media_conversion). Absent
// this check an iPhone HEIC spends that window claiming its format can never be
// previewed, then silently contradicts itself. Keyed on convertedS3Key rather
// than on the classification, so a photo whose classification came back empty
// settles instead of showing "analyzing…" forever.
function isMediaConversionPending(media: any): boolean {
  const mimeType = (media?.mimeType || '').toLowerCase();
  return !media?.convertedS3Key && CONVERTIBLE_IMAGE_MIME_TYPES.has(mimeType);
}

function fmt(ts: string) { return ts ? new Date(ts).toLocaleTimeString() : ''; }
const eventStyle: CSSProperties = { alignSelf: 'center', color: '#99a', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.05em' };
function bubble(out: boolean): CSSProperties {
  const accent = getAccentColor();
  // Outbound bubbles use a light accent tint with accent-colored text rather
  // than a solid accent fill — keeps the accent visible without adding
  // another heavy block of color next to the buttons/badges on this page.
  return {
    background: out ? hexToRgba(accent, 0.12) : '#eef2f2',
    color: out ? accent : '#223',
    padding: '8px 12px',
    borderRadius: 12,
    fontSize: 14,
    whiteSpace: 'pre-wrap',
  };
}

function hexToRgba(hex: string, alpha: number): string {
  const clean = hex.replace('#', '');
  const bigint = parseInt(clean.length === 3
    ? clean.split('').map((c) => c + c).join('')
    : clean, 16);
  const r = (bigint >> 16) & 255;
  const g = (bigint >> 8) & 255;
  const b = bigint & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}
