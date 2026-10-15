import Modal from '@cloudscape-design/components/modal';
import Box from '@cloudscape-design/components/box';

/**
 * Full-size viewer for media previews in the operator dashboard. The caller
 * supplies an already-authorized/presigned image URL, so this component never
 * fetches data itself or creates a second media-access path.
 */
export default function ImagePreviewModal({
  image,
  onDismiss,
}: {
  image: { src: string; alt: string } | null;
  onDismiss: () => void;
}) {
  return (
    <Modal
      visible={!!image}
      onDismiss={onDismiss}
      size="large"
      header={image?.alt || 'Image preview'}
    >
      {image ? (
        <div style={{ display: 'flex', justifyContent: 'center', background: '#111827', borderRadius: 8, padding: 12 }}>
          <img
            src={image.src}
            alt={image.alt}
            style={{ display: 'block', maxWidth: '100%', maxHeight: '72vh', objectFit: 'contain', borderRadius: 4 }}
          />
        </div>
      ) : (
        <Box color="text-body-secondary">No image available.</Box>
      )}
    </Modal>
  );
}
