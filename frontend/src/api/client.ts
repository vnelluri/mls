import axios, { type AxiosInstance } from 'axios';

const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://localhost:8000';

const DEMO_MODE: boolean = (import.meta.env.VITE_DEMO_MODE as string | undefined) === 'true';

/** Populated by AuthContext once MSAL acquires a token (production mode only). */
let bearerTokenGetter: (() => string | null) | null = null;

export function setBearerTokenGetter(getter: () => string | null): void {
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

apiClient.interceptors.request.use((config) => {
  if (DEMO_MODE) {
    const role = getDemoSelectedRole();
    if (role) {
      config.headers.set('X-Demo-Role', role);
    }
  } else if (bearerTokenGetter) {
    const token = bearerTokenGetter();
    if (token) {
      config.headers.set('Authorization', `Bearer ${token}`);
    }
  }
  return config;
});

export { API_BASE_URL, DEMO_MODE };
