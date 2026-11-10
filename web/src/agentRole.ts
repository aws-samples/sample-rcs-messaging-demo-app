import type { Brand } from './api';

// What the human on the other end of a live-agent handover is called, per
// brand (content/brand.md liveAgentRole, served by GET /api/brand). The
// fallback mirrors the backend's brand-neutral default, and is what shows until
// the brand load resolves.
const NEUTRAL_ROLE = 'support specialist';

export function agentRole(brand: Brand | null | undefined): string {
  return brand?.liveAgentRole?.trim() || NEUTRAL_ROLE;
}

// The role in Title Case ("Support Specialist"), matching how the backend
// labels a dashboard reply that carries no explicit agent name.
export function agentTitle(brand: Brand | null | undefined): string {
  return agentRole(brand).replace(/\b\w/g, (ch) => ch.toUpperCase());
}

// "a" or "an" for a word, by its first letter ("an advisor", "a concierge").
export function article(word: string): 'a' | 'an' {
  return /^[aeiou]/i.test(word.trim()) ? 'an' : 'a';
}

// The role with its indefinite article, e.g. "an advisor" or "a concierge".
export function aAgentRole(brand: Brand | null | undefined): string {
  const role = agentRole(brand);
  return `${article(role)} ${role}`;
}
