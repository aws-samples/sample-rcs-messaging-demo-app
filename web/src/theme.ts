import { applyTheme, Theme } from '@cloudscape-design/components/theming';

// This demo's accent color is per-deployment (content/brand.md ->
// GET /api/brand -> accentColor) and isn't known until the app loads.
//
// Cloudscape's *runtime theming* API (applyTheme) is built for that case:
// "Use runtime theming only if your application allows each customer to
// define their own theme" — see
// https://cloudscape.design/foundation/visual-foundation/theming/
//
// We map the single accentColor onto the handful of tokens that drive
// "brand color" across primary buttons, links, and the chat bubble accent,
// so every Cloudscape component (Button, Badge, Alert links, etc.) picks it
// up automatically instead of it being prop-drilled per component instance.
let currentReset: (() => void) | null = null;

// The neutral default accent: the only colour literal in the UI. It applies
// until an Active_Brand's `GET /api/brand` supplies a valid one.
export const DEFAULT_ACCENT = '#0B6E6F';

// The neutral title used in the top bar and the browser tab until a brand
// name has loaded: the project's name.
export const DEFAULT_TITLE = 'AWS End User Messaging RCS Demo Catalog';

// Appended to a loaded brand's name in the browser tab ("AnyHealth RCS Demo").
const BRAND_TITLE_SUFFIX = 'RCS Demo';

let currentAccent = DEFAULT_ACCENT;

// The accent to apply for a brand: its `accentColor` exactly when it is a
// `#RRGGBB` hex colour, otherwise the neutral default (R8.1, R8.4).
export function accentFor(brand: { accentColor?: string | null } | null | undefined): string {
  const c = brand?.accentColor ?? '';
  return /^#[0-9A-Fa-f]{6}$/.test(c) ? c : DEFAULT_ACCENT;
}

// The browser tab title. The operator is usually looking at their phone, not
// the dashboard, when a handover fires, so live mode puts it in the tab title
// too. The " RCS Demo" suffix is added only once a real brand name exists;
// before that the tab shows the neutral title alone (R8.2, R8.5, R8.6).
export function documentTitle(name: string | null | undefined, live: boolean): string {
  const brandName = name || DEFAULT_TITLE;
  return live
    ? `🔴 Live agent needed — ${brandName}`
    : name ? `${name} ${BRAND_TITLE_SUFFIX}` : brandName;
}

// The accent color is tracked here so the one UI element with no Cloudscape
// equivalent — chat bubbles in Conversations.tsx — can use the raw color for
// its custom background, without duplicating brand-fetch logic or hardcoding
// a color.
export function getAccentColor(): string {
  return currentAccent;
}

export function applyBrandTheme(accentColor: string): void {
  currentAccent = accentColor;
  currentReset?.();

  const theme: Theme = {
    tokens: {
      colorBackgroundButtonPrimaryDefault: accentColor,
      colorBackgroundButtonPrimaryHover: accentColor,
      colorBackgroundButtonPrimaryActive: accentColor,
      colorBorderButtonPrimaryDefault: accentColor,
      colorBorderButtonPrimaryHover: accentColor,
      colorBorderButtonPrimaryActive: accentColor,
      colorTextAccent: accentColor,
      colorTextLinkDefault: accentColor,
      colorTextLinkHover: accentColor,
      colorBackgroundChatBubbleOutgoing: accentColor,
    },
  };

  currentReset = applyTheme({ theme }).reset;
}
