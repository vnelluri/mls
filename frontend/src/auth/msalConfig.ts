import type { Configuration } from '@azure/msal-browser';

const tenantId = import.meta.env.VITE_ENTRA_TENANT_ID || 'common';
const clientId = import.meta.env.VITE_ENTRA_CLIENT_ID || '';

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

export const loginRequest = {
  scopes: ['User.Read'],
};
