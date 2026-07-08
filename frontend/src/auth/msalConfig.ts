import type { Configuration } from '@azure/msal-browser';

const tenantId = import.meta.env.VITE_ENTRA_TENANT_ID || 'common';
const clientId = import.meta.env.VITE_ENTRA_CLIENT_ID || '';

/**
 * The scope that mints an access token FOR OUR API — its `aud` must be the
 * backend's app registration (what the backend checks as ENTRA_AUDIENCE /
 * ENTRA_CLIENT_ID). A Graph scope like 'User.Read' would mint a token the
 * backend must reject. Defaults to the SPA's own app-ID URI for
 * single-app-registration setups; set VITE_ENTRA_API_SCOPE explicitly when
 * the API is a separate registration (e.g. api://<api-client-id>/.default).
 */
export const apiScope: string =
  import.meta.env.VITE_ENTRA_API_SCOPE || (clientId ? `api://${clientId}/.default` : '');

export const msalConfig: Configuration = {
  auth: {
    clientId,
    authority: `https://login.microsoftonline.com/${tenantId}`,
    redirectUri: window.location.origin,
  },
  cache: {
    cacheLocation: 'sessionStorage',
    storeAuthStateInCookie: false,
  },
};

/** Login asks for the API scope up front so consent is granted once, at
 * sign-in, and every later acquireTokenSilent for the same scope is a cache
 * hit or silent refresh. */
export const loginRequest = {
  scopes: apiScope ? [apiScope] : [],
};

export const tokenRequest = {
  scopes: apiScope ? [apiScope] : [],
};
