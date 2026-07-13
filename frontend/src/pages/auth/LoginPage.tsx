import { useState } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '@/auth/AuthContext';
import { Button, Copyright, InlineAlert } from '@/components/shared/ui';
import type { Role } from '@/types/platform';

const roleOptions: { role: Role; label: string; description: string }[] = [
  {
    role: 'PlatformAdmin',
    label: 'Platform Admin',
    description: 'View-only across every tenant. Manages tenants and group mappings.',
  },
  {
    role: 'Operator',
    label: 'Operator',
    description: 'Operates jobs across every tenant — stop, restart, resume — including production runs. No other writes.',
  },
  {
    role: 'LeadDataScientist',
    label: 'Lead Data Scientist',
    description: 'Creates and submits jobs, approves steps, and manages models for their tenant.',
  },
  {
    role: 'DataScientist',
    label: 'Data Scientist',
    description: 'Views their own tenant and can stop, restart or resume its staging job runs.',
  },
];

export function LoginPage() {
  const { user, loading, error, demoMode, loginDemo, loginWithMsal } = useAuth();
  const [selected, setSelected] = useState<Role>('LeadDataScientist');
  const [signingIn, setSigningIn] = useState(false);

  if (user) return <Navigate to="/" replace />;

  const handleDemoLogin = async () => {
    setSigningIn(true);
    try {
      await loginDemo(selected);
    } finally {
      setSigningIn(false);
    }
  };

  return (
    <div className="flex min-h-screen bg-truist-tint08">
      {/* Left panel — branded hero, stays valhalla-dark (same as TMT) */}
      <div className="login-grid-pattern relative hidden w-1/2 flex-col justify-between overflow-hidden bg-truist-valhalla bg-gradient-to-br from-truist-valhalla via-truist-valhalla to-truist-valhallaDeep p-12 lg:flex">
        <div className="absolute inset-0 bg-gradient-to-t from-black/40 via-transparent to-transparent" />
        <div className="relative z-10 flex items-center gap-3">
          <img src="/truist-logo1.svg" alt="Truist" className="logo-invert h-10 w-10" />
          <span className="text-lg font-semibold text-white">Truist</span>
        </div>
        <div className="relative z-10 max-w-md">
          <h1 className="text-4xl font-semibold leading-tight text-white">
            Truist Model Serving (TMS)
          </h1>
          <p className="mt-4 text-truist-dawn/90">
            Submit batch scoring jobs, monitor pipelines, and govern model runs across every
            business unit — with tenancy and access derived directly from Entra ID.
          </p>
        </div>
        <Copyright suffix="Internal use only." className="relative z-10 text-xs text-white/40" />
      </div>

      {/* Right panel — sign-in form */}
      <div className="flex w-full flex-col items-center justify-center px-6 lg:w-1/2">
        <div className="w-full max-w-sm">
          <div className="mb-8 text-center lg:hidden">
            <img src="/truist-logo1.svg" alt="Truist" className="mx-auto mb-3 h-10 w-10" />
            <h1 className="text-xl font-semibold text-truist-charcoal">Truist Model Serving (TMS)</h1>
          </div>

          <h2 className="text-2xl font-semibold text-truist-charcoal">Sign in</h2>
          <p className="mt-1 text-sm text-truist-darkGray">
            {demoMode
              ? 'Local demo mode — pick a role to explore the platform.'
              : 'Sign in with your Truist Microsoft account.'}
          </p>

          {error && (
            <div className="mt-4">
              <InlineAlert kind="error">{error}</InlineAlert>
            </div>
          )}

          {demoMode ? (
            <div className="mt-6 space-y-2">
              {roleOptions.map((opt) => (
                <button
                  key={opt.role}
                  aria-pressed={selected === opt.role}
                  onClick={() => setSelected(opt.role)}
                  className={`w-full rounded-xl border px-4 py-3 text-left transition ${
                    selected === opt.role
                      ? 'border-truist-purple bg-truist-purple/10'
                      : 'border-truist-gray06 bg-white hover:border-truist-purple/40'
                  }`}
                >
                  <p className="text-sm font-semibold text-truist-charcoal">{opt.label}</p>
                  <p className="mt-0.5 text-xs text-truist-darkGray">{opt.description}</p>
                </button>
              ))}
              <Button
                className="mt-4 w-full"
                onClick={handleDemoLogin}
                disabled={signingIn || loading}
              >
                {signingIn || loading ? 'Signing in…' : `Continue as ${roleOptions.find((o) => o.role === selected)?.label}`}
              </Button>
              <p className="mt-3 text-center text-[11px] text-truist-midGray">
                The demo role selector is cosmetic only — the actual role always comes from the
                backend's <code>/auth/me</code> response, controlled by the backend's own dev
                auth configuration.
              </p>
            </div>
          ) : (
            <Button
              className="mt-6 w-full gap-3"
              onClick={() => void loginWithMsal()}
              disabled={loading}
            >
              <svg width="18" height="18" viewBox="0 0 21 21" fill="none" aria-hidden="true">
                <rect x="1" y="1" width="9" height="9" fill="#f25022" />
                <rect x="11" y="1" width="9" height="9" fill="#7fba00" />
                <rect x="1" y="11" width="9" height="9" fill="#00a4ef" />
                <rect x="11" y="11" width="9" height="9" fill="#ffb900" />
              </svg>
              Sign in with Microsoft
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
