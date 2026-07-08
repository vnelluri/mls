/**
 * Truist brand design tokens — SINGLE SOURCE OF TRUTH.
 *
 * tailwind.config.js reads this file directly (via require at config-eval
 * time) and theme.css.ts generates the raw CSS custom properties from the
 * same values, so the hex values are only ever written once, here.
 */

export const truistColors = {
  purple: '#2e1a47',
  white: '#ffffff',
  dusk: '#7c6992',
  dawn: '#afabc9',
  charcoal: '#34363b',
  darkGray: '#707070',
  midGray: '#a8a8a8',
  lightGray: '#c9c9c9',
  skyBlue: '#b0e0e2',
  tint07: '#e3dfef',
  tint08: '#f6f3f9',
  gray06: '#ededed',
  gray07: '#f7f7f7',
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
