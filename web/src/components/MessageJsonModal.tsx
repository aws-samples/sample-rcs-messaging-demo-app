import Modal from '@cloudscape-design/components/modal';
import Box from '@cloudscape-design/components/box';
import CopyToClipboard from '@cloudscape-design/components/copy-to-clipboard';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Link from '@cloudscape-design/components/link';
import type { Message } from '../api';

// Classifies an inbound/outbound conversation message the same way the AnyHealth
// dashboard does, so operators see the same vocabulary when discussing how a
// vignette's payload gets built: an outbound message is literally the body
// passed to SendRcsMessage's RcsMessageContent; inbound messages are shown as
// whatever the channel adapter received, labeled by what kind of inbound
// event it was (trigger phrase, suggestion chip tap, or free text).
export function messageJsonLabel(msg: Message): string {
  if (msg.direction === 'outbound') return 'SendRcsMessage REQUEST';
  if (msg.media_content) {
    return msg.media_content.mediaStatus === 'SUCCESS' ? 'MEDIA RECEIVED' : 'MEDIA FAILED';
  }
  const body = msg.body || '';
  if (body.startsWith('Start:')) return 'TRIGGER MESSAGE';
  if (body.startsWith('[Tap]')) return 'SUGGESTION TAP';
  return 'FREE TEXT';
}

// The exact payload to display: outbound messages carry the full RCS content
// dict that was sent (rcs_content, persisted by common.log_message); native
// inbound media carries AWS's own mediaStatus/s3Key/mimeType notification
// (media_content, persisted by common.log_inbound_media); everything else
// falls back to the raw body the channel adapter received.
export function messageJsonContent(msg: Message): unknown {
  if (msg.direction === 'outbound' && msg.rcs_content) return msg.rcs_content;
  if (msg.media_content) return msg.media_content;
  if (msg.body) return { messageBody: msg.body };
  return null;
}

// One sentence explaining the *shape* of what the modal is showing, plus where
// AWS documents it. Builders open this modal to learn the payload, so the shape
// rules go here: exactly one content type per request, and where inbound
// `messageBody` carries a JSON envelope.
const DOC = 'https://docs.aws.amazon.com/sms-voice/latest/userguide/';
function messageJsonNote(msg: Message): { text: string; docUrl: string } {
  if (msg.direction === 'outbound') {
    return {
      text:
        'This is the RcsMessageContent argument to SendRcsMessage. Its Content object holds exactly ' +
        'one of TextMessage, FileMessage, RichCard or Carousel — never two — and message-level ' +
        'Suggestions sit beside Content, not inside it.',
      docUrl: DOC + 'rcs-rich-messaging.html#rcs-rich-messaging-api',
    };
  }
  if (msg.media_content) {
    return {
      text:
        'Inbound media arrives as a JSON envelope inside messageBody; this sample detects it by its ' +
        'mediaStatus field. AWS stores the file for you; this app copies it into its own bucket.',
      docUrl: DOC + 'rcs-inbound-media.html',
    };
  }
  return {
    text:
      'Inbound member traffic arrives in the messageBody field: plain text as-is, or a JSON ' +
      'envelope for a suggestion tap, a shared location, or a typing indicator. Inbound ' +
      'messages never carry an eventType — that is how you tell them from delivery events.',
    docUrl: DOC + 'rcs-inbound.html',
  };
}

export default function MessageJsonModal({
  message,
  visible,
  onDismiss,
}: {
  message: Message | null;
  visible: boolean;
  onDismiss: () => void;
}) {
  const content = message ? messageJsonContent(message) : null;
  const text = content ? JSON.stringify(content, null, 2) : '';
  const note = message ? messageJsonNote(message) : null;

  return (
    <Modal
      visible={visible}
      onDismiss={onDismiss}
      size="medium"
      header={message ? messageJsonLabel(message) : ''}
      footer={
        text && (
          <Box float="right">
            <CopyToClipboard
              copyButtonText="Copy JSON"
              copySuccessText="Copied"
              copyErrorText="Failed to copy"
              textToCopy={text}
            />
          </Box>
        )
      }
    >
      <SpaceBetween size="s">
        {message && (
          <Box color="text-body-secondary" fontSize="body-s">
            {new Date(message.timestamp).toLocaleString()}
          </Box>
        )}
        {note && (
          <Box color="text-body-secondary" fontSize="body-s">
            {note.text}{' '}
            <Link href={note.docUrl} external externalIconAriaLabel="Opens in a new tab">
              AWS documentation
            </Link>
          </Box>
        )}
        {text ? (
          <Box
            fontSize="body-s"
            padding="s"
            variant="pre"
            nativeAttributes={{
              style: {
                display: 'block',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
                maxHeight: '60vh',
                overflow: 'auto',
                background: '#1e1e2e',
                color: '#cdd6f4',
                fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
                borderRadius: 8,
                margin: 0,
              },
            }}
          >
            {text}
          </Box>
        ) : (
          <Box color="text-body-secondary">No payload available for this message.</Box>
        )}
      </SpaceBetween>
    </Modal>
  );
}
