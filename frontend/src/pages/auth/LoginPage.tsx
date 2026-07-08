import { useState } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '@/auth/AuthContext';
import { Button, Card, InlineAlert } from '@/components/shared/ui';
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
    <div className="flex min-h-screen items-center justify-center bg-truist-tint08 px-4">
      <Card className="w-full max-w-md">
        <div className="mb-6 text-center">
          <div className="mb-2 text-2xl font-bold text-truist-purple">ML Serving &amp; Monitoring</div>
          <p className="text-sm text-truist-darkGray">Sign in to continue</p>
        </div>

        {error && (
          <div className="mb-4">
            <InlineAlert kind="error">{error}</InlineAlert>
          </div>
        )}

        {demoMode ? (
          <>
            <div className="mb-4">
              <InlineAlert kind="info">
                Local dev demo mode. This role selector is cosmetic only — the actual role always
                comes from the backend's <code>/auth/me</code> response, controlled by the backend's
                own dev auth configuration.
              </InlineAlert>
            </div>
            <div className="mb-5 space-y-2">
              {roleOptions.map((opt) => (
                <label
                  key={opt.role}
                  className={`flex cursor-pointer items-start gap-3 rounded-md border p-3 transition-colors ${
                    selected === opt.role
                      ? 'border-truist-purple bg-truist-tint07'
                      : 'border-truist-lightGray hover:bg-truist-gray07'
                  }`}
                >
                  <input
                    type="radio"
                    name="role"
                    className="mt-1"
                    checked={selected === opt.role}
                    onChange={() => setSelected(opt.role)}
                  />
                  <span>
                    <span className="block text-sm font-medium text-truist-charcoal">{opt.label}</span>
                    <span className="block text-xs text-truist-darkGray">{opt.description}</span>
                  </span>
                </label>
              ))}
            </div>
            <Button className="w-full" onClick={handleDemoLogin} disabled={signingIn || loading}>
              {signingIn || loading ? 'Signing in…' : 'Continue'}
            </Button>
          </>
        ) : (
          <Button className="w-full" onClick={() => void loginWithMsal()} disabled={loading}>
            Sign in with Microsoft
          </Button>
        )}
      </Card>
    </div>
  );
}
