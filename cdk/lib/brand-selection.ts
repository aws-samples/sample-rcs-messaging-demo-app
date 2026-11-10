/**
 * Pure, CDK- and synth-free brand-selection helpers.
 *
 * This module deliberately imports nothing from `aws-cdk-lib`, `fs`, or any
 * synth machinery, so both functions can be unit- and property-tested in
 * isolation (see design §3 "CDK selected-brand model"). `config.ts` imports
 * `slugify` from here rather than defining its own copy, so the one resource
 * prefix is derived the same way everywhere.
 */

/**
 * Resolve the deploy-time brand selection to exactly ONE catalog id.
 *
 * The CDK context flag `-c brand=<id>` names exactly one brand to stand up.
 * Resolution is:
 *
 *   - case-insensitive and trimmed — `"  AnyWealth "` selects `anywealth`;
 *   - empty or unset (`undefined`, `null`, `""`, all-whitespace) → `defaultBrand`;
 *   - a value naming more than one brand (any internal whitespace or comma,
 *     e.g. `"anyhealth,anytravel"` or `"anyhealth anytravel"`) is rejected — the
 *     flag selects exactly one brand, never a set;
 *   - an id that is not a key in `catalogIds` throws, naming the offending id
 *     and listing the valid ids.
 *
 * It throws before anything else runs, so an unknown or multi-valued selection
 * stops the deploy before any resource is built or any AWS lookup is made.
 *
 * @param raw          the raw `-c brand=` value (or undefined/null when unset)
 * @param catalogIds   the brand ids defined in the source of truth
 * @param defaultBrand the id to select when `raw` is empty/unset (R2.2)
 * @returns the single selected id (always a member of `catalogIds`)
 */
export function parseBrandSelection(
  raw: string | undefined | null,
  catalogIds: readonly string[],
  defaultBrand: string,
): string {
  const trimmed = (raw ?? '').trim();

  // Empty/unset → default (R2.2).
  if (trimmed === '') return defaultBrand;

  const normalized = trimmed.toLowerCase();

  // The flag selects exactly one brand (R2.3). Any internal whitespace or
  // comma means the value names more than one brand, which is rejected rather
  // than silently taking the first.
  if (/[\s,]/.test(normalized)) {
    throw new Error(
      `brand must name exactly one brand (got "${raw}"). The -c brand= flag selects a ` +
        `single brand to stand up, not a set. Valid ids: ${formatValidIds(catalogIds)}.`,
    );
  }

  // Unknown id → throw naming it and listing the valid ids (R2.4), before any
  // resource or AWS lookup.
  if (!catalogIds.includes(normalized)) {
    throw new Error(
      `Unknown brand "${trimmed}". The -c brand= flag must name a brand defined in ` +
        `content/brand.md. Valid ids: ${formatValidIds(catalogIds)}.`,
    );
  }

  return normalized;
}

/** Render the catalog ids as a stable, comma-separated list for error text. */
function formatValidIds(catalogIds: readonly string[]): string {
  return catalogIds.length ? catalogIds.join(', ') : '(none defined)';
}

/**
 * Derive the single resource-name prefix from a brand name.
 *
 * Deterministic: the same name always yields the same slug, so renaming the
 * selected brand in content/brand.md changes the derived prefix on the next
 * synth (R4.3). Lower-cases, collapses every run of non-alphanumeric characters
 * to a single `-`, trims leading/trailing `-`, caps at 20 characters, and falls
 * back to `anyhealth` when nothing is left. No set, no collision helper, no
 * capacity math — exactly the behavior config.ts used before this helper was
 * extracted.
 */
export function slugify(name: string): string {
  return (
    name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 20) || 'anyhealth'
  );
}
