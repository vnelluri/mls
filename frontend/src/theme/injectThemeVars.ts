import { buildThemeCss } from './tokens';

const STYLE_TAG_ID = 'truist-theme-vars';

/**
 * Injects the --truist-* / --status-* CSS custom properties (generated
 * directly from src/theme/tokens.ts) into <head> as a <style> tag on :root.
 * Call once at app startup, before render, so that both Tailwind utility
 * classes (which read tokens.ts via tailwind.config.ts) and raw CSS/SVG
 * consumers (e.g. PipelineCanvas stroke/fill) share the exact same values.
 */
export function injectThemeVars(): void {
  if (document.getElementById(STYLE_TAG_ID)) return;
  const style = document.createElement('style');
  style.id = STYLE_TAG_ID;
  style.textContent = buildThemeCss();
  document.head.appendChild(style);
}
