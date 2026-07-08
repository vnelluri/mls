import {
  InteractionRequiredAuthError,
  type IPublicClientApplication,
} from '@azure/msal-browser';
import { tokenRequest } from './msalConfig';

/**
 * Acquire an access token for the backend API, silently when possible.
 *
 * MSAL serves from its cache until the token nears expiry, then refreshes it
 * without user interaction. When silent acquisition fails because the user
 * must interact (expired session, revoked consent, Conditional Access), fall
 * through to a full-page redirect: the request that triggered this is lost,
 * but the user lands back with a fresh session. Any other failure is
 * re-thrown so the API call fails with the real MSAL error instead of a
 * misleading unauthenticated 401.
 */
export async function acquireApiToken(instance: IPublicClientApplication): Promise<string | null> {
  const account = instance.getActiveAccount() ?? instance.getAllAccounts()[0];
  if (!account) return null;
  try {
    const result = await instance.acquireTokenSilent({ ...tokenRequest, account });
    return result.accessToken;
  } catch (err) {
    if (err instanceof InteractionRequiredAuthError) {
      await instance.acquireTokenRedirect({ ...tokenRequest, account });
      return null; // not reached in practice — the redirect navigates away
    }
    throw err;
  }
}
