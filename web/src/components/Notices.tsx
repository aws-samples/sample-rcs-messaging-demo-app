import Alert from '@cloudscape-design/components/alert';
import SpaceBetween from '@cloudscape-design/components/space-between';
import { registry, useRegistry } from '../connections/registry';
import { scrubKeys } from '../connections/resolve';
import type { UnknownBrandNotice } from '../connections/types';

/**
 * Shell-level notices about the brand connections. Rendered below the top
 * navigation and outside the brand session, so a notice stays visible across
 * tab changes and Brand_Switches until the operator dismisses it (R4.6).
 *
 * - The unknown-`brand` notice (R4.5) is built from data: the requested value
 *   and the Brand_Ids of the Available_Connections. No brand literal appears in
 *   this file. The registry shows it at most once per page load, so a
 *   dismissed notice does not come back until the next load.
 * - The Connection_Store notice (R1.9) carries the file name and a reason from
 *   a closed set, never the file's contents.
 *
 * Every string passes through `scrubKeys` with all known keys (R11.5). The
 * Cloudscape Alert dismiss control is a native button, so Tab reaches it and
 * Enter or Space removes the notice.
 */

/** `No brand "<value>" is wired up. Available: a, b` */
export function unknownBrandText(n: UnknownBrandNotice): string {
  const available = n.available.length > 0 ? n.available.join(', ') : 'none';
  return `No brand "${n.requested}" is wired up. Available: ${available}`;
}

export default function Notices() {
  const { unknownBrandNotice, storeNotice } = useRegistry();
  if (!unknownBrandNotice && !storeNotice) return null;

  const keys = registry.allKeys();
  return (
    <SpaceBetween size="xs">
      {unknownBrandNotice && (
        <Alert
          type="warning"
          dismissible
          dismissAriaLabel="Dismiss brand notice"
          onDismiss={() => registry.dismissUnknownBrandNotice()}
        >
          {scrubKeys(unknownBrandText(unknownBrandNotice), keys)}
        </Alert>
      )}
      {storeNotice && (
        <Alert
          type="warning"
          dismissible
          dismissAriaLabel="Dismiss connection file notice"
          onDismiss={() => registry.dismissStoreNotice()}
        >
          {scrubKeys(storeNotice, keys)}
        </Alert>
      )}
    </SpaceBetween>
  );
}
