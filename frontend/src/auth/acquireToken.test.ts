import { describe, expect, it, vi } from 'vitest';
import {
  InteractionRequiredAuthError,
  type AccountInfo,
  type AuthenticationResult,
  type IPublicClientApplication,
} from '@azure/msal-browser';

import { acquireApiToken } from './acquireToken';
import { tokenRequest } from './msalConfig';

const account = { homeAccountId: 'home-1', username: 'user@bank.com' } as AccountInfo;

/** Minimal fake of the MSAL surface acquireApiToken touches. */
function fakeMsal(overrides: Partial<IPublicClientApplication>): IPublicClientApplication {
  return {
    getActiveAccount: () => null,
    getAllAccounts: () => [],
    acquireTokenSilent: vi.fn(),
    acquireTokenRedirect: vi.fn(),
    ...overrides,
  } as unknown as IPublicClientApplication;
}

describe('acquireApiToken', () => {
  it('returns null when no account is signed in', async () => {
    const silent = vi.fn();
    const instance = fakeMsal({ acquireTokenSilent: silent });
    expect(await acquireApiToken(instance)).toBeNull();
    expect(silent).not.toHaveBeenCalled();
  });

  it('returns the access token from acquireTokenSilent for the active account', async () => {
    const silent = vi
      .fn()
      .mockResolvedValue({ accessToken: 'api-token-789' } as AuthenticationResult);
    const instance = fakeMsal({
      getActiveAccount: () => account,
      acquireTokenSilent: silent,
    });

    expect(await acquireApiToken(instance)).toBe('api-token-789');
    expect(silent).toHaveBeenCalledWith({ ...tokenRequest, account });
  });

  it('falls back to the first cached account when none is active', async () => {
    const silent = vi
      .fn()
      .mockResolvedValue({ accessToken: 'api-token-789' } as AuthenticationResult);
    const instance = fakeMsal({
      getAllAccounts: () => [account],
      acquireTokenSilent: silent,
    });

    expect(await acquireApiToken(instance)).toBe('api-token-789');
    expect(silent).toHaveBeenCalledWith({ ...tokenRequest, account });
  });

  it('redirects to re-authenticate when interaction is required', async () => {
    const redirect = vi.fn().mockResolvedValue(undefined);
    const instance = fakeMsal({
      getActiveAccount: () => account,
      acquireTokenSilent: vi
        .fn()
        .mockRejectedValue(new InteractionRequiredAuthError('interaction_required')),
      acquireTokenRedirect: redirect,
    });

    expect(await acquireApiToken(instance)).toBeNull();
    expect(redirect).toHaveBeenCalledWith({ ...tokenRequest, account });
  });

  it('re-throws unexpected MSAL failures instead of swallowing them into a 401', async () => {
    const instance = fakeMsal({
      getActiveAccount: () => account,
      acquireTokenSilent: vi.fn().mockRejectedValue(new Error('network down')),
    });

    await expect(acquireApiToken(instance)).rejects.toThrow('network down');
  });
});
