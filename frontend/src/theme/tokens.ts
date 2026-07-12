/**
 * Truist brand design tokens — SINGLE SOURCE OF TRUTH.
 *
 * tailwind.config.js reads this file directly (via require at config-eval
 * time) and theme.css.ts generates the raw CSS custom properties from the
 * same values, so the hex values are only ever written once, here.
 *
 * The token NAMES are the historical Truist palette names; the VALUES now
 * follow the TMT light theme (see ~/tmt/frontend/tailwind.config.ts) so both
 * platforms share one look. Semantic mapping:
 *   purple   → brand accent (buttons, links, active nav) — reads on white
 *   valhalla → dark brand surface (topbar, login hero) only
 *   charcoal/darkGray/midGray → text primary/secondary/muted
 *   tint08 → page bg, tint07/gray06 → elevated fills & borders
 *   skyBlue → focus ring (now brand purple, name kept to avoid a mass rename)
 */

export const truistColors = {
  purple: '#6c63c5',
  valhalla: '#2e1a47',
  white: '#ffffff',
  dusk: '#5b53b0',
  dawn: '#a6a3e0',
  charcoal: '#241e3d',
  darkGray: '#5a5280',
  midGray: '#8d86ad',
  lightGray: '#d9d5ea',
  skyBlue: '#6c63c5',
  tint07: '#e8e5f2',
  tint08: '#f4f3fa',
  gray06: '#e8e5f2',
  gray07: '#edebf5',
} as const;

export const statusColors = {
  passed: '#19a84e',
  failed: '#e61f00',
  rework: '#ffa329',
  inReview: '#45b0e6',
  notStarted: '#a8a8a8',
} as const;

export type TruistColorName = keyof typeof truistColors;
export type StatusColorName = keyof typeof statusColors;

/** Builds the CSS custom-property text block consumed by theme.css. */
export function buildThemeCss(): string {
  const truistVars = Object.entries(truistColors)
    .map(([name, hex]) => `  --truist-${kebab(name)}: ${hex};`)
    .join('\n');
  const statusVars = Object.entries(statusColors)
    .map(([name, hex]) => `  --status-${kebab(name)}: ${hex};`)
    .join('\n');

  return `:root {\n${truistVars}\n${statusVars}\n}\n`;
}

function kebab(name: string): string {
  return name.replace(/([a-z0-9])([A-Z])/g, '$1-$2').toLowerCase();
}
