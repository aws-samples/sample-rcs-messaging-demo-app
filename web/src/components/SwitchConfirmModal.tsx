import Modal from '@cloudscape-design/components/modal';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import SpaceBetween from '@cloudscape-design/components/space-between';
import { registry } from '../connections/registry';
import { scrubKeys } from '../connections/resolve';
import type { SwitchGuards } from '../session/BrandSession';

/**
 * Confirmation before a Brand_Switch that would drop work in progress (R7).
 *
 * One dialog covers both cases (R7.5):
 * - a video visit is open: switching ends it for the operator and the member
 *   (R7.1);
 * - the target recipient is in live mode: they stay in live mode and get no
 *   bot replies until released to the bot from the current brand (R7.4).
 *
 * It offers exactly one confirm and one cancel action. The cancel button,
 * Escape and the close button all call `onCancel` (R7.6); the shell then
 * returns focus to the Brand_Picker. While `busy` (the confirm is ending the
 * video visit, up to 5 s), the switch is already committed, so cancel is
 * disabled and a dismiss is ignored.
 */
export interface SwitchConfirmModalProps {
  /** null = closed. */
  guards: SwitchGuards | null;
  /** Brand_Label of the Active_Brand. */
  fromLabel: string;
  /** Brand_Label of the selected Brand_Connection. */
  toLabel: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/** The statements the dialog shows, in order. Empty when nothing is guarded. */
export function switchStatements(guards: SwitchGuards, fromLabel: string, toLabel: string): string[] {
  const out: string[] = [];
  if (guards.video) {
    out.push(
      `Switching from ${fromLabel} to ${toLabel} ends the video visit for both you and the member.`,
    );
  }
  if (guards.live) {
    out.push(
      `${guards.live.recipient} stays in live mode and gets no bot replies until you release them to the bot from ${fromLabel}.`,
    );
  }
  return out;
}

export default function SwitchConfirmModal({
  guards,
  fromLabel,
  toLabel,
  busy = false,
  onConfirm,
  onCancel,
}: SwitchConfirmModalProps) {
  const open = !!guards && (!!guards.video || !!guards.live);
  const keys = open ? registry.allKeys() : [];
  const scrub = (s: string) => scrubKeys(s, keys);
  const statements = open ? switchStatements(guards!, fromLabel, toLabel) : [];
  const confirmText = guards?.video ? 'End visit and switch' : 'Switch brand';

  return (
    <Modal
      visible={open}
      onDismiss={() => {
        if (!busy) onCancel();
      }}
      closeAriaLabel="Cancel switch"
      header={scrub(`Switch from ${fromLabel} to ${toLabel}?`)}
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" disabled={busy} onClick={onCancel}>
              Cancel
            </Button>
            <Button variant="primary" loading={busy} onClick={onConfirm}>
              {confirmText}
            </Button>
          </SpaceBetween>
        </Box>
      }
    >
      <SpaceBetween size="s">
        {statements.map((s) => (
          <Box key={s} variant="p">
            {scrub(s)}
          </Box>
        ))}
      </SpaceBetween>
    </Modal>
  );
}
