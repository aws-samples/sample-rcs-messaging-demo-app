import Modal from '@cloudscape-design/components/modal';
import Button from '@cloudscape-design/components/button';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import { Vignette } from '../api';

/**
 * The reveal behind a Mystery Box card. The card face on the Interactive Demos
 * tab shows no name, description or preview -- only a single "." in its corner.
 * Tapping it opens this modal, which discloses what the box actually is (the
 * vignette's real name and description, the same copy the Settings ->
 * Diagnostics & experiments section shows) and lets the operator send it to the
 * current target device.
 *
 * Deliberately no device preview here: the whole point of a Mystery Box is that
 * you don't see the contents until you open it, and previewing on the card face
 * would give the surprise away. Sending is the one action offered.
 */
export default function MysteryBoxModal({
  vignette,
  phone,
  currentLabel,
  busy,
  onSend,
  onDismiss,
}: {
  // null = closed. Non-null = open, revealing this vignette.
  vignette: Vignette | null;
  phone: string;
  currentLabel: string;
  busy: boolean;
  onSend: (trigger: string) => void;
  onDismiss: () => void;
}) {
  return (
    <Modal
      visible={!!vignette}
      onDismiss={onDismiss}
      size="medium"
      header="Mystery Box revealed"
    >
      {vignette && (
        <SpaceBetween size="m">
          <Box variant="h3">{vignette.name}</Box>
          <Box color="text-body-secondary">{vignette.description}</Box>
          <SpaceBetween direction="horizontal" size="s" alignItems="center">
            <Button
              variant="primary"
              disabled={!phone}
              loading={busy}
              onClick={() => onSend(vignette.trigger)}
            >
              {phone ? `Send to ${currentLabel}` : 'Send to target device'}
            </Button>
            {!phone && (
              <Box color="text-body-secondary" fontSize="body-s">
                Select a target recipient above to enable sending.
              </Box>
            )}
          </SpaceBetween>
        </SpaceBetween>
      )}
    </Modal>
  );
}
