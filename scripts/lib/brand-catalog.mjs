/**
 * Shared helpers for the agent scripts: read the brand catalog from
 * `content/brand.md` and check one brand's identity block against the limits of
 * the RCS testing-agent registration form.
 *
 * Pure and offline except `readCatalog` (reads two files).
 */
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join } from 'node:path';

/** A Brand_Id: lowercase letter, then up to 31 lowercase letters, digits or `-`. */
export function isValidBrandId(s) {
  return typeof s === 'string' && /^[a-z][a-z0-9-]{0,31}$/.test(s);
}

/** Region such as `us-east-1`. */
export function isValidRegion(s) {
  // One character class and no nested quantifier, so the match is linear; the
  // `--` check rejects the empty segments the class would otherwise allow.
  return typeof s === 'string' && /^[a-z]{2}-[a-z-]+-\d+$/.test(s) && !s.includes('--');
}

/** RCS agent id such as `rcs-0123...` (32 hex digits). */
export function isValidAgentId(s) {
  return typeof s === 'string' && /^rcs-[0-9a-f]{32}$/.test(s);
}

/**
 * Resource-name prefix from a brand name. Mirrors `slugify` in
 * `cdk/lib/brand-selection.ts` exactly (including its fallback), so the stack
 * name computed here is the one `cdk deploy` creates.
 */
export function slugify(name) {
  return (
    String(name)
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 20) || 'anyhealth'
  );
}

function isPlainObject(v) {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}

/** Read `content/brand.md`. Returns `{ brands, defaultBrand }` or `{ error }`. */
export function readCatalog(root) {
  let YAML;
  try {
    YAML = createRequire(join(root, 'cdk', 'package.json'))('yaml');
  } catch {
    return { error: 'the yaml package is not installed in cdk/; run `(cd cdk && npm ci)` first' };
  }
  let fm = {};
  try {
    const raw = readFileSync(join(root, 'content', 'brand.md'), 'utf8');
    const m = raw.match(/^---\n([\s\S]*?)\n---/);
    fm = (m && YAML.parse(m[1])) || {};
  } catch {
    return { error: 'could not parse the frontmatter of content/brand.md' };
  }
  const defaultBrand =
    typeof fm.defaultBrand === 'string' && fm.defaultBrand.trim() ? fm.defaultBrand.trim() : 'anyhealth';
  const brands = isPlainObject(fm.brands) ? fm.brands : { [defaultBrand]: fm };
  return { brands, defaultBrand };
}

