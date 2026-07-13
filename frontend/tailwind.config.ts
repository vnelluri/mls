import type { Config } from 'tailwindcss';
import { truistColors, statusColors } from './src/theme/tokens';

// Tailwind CSS v3.4+ loads TypeScript config files natively (via its bundled
// jiti loader), so this file can import directly from tokens.ts — the single
// source of truth for the Truist palette. Nothing here is hand-duplicated.
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        truist: {
          purple: truistColors.purple,
          valhalla: truistColors.valhalla,
          valhallaDeep: truistColors.valhallaDeep,
          white: truistColors.white,
          dusk: truistColors.dusk,
          dawn: truistColors.dawn,
          charcoal: truistColors.charcoal,
          darkGray: truistColors.darkGray,
          midGray: truistColors.midGray,
          lightGray: truistColors.lightGray,
          skyBlue: truistColors.skyBlue,
          tint07: truistColors.tint07,
          tint08: truistColors.tint08,
          gray06: truistColors.gray06,
          gray07: truistColors.gray07,
        },
        status: {
          passed: statusColors.passed,
          failed: statusColors.failed,
          rework: statusColors.rework,
          inReview: statusColors.inReview,
          notStarted: statusColors.notStarted,
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [],
} satisfies Config;
