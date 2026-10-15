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
let currentAccent = '#0B6E6F';

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
