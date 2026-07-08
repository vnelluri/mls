import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'node:path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['src/test/setup.ts'],
    // Testing Library's automatic between-test cleanup registers itself via
    // the global afterEach; without globals, renders leak across tests.
    globals: true,
    // Tests must not inherit the developer's local .env (VITE_DEMO_MODE=true
    // there would silently flip the api client into demo mode). Tests that
    // need demo mode stub it explicitly with vi.stubEnv.
    env: {
      VITE_DEMO_MODE: 'false',
      VITE_API_BASE_URL: 'http://testserver',
    },
  },
});
