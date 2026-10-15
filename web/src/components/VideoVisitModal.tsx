import { useCallback, useEffect, useRef, useState } from 'react';
import Modal from '@cloudscape-design/components/modal';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Alert from '@cloudscape-design/components/alert';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Spinner from '@cloudscape-design/components/spinner';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import type { DefaultMeetingSession } from 'amazon-chime-sdk-js';
import { api, VideoJoin } from '../api';

/**
 * EXPERIMENTAL. The clinician's half of the video visit: a Chime SDK JS client
 * in the operator dashboard that joins the *same* Chime meeting as the member's
 * handset. See lambda/webviews/video-visit.html for the member's half — the two
 * are deliberately the same shape (prime permissions, exchange the visit token
 * for join material, bind one remote tile and a local thumbnail), because when
 * one side sees an empty room the first question is always which side is wrong.
 *
 * Unlike the webview, the SDK here is a bundled npm dependency: Vite bundles
 * the SDK, so there is no third-party CDN in this path. It is
 * `import()`ed inside join() rather than at module scope because it is ~1 MB
 * minified — a third of the whole dashboard bundle — for one experimental
 * vignette most operators never open.
 *
 * Four things worth not "cleaning up":
 *
 * 1. Joining is a button, not an effect. React StrictMode runs effects
 *    setup → cleanup → setup in development, so an auto-joining effect would
 *    join twice per open and tear the meeting down in between. A deliberate
 *    click also gives the browser the user gesture that makes autoplaying the
 *    remote audio element reliable.
 * 2. Dismissing ends the meeting for everyone, via /api/video/end with
 *    role=clinician. That is the intended semantics — the clinician hanging up
 *    ends the visit — and it is also the cost control, since attendee-minutes
 *    bill until Chime's own idle timeout otherwise. The member's page cannot do
 *    the same; see the role discussion in lambda/video_visit.py.
 * 3. Unmount tears down too, not just onDismiss. Switching dashboard tabs
 *    unmounts this component without a dismiss, and a live meeting left behind
 *    keeps accruing attendee-minutes.
 * 4. Presence comes from polling /api/video/status, not from the Chime session.
 *    The whole point of the "patient is waiting" indicator is to work *before*
 *    the clinician joins, when there is no local session to ask. The same poll
 *    doubles as this side's heartbeat once live.
 */
