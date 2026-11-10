import { forwardRef, useImperativeHandle, useMemo, useRef } from 'react';
import Select, { SelectProps } from '@cloudscape-design/components/select';
import type { BrandConnection } from '../connections/types';
import { brandLabel } from '../connections/resolve';

// The Brand_Picker in the top navigation (design C6, R3). It is a controlled
// Cloudscape Select: the shell owns which brand is active and decides whether
// a switch needs a confirmation first, so this component only reports what
// the operator picked. Cloudscape provides the Tab stop, Enter/Space to open,
// arrow keys, Enter to choose, Escape to close and aria-selected (R3.4, R3.7).

/** What the shell knows about one connection's `GET /api/brand` result. */
export interface BrandLabelEntry {
  /** `brandName` from the last successful `GET /api/brand`. */
  name?: string;
  /** True when the last `GET /api/brand` failed or timed out. */
  unreachable?: boolean;
}

/** Label cache, keyed by connection id (Brand_Id or LEGACY_ID). */
export type BrandLabels = Record<string, BrandLabelEntry>;

export interface BrandPickerProps {
  /** Available_Connections, already in Brand_Id order. */
  connections: BrandConnection[];
  /** Id of the Active_Brand's connection. */
  activeId: string;
  /** Loaded labels and reachability per connection id. */
  labels: BrandLabels;
  /** Called with the picked connection id; never called for the active entry. */
  requestSwitch: (id: string) => void;
}

/** Handle the shell uses to return focus to the picker (R7.6). */
export interface BrandPickerHandle {
  focus(): void;
}

const KEY_MISSING_TAG = 'API key missing';
const UNREACHABLE_TAG = 'Unreachable';

function toOption(c: BrandConnection, entry: BrandLabelEntry | undefined): SelectProps.Option {
  const unreachable = !!entry?.unreachable;
  const tags: string[] = [];
  if (!c.apiKey) tags.push(KEY_MISSING_TAG);
  if (unreachable) tags.push(UNREACHABLE_TAG);
  return {
    value: c.id,
    // An unreachable entry falls back to the Brand_Id (R3.6), so the loaded
    // name is ignored until a later load clears the flag.
    label: brandLabel(c, unreachable ? undefined : entry),
    ...(tags.length ? { tags } : {}),
  };
}

const BrandPicker = forwardRef<BrandPickerHandle, BrandPickerProps>(function BrandPicker(
  { connections, activeId, labels, requestSwitch },
  ref,
) {
  const selectRef = useRef<SelectProps.Ref>(null);
  useImperativeHandle(ref, () => ({ focus: () => selectRef.current?.focus() }), []);

  const options = useMemo(
    () => connections.map((c) => toOption(c, labels[c.id])),
    [connections, labels],
  );
  // Always derived from activeId, so the selection moves only when the shell
  // actually starts a switch (R3.4, R7.6).
  const selectedOption = options.find((o) => o.value === activeId) ?? null;

  return (
    <Select
      ref={selectRef}
      ariaLabel="Brand"
      options={options}
      selectedOption={selectedOption}
      onChange={({ detail }) => {
        const id = detail.selectedOption.value;
        // Picking the active entry just closes the dropdown (R3.9).
        if (!id || id === activeId) return;
        requestSwitch(id);
      }}
    />
  );
});

export default BrandPicker;
