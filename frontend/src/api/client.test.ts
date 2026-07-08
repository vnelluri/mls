import { afterEach, describe, expect, it, vi } from 'vitest';
import { AxiosHeaders } from 'axios';
import type { AxiosRequestConfig, AxiosResponse } from 'axios';

import {
  apiClient,
  getDemoSelectedRole,
  setBearerTokenGetter,
  setDemoSelectedRole,
} from './client';

/** Adapter that short-circuits the request and echoes its config back, so
 * interceptor effects can be asserted without any network. */
function echoAdapter(config: AxiosRequestConfig): Promise<AxiosResponse> {
  return Promise.resolve({
    data: {},
    status: 200,
    statusText: 'OK',
    headers: {},
    config,
  } as AxiosResponse);
}

afterEach(() => {
  setBearerTokenGetter(() => null);
  setDemoSelectedRole(null);
});

describe('apiClient auth interceptor (production mode)', () => {
  it('attaches the MSAL bearer token to every request', async () => {
    setBearerTokenGetter(() => 'token-123');
    const resp = await apiClient.get('/auth/me', { adapter: echoAdapter });
    const headers = AxiosHeaders.from(resp.config.headers);
    expect(headers.get('Authorization')).toBe('Bearer token-123');
  });

  it('sends no Authorization header when no token is available', async () => {
    setBearerTokenGetter(() => null);
    const resp = await apiClient.get('/auth/me', { adapter: echoAdapter });
    const headers = AxiosHeaders.from(resp.config.headers);
    expect(headers.get('Authorization')).toBeFalsy();
  });
});

describe('apiClient in demo mode', () => {
  it('sends the cosmetic X-Demo-Role header instead of a bearer token', async () => {
    // DEMO_MODE is a module constant, so stub the env and load a fresh copy.
    vi.stubEnv('VITE_DEMO_MODE', 'true');
    vi.resetModules();
    const demo = await import('./client');
    demo.setDemoSelectedRole('Operator');
    demo.setBearerTokenGetter(() => 'token-must-not-be-used');

    const resp = await demo.apiClient.get('/auth/me', { adapter: echoAdapter });
    const headers = AxiosHeaders.from(resp.config.headers);
    expect(headers.get('X-Demo-Role')).toBe('Operator');
    expect(headers.get('Authorization')).toBeFalsy();

    demo.setDemoSelectedRole(null);
    vi.unstubAllEnvs();
    vi.resetModules();
  });
});

describe('demo role selection persistence', () => {
  it('persists the cosmetic role to localStorage and clears it', () => {
    setDemoSelectedRole('Operator');
    expect(getDemoSelectedRole()).toBe('Operator');
    expect(window.localStorage.getItem('demoSelectedRole')).toBe('Operator');

    setDemoSelectedRole(null);
    expect(window.localStorage.getItem('demoSelectedRole')).toBeNull();
  });

  it('falls back to localStorage after a reload (fresh module state)', () => {
    window.localStorage.setItem('demoSelectedRole', 'DataScientist');
    // In-memory value was reset to null by afterEach; the getter must
    // recover the persisted choice.
    expect(getDemoSelectedRole()).toBe('DataScientist');
  });
});
