import Popover from '@cloudscape-design/components/popover';
import Box from '@cloudscape-design/components/box';
import Link from '@cloudscape-design/components/link';
import SpaceBetween from '@cloudscape-design/components/space-between';
import type { RcsFeature } from '../api';

// The teaching surface on every vignette card. Each feature tag is a popover
// carrying the explanation, the documented limits, a guidance note, and a link
// into the AWS End User Messaging user guide.
//
// Nothing here is written in this file: every word comes from
// content/rcs-features.json via /api/vignettes, so keeping the dashboard current
// with an evolving service is a JSON edit, not a React edit. See
// docs/updating-rcs-content.md.

const KIND_LABEL: Record<RcsFeature['kind'], string> = {
  'rcs-api': 'RCS feature',
  'demo-pattern': 'Demo pattern',
  caveat: 'Guidance',
};

// A demo pattern is something this project invented; an RCS feature is something
// the service provides. Colouring them differently matters because a builder
// evaluating RCS needs to know which is which before they quote it to anyone.
const KIND_COLOR: Record<RcsFeature['kind'], 'text-body-secondary' | 'text-status-info' | 'text-status-warning'> = {
  'rcs-api': 'text-status-info',
  'demo-pattern': 'text-body-secondary',
  caveat: 'text-status-warning',
};

const STATUS_NOTE: Record<RcsFeature['status'], string | null> = {
  demonstrated: null,
  'not-demonstrated': 'Supported by AWS End User Messaging, not shown in this demo.',
  'planned-by-aws': 'Documented by AWS as planned — not available yet.',
};

function formatLimit(value: number, unit?: string): string {
  return `${value.toLocaleString()}${unit ? ` ${unit}` : ''}`;
}

export default function FeatureTag({ feature }: { feature: RcsFeature }) {
  const statusNote = STATUS_NOTE[feature.status];
  return (
    <Popover
      triggerType="text"
      size="large"
      dismissAriaLabel="Close"
      header={feature.name}
      content={
        <SpaceBetween size="xs">
          <Box fontSize="body-s" color="text-body-secondary">
            {KIND_LABEL[feature.kind]}
          </Box>
          <Box>{feature.blurb}</Box>
          {feature.apiShape && (
            <Box variant="code" fontSize="body-s">
              {feature.apiShape}
            </Box>
          )}
          {feature.gotcha && (
            <Box>
              <Box variant="strong" display="inline">
                Keep in mind:{' '}
              </Box>
              {feature.gotcha}
            </Box>
          )}
          {!!feature.limits?.length && (
            <Box>
              <Box variant="strong" display="inline">
                Documented limits:{' '}
              </Box>
              {feature.limits
                .map((l) => `${l.label} ${formatLimit(l.value, l.unit)}`)
                .join(' · ')}
            </Box>
          )}
          {statusNote && (
            <Box fontSize="body-s" color="text-status-warning">
              {statusNote} {feature.statusNote}
            </Box>
          )}
          {!statusNote && feature.statusNote && (
            <Box fontSize="body-s" color="text-body-secondary">
              {feature.statusNote}
            </Box>
          )}
          {feature.docUrl && (
            <Link href={feature.docUrl} external externalIconAriaLabel="Opens in a new tab">
              AWS documentation
            </Link>
          )}
        </SpaceBetween>
      }
    >
      <Box color={KIND_COLOR[feature.kind]} fontSize="body-s" display="inline">
        {feature.name}
        {feature.status !== 'demonstrated' && ' *'}
      </Box>
    </Popover>
  );
}
