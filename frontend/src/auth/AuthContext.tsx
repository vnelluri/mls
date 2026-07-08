import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { PublicClientApplication } from '@azure/msal-browser';
import { getCurrentUser } from '@/api/authApi';
import { DEMO_MODE, getDemoSelectedRole, setBearerTokenGetter, setDemoSelectedRole } from '@/api/client';
import { msalConfig, loginRequest } from './msalConfig';
import type { CurrentUser, Role } from '@/types/platform';

interface AuthContextValue {
  user: CurrentUser | null;
  loading: boolean;
  error: string | null;
  demoMode: boolean;
  /** Demo-mode only: the cosmetic role chosen on the login screen. Purely
   * visual — the authoritative role is always whatever GET /auth/me returns,
   * which may legitimately differ (the backend's AUTH_MODE=dev setting is
   * the real source of truth, not this selector). */
  demoSelectedRole: Role | null;
  loginDemo: (role: Role) => Promise<void>;
  loginWithMsal: () => Promise<void>;
  logout: () => void;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

const msalInstance = DEMO_MODE ? null : new PublicClientApplication(msalConfig);
let msalInitialized = false;

async function ensureMsalInitialized() {
  if (!msalInstance) return;
  if (!msalInitialized) {
    await msalInstance.initialize();
    msalInitialized = true;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const me = await getCurrentUser();
      setUser(me);
    } catch (err) {
      setUser(null);
      setError(
        err instanceof Error
          ? `Could not reach the backend to authenticate: ${err.message}`
          : 'Could not reach the backend to authenticate.',
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!DEMO_MODE) {
      setBearerTokenGetter(() => {
        if (!msalInstance) return null;
        const accounts = msalInstance.getAllAccounts();
        if (accounts.length === 0) return null;
        // In production this would use acquireTokenSilent and cache the
        // result; kept synchronous here since this is a thin demo scaffold.
        return null;
      });
    }

    const bootstrap = async () => {
      if (DEMO_MODE) {
        const existingRole = getDemoSelectedRole();
        if (existingRole) {
          await refresh();
        } else {
          setLoading(false);
        }
        return;
      }

      await ensureMsalInitialized();
      const accounts = msalInstance?.getAllAccounts() ?? [];
      if (accounts.length > 0) {
        await refresh();
      } else {
        setLoading(false);
      }
    };

    void bootstrap();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loginDemo = useCallback(
    async (role: Role) => {
      setDemoSelectedRole(role);
      await refresh();
    },
    [refresh],
  );

  const loginWithMsal = useCallback(async () => {
    if (!msalInstance) return;
    await ensureMsalInitialized();
    await msalInstance.loginRedirect(loginRequest);
  }, []);

  const logout = useCallback(() => {
    setUser(null);
    if (DEMO_MODE) {
      setDemoSelectedRole(null);
    } else {
      void msalInstance?.logoutRedirect();
    }
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      loading,
      error,
      demoMode: DEMO_MODE,
      demoSelectedRole: (getDemoSelectedRole() as Role | null) ?? null,
      loginDemo,
      loginWithMsal,
      logout,
      refresh,
    }),
    [user, loading, error, loginDemo, loginWithMsal, logout, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider');
  return ctx;
}
