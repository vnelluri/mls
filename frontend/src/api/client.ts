import axios, { type AxiosInstance } from 'axios';

const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://localhost:8001';

const DEMO_MODE: boolean = (import.meta.env.VITE_DEMO_MODE as string | undefined) === 'true';

/** Populated by AuthContext once MSAL is initialized (production mode only).
 * May return the token synchronously or as a promise (acquireTokenSilent is
 * async) — the request interceptor awaits it either way. */
type BearerTokenGetter = () => string | null | Promise<string | null>;

let bearerTokenGetter: BearerTokenGetter | null = null;

export function setBearerTokenGetter(getter: BearerTokenGetter): void {
  bearerTokenGetter = getter;
}

/** Demo mode: which cosmetic role the login page selector chose. Purely for
 * local-dev convenience — the backend's dev AUTH_MODE, not this header, is
 * what actually determines the authoritative role from GET /auth/me. */
let demoSelectedRole: string | null = null;

export function setDemoSelectedRole(role: string | null): void {
  demoSelectedRole = role;
  if (role) {
    window.localStorage.setItem('demoSelectedRole', role);
  } else {
    window.localStorage.removeItem('demoSelectedRole');
  }
}

export function getDemoSelectedRole(): string | null {
  if (demoSelectedRole) return demoSelectedRole;
  return window.localStorage.getItem('demoSelectedRole');
}

export const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15000,
});

apiClient.interceptors.request.use(async (config) => {
  if (DEMO_MODE) {
    const role = getDemoSelectedRole();
    if (role) {
      config.headers.set('X-Demo-Role', role);
    }
  } else if (bearerTokenGetter) {
    const token = await bearerTokenGetter();
    if (token) {
      config.headers.set('Authorization', `Bearer ${token}`);
    }
  }
  return config;
});

/** Every error-handling call site in the app follows the same pattern —
 * `err instanceof Error ? err.message : fallback` — so a bare axios error's
 * generic "Request failed with status code 400" is what users see on every
 * failed request, never the backend's actual (useful) explanation. Rewrite
 * the error's `message` in place, here, once: FastAPI's error body is
 * `{"detail": ...}`, either a string (our own bad_request/conflict/etc.
 * exceptions) or a list of `{msg, loc}` objects (FastAPI's own request-body
 * validation, e.g. a field of the wrong type). Every existing catch block
 * picks this up for free — no call-site changes needed. */
apiClient.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (axios.isAxiosError(error)) {
      const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail;
      if (typeof detail === 'string' && detail.trim()) {
        error.message = detail;
      } else if (Array.isArray(detail) && detail.length > 0) {
        error.message = detail
          .map((d) => (d && typeof d === 'object' && 'msg' in d ? String((d as { msg: unknown }).msg) : String(d)))
          .join('; ');
      }
    }
    return Promise.reject(error);
  },
);

export { API_BASE_URL, DEMO_MODE };