export default function VideoVisitModal({
  visit,
  phoneLabel,
  onDismiss,
}: {
  /** The visit token from POST /api/video/start. Null when the modal is closed. */
  visit: string | null;
  phoneLabel: string;
  onDismiss: () => void;
}) {
  const [phase, setPhase] = useState<'idle' | 'joining' | 'live' | 'ended'>('idle');
  const [error, setError] = useState('');
  const [note, setNote] = useState('');
  const [muted, setMuted] = useState(false);
  const [cameraOn, setCameraOn] = useState(true);
  const [remoteJoined, setRemoteJoined] = useState(false);
  // From the presence poll, not from WebRTC: true means the member's page is
  // open and heartbeating, which is the cue for the clinician to walk in.
  const [memberPresent, setMemberPresent] = useState(false);

  const remoteRef = useRef<HTMLVideoElement | null>(null);
  const localRef = useRef<HTMLVideoElement | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const sessionRef = useRef<DefaultMeetingSession | null>(null);
  // The token this modal actually joined, which is not always `visit`: teardown
  // has to end the meeting it joined even if the prop has already been cleared
  // by the parent on dismiss.
  const joinedTokenRef = useRef<string | null>(null);
  const remoteTileRef = useRef<number | null>(null);

  const teardown = useCallback(() => {
    const token = joinedTokenRef.current;
    joinedTokenRef.current = null;
    const session = sessionRef.current;
    sessionRef.current = null;
    if (session) {
      try {
        session.audioVideo.stopLocalVideoTile();
        session.audioVideo.stop();
      } catch { /* tearing down; nothing left to salvage */ }
    }
    // Fire-and-forget: this runs from unmount and from dismiss, where there is
    // nobody left to show a failure to. The server-side teardown is idempotent.
    if (token) api.videoEnd(token).catch(() => {});
  }, []);

  useEffect(() => teardown, [teardown]);

  // Presence poll. Runs for as long as the modal is open, including before the
  // clinician joins — that is the case it exists for. Safe under StrictMode's
  // double-invoke (unlike joining, it creates nothing), and it also reports this
  // side's own heartbeat once we are in, so the member's page and the backend
  // both know the clinician is still here.
  //
  // 5s rather than the clients' 15s heartbeat interval: this is the latency the
  // clinician actually feels between the patient tapping Join and the dashboard
  // saying so, and one small GET every five seconds while a modal is open is not
  // worth optimising.
  useEffect(() => {
    if (!visit) return;
    let live = true;
    const tick = async () => {
      try {
        const s = await api.videoStatus(visit);
        if (!live) return;
        setMemberPresent(!!s.member);
      } catch {
        // Presence is advisory. A failed poll must not surface an error over a
        // call that is working, so it is dropped and the next tick retries.
      }
      if (joinedTokenRef.current) api.videoPing(visit).catch(() => {});
    };
    tick();
    const id = setInterval(tick, 5000);
    return () => { live = false; clearInterval(id); };
  }, [visit]);

  async function join() {
    if (!visit) return;
    setPhase('joining');
    setError('');
    setNote('');
    // Drop any session a previous attempt left behind — locally only, without
    // calling /api/video/end. Retrying must not end the visit the member may
    // already be sitting in; that is exactly the desync this modal used to cause.
    const stale = sessionRef.current;
    sessionRef.current = null;
    if (stale) {
      try { stale.audioVideo.stop(); } catch { /* already down */ }
    }
    setRemoteJoined(false);
    remoteTileRef.current = null;

    let chime: typeof import('amazon-chime-sdk-js');
    let material: VideoJoin;
    try {
      // Loaded before the join call, so a failure to fetch the SDK chunk is not
      // reported as a visit problem — and so no attendee slot is spent on a
      // client that cannot start.
      chime = await import('amazon-chime-sdk-js');
    } catch (e) {
      setPhase('idle');
      return setError(`Could not load the video client: ${e}`);
    }
    try {
      material = await api.videoJoin(visit);
    } catch (e) {
      setPhase('idle');
      return setError(`Could not reach the visit service: ${e}`);
    }
    if (material.error || !material.Meeting || !material.Attendee) {
      setPhase('idle');
      return setError(material.error || 'The visit service returned no join material.');
    }

    const logger = new chime.ConsoleLogger('chime-operator', chime.LogLevel.WARN);
    const session = new chime.DefaultMeetingSession(
      new chime.MeetingSessionConfiguration(material.Meeting, material.Attendee),
      logger,
      new chime.DefaultDeviceController(logger),
    );
    sessionRef.current = session;
    joinedTokenRef.current = visit;
    const av = session.audioVideo;

    av.addObserver({
      videoTileDidUpdate: (tile) => {
        if (!tile.boundAttendeeId || tile.tileId === null) return;
        // localTile is what tells the two apart. Binding the member's stream
        // into the thumbnail (or the operator's into the main frame) is the
        // classic way this layout goes wrong, and it looks like a server bug.
        const el = tile.localTile ? localRef.current : remoteRef.current;
        if (el) av.bindVideoElement(tile.tileId, el);
        if (!tile.localTile) {
          remoteTileRef.current = tile.tileId;
          setRemoteJoined(true);
        }
      },
      videoTileWasRemoved: (tileId) => {
        // Only the member's tile clears the "waiting" overlay's counterpart —
        // the operator toggling their own camera must not make the frame claim
        // the member left.
        if (tileId === remoteTileRef.current) {
          remoteTileRef.current = null;
          setRemoteJoined(false);
        }
      },
      audioVideoDidStart: () => setPhase('live'),
      audioVideoDidStop: () => {
        setPhase('ended');
        setNote('The visit has ended.');
      },
      connectionDidBecomePoor: () => setNote('Connection is poor — video may pause; audio continues.'),
    });

    if (audioRef.current) {
      try {
        await av.bindAudioElement(audioRef.current);
      } catch {
        // Not fatal: video can still work, and the operator will notice silence
        // faster than any message here would tell them.
        setNote('Could not attach meeting audio — you may not hear the member.');
      }
    }

    // Microphone and camera as separate steps, mic first. A laptop with no
    // webcam, or a camera held by another conference app, should still produce a
    // usable audio call rather than failing the whole join.
    try {
      const mics = await av.listAudioInputDevices();
      if (!mics.length) throw new Error('no microphone found');
      await av.startAudioInput(mics[0].deviceId);
    } catch (e) {
      // Local stop, not teardown(): a missing microphone on the clinician's
      // laptop is their problem to fix, and must not evict the member from a
      // meeting they are already waiting in.
      try { av.stop(); } catch { /* never started */ }
      sessionRef.current = null;
      setPhase('idle');
      return setError(`No microphone available: ${e}`);
    }

    let withVideo = true;
    try {
      const cams = await av.listVideoInputDevices();
      if (!cams.length) throw new Error('no camera found');
      await av.startVideoInput(cams[0].deviceId);
    } catch {
      withVideo = false;
      setNote('No camera available — joining as audio only.');
    }
    setCameraOn(withVideo);

    av.start();
    if (withVideo) av.startLocalVideoTile();
  }

  function toggleMute() {
    const av = sessionRef.current?.audioVideo;
    if (!av) return;
    if (muted) av.realtimeUnmuteLocalAudio();
    else av.realtimeMuteLocalAudio();
    setMuted(!muted);
  }

  async function toggleCamera() {
    const av = sessionRef.current?.audioVideo;
    if (!av) return;
    try {
      if (cameraOn) {
        av.stopLocalVideoTile();
        await av.stopVideoInput();
        setCameraOn(false);
      } else {
        const cams = await av.listVideoInputDevices();
        if (!cams.length) throw new Error('no camera found');
        await av.startVideoInput(cams[0].deviceId);
        av.startLocalVideoTile();
        setCameraOn(true);
      }
    } catch (e) {
      setCameraOn(false);
      setNote(`Camera unavailable: ${e}`);
    }
  }

  function dismiss() {
    teardown();
    setPhase('idle');
    setError('');
    setNote('');
    setMuted(false);
    setRemoteJoined(false);
    setMemberPresent(false);
    onDismiss();
  }

  return (
    <Modal
      visible={!!visit}
      onDismiss={dismiss}
      size="large"
      header="Video visit — clinician view"
      footer={
        <SpaceBetween direction="horizontal" size="xs">
          {(phase === 'idle' || phase === 'ended') && (
            <Button
              variant="primary"
              onClick={() => join().catch((e) => { setPhase('idle'); setError(String(e)); })}
            >
              {phase === 'ended' ? 'Rejoin the visit' : 'Join the visit'}
            </Button>
          )}
          {phase === 'live' && (
            <>
              <Button onClick={toggleMute}>{muted ? 'Unmute' : 'Mute'}</Button>
              <Button onClick={toggleCamera}>{cameraOn ? 'Camera off' : 'Camera on'}</Button>
            </>
          )}
          <Button variant={phase === 'live' ? 'primary' : 'normal'} onClick={dismiss}>
            {phase === 'live' ? 'Leave and end visit' : 'Close'}
          </Button>
        </SpaceBetween>
      }
    >
      <SpaceBetween size="s">
        <Box color="text-body-secondary" fontSize="body-s">
          The invitation was sent to {phoneLabel || 'the recipient'}. They join by tapping
          the card in the conversation; you are both in the same Chime SDK meeting.
        </Box>
        {/* The cue to walk in. Only shown while the clinician is not yet in the
            meeting: once live, the video frame itself is the better signal, and a
            standing banner would just compete with it. */}
        {phase !== 'live' && (
          memberPresent ? (
            <Alert type="success" statusIconAriaLabel="Patient waiting">
              <b>{phoneLabel || 'The patient'} is waiting in the visit.</b>{' '}
              {phase === 'ended' ? 'Rejoin to reconnect.' : 'Join now to start the consultation.'}
            </Alert>
          ) : (
            <StatusIndicator type="pending">
              Waiting for {phoneLabel || 'the patient'} to open the invitation…
            </StatusIndicator>
          )
        )}
        {error && <Alert type="error">{error}</Alert>}
        {note && <Alert type="info">{note}</Alert>}

        <div style={{ position: 'relative', background: '#000', borderRadius: 8, overflow: 'hidden', aspectRatio: '16 / 9' }}>
          <video
            ref={remoteRef}
            autoPlay
            playsInline
            style={{ width: '100%', height: '100%', objectFit: 'contain', background: '#000' }}
          />
          {/* Local preview over the member's frame — muted so the operator does
              not hear their own microphone back. */}
          <video
            ref={localRef}
            autoPlay
            playsInline
            muted
            style={{
              position: 'absolute', right: 12, bottom: 12, width: 132, height: 99,
              objectFit: 'cover', borderRadius: 6, background: '#111',
              border: '2px solid rgba(255,255,255,.7)',
            }}
          />
          {/* Overlays the empty frame rather than replacing it, so the local
              thumbnail stays visible while waiting — the operator's own video is
              the evidence that their end of the call is working. */}
          {(phase !== 'live' || !remoteJoined) && (
            <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#9ca3af', pointerEvents: 'none' }}>
              <SpaceBetween direction="horizontal" size="xs" alignItems="center">
                {phase === 'joining' && <Spinner />}
                <span>
                  {phase === 'idle' ? 'Not joined yet.'
                    : phase === 'joining' ? 'Connecting…'
                    : phase === 'ended' ? 'The visit has ended.'
                    : 'Waiting for the member to join…'}
                </span>
              </SpaceBetween>
            </div>
          )}
        </div>
        {/* Chime binds meeting audio to this element; it must exist before start(). */}
        <audio ref={audioRef} style={{ display: 'none' }} />
      </SpaceBetween>
    </Modal>
  );
}
