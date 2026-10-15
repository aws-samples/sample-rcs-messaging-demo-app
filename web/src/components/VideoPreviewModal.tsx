import { useState } from 'react';
import Modal from '@cloudscape-design/components/modal';
import Button from '@cloudscape-design/components/button';
import Box from '@cloudscape-design/components/box';
import Spinner from '@cloudscape-design/components/spinner';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import ExpandableSection from '@cloudscape-design/components/expandable-section';
import { api } from '../api';

/**
 * The video-visit counterpart of PhonePreviewPopover's "Device preview": open the
 * member's own page from the dashboard, with no handset and no send.
 *
 * What is in the frame is not a mockup. It is lambda/webviews/video-visit.html —
 * the exact page an RCS chip opens — running against a real visit token minted by
 * POST /api/video/preview, so tapping Join really creates the Chime meeting and
 * really asks for the camera. That is the point: the two things most likely to be
 * wrong about this vignette are the webview's own permission flow and whether the
 * SDK bundle loads, and a mockup would exercise neither.
 *
 * Three consequences worth knowing before editing this file:
 *
 *  • The iframe is cross-origin — the page is served by the dashboard Lambda on
 *    the API Gateway domain, not by Vite — so camera and microphone have to be
 *    delegated with `allow`, and the browser prompts for the *API* domain rather
 *    than for the dashboard's. That surprises people; the copy says so.
 *  • The frame comes up with its microphone muted (the page does this itself on
 *    ?preview=1), because the clinician modal is usually open on the same machine
 *    and two unmuted clients in one meeting is a feedback loop.
 *  • Dismissing ends the preview visit via /api/video/end with role=clinician,
 *    which deletes any meeting the preview created. Without that, closing the
 *    modal would leave a meeting billing until Chime's own idle timeout.
 */
export default function VideoPreviewModal() {
  const [open, setOpen] = useState(false);
  const [visit, setVisit] = useState('');
  const [error, setError] = useState('');

  async function open_() {
    setOpen(true);
    setError('');
    if (visit) return;  // reuse the token for the life of this component
    try {
      const r = await api.previewVideoVisit();
      setVisit(r.visit);
    } catch (e) {
      setError(`Could not mint a preview visit: ${e}`);
    }
  }

  function dismiss() {
    setOpen(false);
    // Unmount the iframe and release the token's meeting. Both matter: an iframe
    // left mounted behind a closed modal keeps its camera light on.
    if (visit) api.videoEnd(visit).catch(() => {});
    setVisit('');
  }

  return (
    <>
      <Button iconName="video-camera-on" onClick={open_} style={{ root: { borderRadius: '999px' } }}>
        Video preview
      </Button>
      <Modal visible={open} onDismiss={dismiss} size="small" header="Video preview">
        {error && <Box color="text-status-error" fontSize="body-s" padding="s">{error}</Box>}
        {!visit && !error && <Box textAlign="center" padding="l"><Spinner size="normal" /></Box>}
        {visit && (
          <div>
            <Box textAlign="center">
              {/* Same frame proportions as the message preview next to it, so the
                  two previews read as the same handset. */}
              <div style={{
                display: 'inline-block', width: 260, border: '8px solid #1a1a1a',
                borderRadius: 28, background: '#1a1a1a',
                boxShadow: '0 4px 16px rgba(0,0,0,0.25)',
              }}>
                <iframe
                  title="Member video visit page"
                  src={api.videoVisitWebviewUrl(visit, true)}
                  // Camera, microphone and autoplay are delegated explicitly: this
                  // is a cross-origin frame, so without these the page inside
                  // fails at getUserMedia with NotAllowedError and looks like the
                  // handset bug this vignette exists to rule out.
                  allow="camera; microphone; autoplay; fullscreen"
                  style={{
                    display: 'block', width: '100%', height: 560, border: 0,
                    borderRadius: 20, background: '#101414',
                  }}
                />
              </div>
            </Box>
            <Box padding={{ top: 'xs' }} fontSize="body-s">
              <StatusIndicator type="info">
                Live page, real Chime meeting, nothing sent to a device
              </StatusIndicator>
            </Box>
            <ExpandableSection headerText="How accurate is this?" variant="footer">
              <Box color="text-body-secondary" fontSize="body-s">
                This is the member's actual webview — the page an RCS chip opens — on a real visit
                token, so Join creates a real Chime SDK meeting and really asks for camera and
                microphone. No RCS message was sent and no device was involved.
                <br /><br />
                Because the page is served from the API domain rather than the dashboard's, your
                browser asks for permission for <i>that</i> origin, and the frame starts with its
                microphone muted so it cannot feed back into the clinician view. To see both ends
                at once, tap Join here and then “Start visit with …” on the card — you will be the
                patient and the clinician on one machine.
                <br /><br />
                What this cannot tell you is whether a given handset's messaging app grants camera
                access to its in-conversation webview at all. This vignette exists to answer that,
                and only a real device can: it has been confirmed working on iOS and has not yet
                been tried on Android.
              </Box>
            </ExpandableSection>
          </div>
        )}
      </Modal>
    </>
  );
}