/** WCAG contrast ratio of `#RRGGBB` against white, or NaN for a bad colour. */
export function contrastOnWhite(hex) {
  const m = /^#([0-9a-fA-F]{6})$/.exec(hex ?? '');
  if (!m) return NaN;
  const lin = [0, 2, 4].map((i) => {
    const c = parseInt(m[1].slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  const lum = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
  return 1.05 / (lum + 0.05);
}

/** Width, height and alpha flag of a PNG buffer, or `null` when it is not a PNG. */
export function pngInfo(buf) {
  const sig = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  if (!buf || buf.length < 26 || !buf.subarray(0, 8).equals(sig)) return null;
  const colorType = buf[25];
  return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20), alpha: colorType === 4 || colorType === 6 };
}

const USE_CASES = ['OTP', 'TRANSACTIONAL', 'PROMOTIONAL', 'MULTI_USE'];
const FREQUENCIES = ['10', '100', '1000+'];

/** Text fields: `[key, min, max]` length bounds of the registration form. */
const TEXT_LIMITS = [
  ['brandName', 2, 100],
  ['serviceName', 1, 100],
  ['senderDisplayName', 1, 40],
  ['agentDescription', 5, 100],
];

/** Contact value/label pairs; at least one complete pair is required. */
export const CONTACT_PAIRS = [
  ['contactPhoneNumber', 'contactPhoneLabel'],
  ['contactEmailAddress', 'contactEmailLabel'],
  ['contactWebsite', 'contactWebsiteLabel'],
];

/**
 * Check one brand block against the registration form's limits. `readFile` is
 * injectable so tests need no media files. Returns `{ errors, warnings }`
 * (arrays of strings that name the brand key, never a secret).
 */
export function validateBlock(brand, block, { root = '.', readFile = (p) => readFileSync(p) } = {}) {
  const errors = [];
  const warnings = [];
  if (!isPlainObject(block)) return { errors: [`brands.${brand} is not an identity block`], warnings };
  const str = (k) => (typeof block[k] === 'string' ? block[k].trim() : '');
  for (const [k, min, max] of TEXT_LIMITS) {
    const n = str(k).length;
    if (n < min || n > max) errors.push(`brands.${brand}.${k} must be ${min}-${max} characters (it is ${n})`);
  }
  if (!USE_CASES.includes(str('useCase'))) errors.push(`brands.${brand}.useCase must be one of ${USE_CASES.join(', ')}`);
  if (!FREQUENCIES.includes(str('averageMonthlyRcsFrequency')))
    errors.push(`brands.${brand}.averageMonthlyRcsFrequency must be one of ${FREQUENCIES.join(', ')}`);
  if (!/^[1-9][0-9]{0,5}$/.test(str('monthlyRcsVolume')))
    errors.push(`brands.${brand}.monthlyRcsVolume must be a whole number from 1 to 999999`);
  const ratio = contrastOnWhite(str('accentColor'));
  if (Number.isNaN(ratio)) errors.push(`brands.${brand}.accentColor must look like #RRGGBB`);
  else if (ratio < 4.5) errors.push(`brands.${brand}.accentColor has contrast ${ratio.toFixed(1)}:1 against white; it needs at least 4.5:1`);
  for (const k of ['privacyPolicyUrl', 'termsAndConditionsUrl']) {
    if (!/^https:\/\/[^\s/]+\.[^\s/]+(\/\S*)?$/.test(str(k))) errors.push(`brands.${brand}.${k} must be an https URL`);
  }
  if (!CONTACT_PAIRS.some(([v, l]) => str(v) && str(l)))
    errors.push(`brands.${brand} needs at least one contact value with its label (phone, email or website)`);
  for (const [v, l] of CONTACT_PAIRS) {
    if (Boolean(str(v)) !== Boolean(str(l))) errors.push(`brands.${brand}.${v} and ${l} must be set together`);
  }
  if (str('contactWebsite') && !/^https:\/\//.test(str('contactWebsite'))) errors.push(`brands.${brand}.contactWebsite must be an https URL`);
  if (str('contactPhoneNumber') && !/^\+[1-9][0-9]{7,14}$/.test(str('contactPhoneNumber')))
    errors.push(`brands.${brand}.contactPhoneNumber must be E.164 (for example +18005550100)`);
  if (str('contactEmailAddress') && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(str('contactEmailAddress')))
    errors.push(`brands.${brand}.contactEmailAddress is not a valid email address`);
  const media = [
    ['logoImage', 224, 224, 50 * 1024, true],
    ['bannerImage', 1440, 448, 200 * 1024, false],
  ];
  for (const [k, w, h, max, needAlpha] of media) {
    const rel = str(k);
    if (!rel) {
      errors.push(`brands.${brand}.${k} is required`);
      continue;
    }
    let buf;
    try {
      buf = readFile(join(root, rel));
    } catch {
      errors.push(`brands.${brand}.${k}: the file ${rel} cannot be read`);
      continue;
    }
    if (buf.length > max) errors.push(`${rel} is ${Math.ceil(buf.length / 1024)} KB; the limit is ${max / 1024} KB`);
    const info = pngInfo(buf);
    if (!info) warnings.push(`${rel} is not a PNG; the size and format limits were not checked`);
    else {
      if (info.width !== w || info.height !== h) errors.push(`${rel} is ${info.width}x${info.height}; it must be ${w}x${h}`);
      if (needAlpha && !info.alpha) warnings.push(`${rel} has no transparency channel; the logo is expected to have one`);
    }
  }
  return { errors, warnings };
}
