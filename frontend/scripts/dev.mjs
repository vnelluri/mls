// Local dev bootstrapper — NO DOCKER. Reads VITE_API_BASE_URL from .env,
// confirms the backend is actually reachable, then hands off to Vite.
// This exists because starting the frontend against a backend that isn't
// running yet produces confusing, silent failures deep in page components —
// far better to fail fast here with a clear, actionable message.

import { readFileSync, existsSync, copyFileSync } from 'node:fs';
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(__dirname, '..');
const envPath = path.join(rootDir, '.env');
const envExamplePath = path.join(rootDir, '.env.example');

function ensureEnvFile() {
  if (!existsSync(envPath)) {
    if (existsSync(envExamplePath)) {
      copyFileSync(envExamplePath, envPath);
      console.log('[dev] Created .env from .env.example');
    } else {
      console.warn('[dev] No .env or .env.example found — proceeding with defaults.');
    }
  }
}

/** Minimal manual .env parser — one KEY=VALUE per line, no quoting/escaping
 * support needed for the handful of values this project uses. */
function readEnvValue(key, fallback) {
  if (!existsSync(envPath)) return fallback;
  const lines = readFileSync(envPath, 'utf-8').split('\n');
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const eq = trimmed.indexOf('=');
    if (eq === -1) continue;
    const k = trimmed.slice(0, eq).trim();
    if (k === key) {
      return trimmed.slice(eq + 1).trim();
    }
  }
  return fallback;
}

async function waitForBackend(healthUrl, timeoutMs) {
  const start = Date.now();
  let lastError = null;
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(healthUrl, { signal: AbortSignal.timeout(2000) });
      if (res.ok) return true;
      lastError = new Error(`Received HTTP ${res.status}`);
    } catch (err) {
      lastError = err;
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  console.error(lastError ? `[dev] Last error: ${lastError.message}` : '');
  return false;
}

async function main() {
  ensureEnvFile();

  const apiBaseUrl = readEnvValue('VITE_API_BASE_URL', 'http://localhost:8000');
  const healthUrl = `${apiBaseUrl.replace(/\/$/, '')}/health`;

  console.log(`[dev] Checking backend health at ${healthUrl} …`);
  const reachable = await waitForBackend(healthUrl, 10_000);

  if (!reachable) {
    console.error('');
    console.error(
      `Can't reach the backend at ${healthUrl} — start the backend first: cd ../backend && python scripts/dev.py — then re-run this script.`,
    );
    console.error('');
    process.exit(1);
  }

  console.log('[dev] Backend is reachable. Starting Vite…');
  const vite = spawn('npx', ['vite'], { stdio: 'inherit', shell: true, cwd: rootDir });
  vite.on('exit', (code) => process.exit(code ?? 0));
}

main().catch((err) => {
  console.error('[dev] Unexpected error while starting the dev environment:', err);
  process.exit(1);
});
