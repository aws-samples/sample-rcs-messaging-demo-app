import Popover from '@cloudscape-design/components/popover';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Link from '@cloudscape-design/components/link';

// Each panel ends with the AWS page that documents the mechanism it describes,
// so a builder can check the transport claim rather than take it on trust.
const DOC = 'https://docs.aws.amazon.com/sms-voice/latest/userguide/';
function DocLink({ path, label }: { path: string; label: string }) {
  return (
    <Box fontSize="body-s">
      <Link href={DOC + path} external externalIconAriaLabel="Opens in a new tab">
        {label}
      </Link>
    </Box>
  );
}

// Explains the PII/PHI trade-off to whoever's watching the demo — this is
// guidance for the demo operator/audience, not something shown to an actual RCS
// recipient. 'native' and 'webview' are the two inbound rich-media vignettes;
// 'outbound' is the same decision for a document the agent sends. See
// lambda/flows/photo_submission.py, insurance_upload.py and pharmacy.py for the
// matching server-side rationale.
const COPY: Record<'native' | 'webview' | 'outbound', { title: string; body: React.ReactNode }> = {
  native: {
    title: 'Why this demo is NOT intended for photos that may contain PII or PHI',
    body: (
      <SpaceBetween size="xs">
        <Box>
          This vignette sends the photo natively through the RCS message thread —
          the file bytes transit the public carrier/RCS network on the way to AWS.
        </Box>
        <Box>
          That's fine for generic photos, but it's
          <Box variant="strong" display="inline"> not the right pattern for anything that could
          contain PII</Box> (invoice, statement, photo of a driver's license, etc) or
          <Box variant="strong" display="inline"> PHI</Box> (a symptom photo, an insurance card, a
          medical report) because the carrier/aggregator hop is outside AWS's HIPAA BAA and
          outside your control.
        </Box>
        <Box>
          <Box variant="strong" display="inline">Secure Document Upload</Box> shows the
          alternative: the file stays off the RCS thread entirely. It is a demo too, so
          use sample images there as well.
        </Box>
        <DocLink path="rcs-inbound-media.html" label="AWS docs: receiving inbound RCS media" />
        <DocLink path="rcs-overview.html" label="AWS docs: RCS overview and Google's role in delivery" />
      </SpaceBetween>
    ),
  },
  webview: {
    title: "What the upload webview protects, and what it doesn't",
    body: (
      <SpaceBetween size="xs">
        <Box>
          This vignette sends only a link over RCS. Tapping it opens a web page
          in the messaging app, and the file uploads directly from that browser
          to a private S3 bucket via a presigned URL — the bytes never enter the
          message thread or the carrier/RCS messaging path. They travel over
          HTTPS between the browser and S3.
        </Box>
        <Box>
          Choosing that transport is one control, and the one this vignette
          demonstrates: the file stays out of the RCS message path. On its own
          it does not make a flow safe for real PHI.
        </Box>
        <Box>
          <Box variant="strong" display="inline">In this demo the upload page is
          not authenticated</Box> — the in-app browser can't hold an API key, so
          the link carries only a conversation hash (a truncated, unsalted
          SHA-256 of the phone number, which anyone who knows the number can
          compute), and the page URL never expires. Only the presigned upload
          URL the page requests is time-limited (10 minutes). Real PHI needs a
          member-verified session on that route, per-member object keys, and an
          access log of every fetch. Use a sample image, not a real document.
        </Box>
        <Box>
          It also accepts iPhone's default HEIC photos — HEIC/HEIF is not on
          AWS's list of accepted inbound RCS media types — and a Lambda converts
          them to JPEG server-side.
        </Box>
        <DocLink
          path="rcs-suggestions.html#rcs-suggestions-openurl"
          label="AWS docs: OpenUrl suggestions and webviews"
        />
      </SpaceBetween>
    ),
  },
  outbound: {
    title: 'Sending documents: which one may go over RCS, and which may not',
    body: (
      <SpaceBetween size="xs">
        <Box>
          Tap <Box variant="strong" display="inline">Rx Documents</Box> on the
          confirmation card and this vignette sends two documents by two different
          transports, on purpose.
        </Box>
        <Box>
          <Box variant="strong" display="inline">Magic Medicine Facts</Box> goes as
          a <Box variant="strong" display="inline">FileMessage</Box>. AWS downloads
          the PDF from your S3 bucket, rehosts it and presigns it for the
          aggregator, so those bytes leave your account and cross the carrier/RCS
          network with Google in the delivery chain. That is acceptable here only
          because the file is generic drug information — byte-identical for every
          member, with no name, address, prescriber or directions in it.
        </Box>
        <Box>
          The <Box variant="strong" display="inline">member's prescription record</Box>{' '}
          is never sent as a message. The file message carries a WEBVIEW suggestion
          that opens a page in the messaging app; that page requests a 300-second
          presigned URL and the browser fetches the PDF straight from private S3
          over HTTPS. Nothing about the member enters the message stream.
        </Box>
        <Box>
          The bucket policy and the channel adapter's role make that structural
          rather than a matter of discipline: the RCS service principal can read
          only{' '}
          <Box variant="strong" display="inline">media/</Box> and the inbound
          prefixes, and the service reads a file-message object using the
          adapter role's s3:GetObject grant, which covers just those three
          prefixes. On a test deployment a file message naming the{' '}
          <Box variant="strong" display="inline">secure-docs/</Box> key, and one
          naming a member photo, were refused with RESOURCE_NOT_ACCESSIBLE; treat
          that as an observation from this sample's testing, not a guarantee.
        </Box>
        <Box>
          <Box variant="strong" display="inline">Transport is one control, not all
          of them.</Box> As with the upload page, this webview is not
          authenticated, and the conversation hash in its URL is an unsalted hash
          of the phone number. Real PHI needs a member-verified session on that
          route, per-member object keys, and an access log of every fetch.
        </Box>
        <DocLink path="rcs-file-messages.html" label="AWS docs: sending RCS file messages" />
        <DocLink
          path="rcs-suggestions.html#rcs-suggestions-openurl"
          label="AWS docs: OpenUrl suggestions and webviews"
        />
      </SpaceBetween>
    ),
  },
};

export default function PiiGuidanceTooltip({ variant }: { variant: 'native' | 'webview' | 'outbound' }) {
  const { title, body } = COPY[variant];
  return (
    <Popover
      triggerType="text"
      size="large"
      dismissAriaLabel="Close"
      header={title}
      content={body}
    >
      <Box color="text-status-info" fontSize="body-s" display="inline">
        ⓘ PII/PHI guidance
      </Box>
    </Popover>
  );
}
