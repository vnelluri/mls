import { useAuth } from '@/auth/AuthContext';
import { useTenantContext } from '@/auth/useTenantContext';

const roleLabels: Record<string, string> = {
  PlatformAdmin: 'Platform Admin',
  Operator: 'Operator',
  LeadDataScientist: 'Lead Data Scientist',
  DataScientist: 'Data Scientist',
};

export function Topbar() {
  const { user, logout } = useAuth();
  const { tenantId } = useTenantContext();

  return (
    <header className="flex h-16 shrink-0 items-center gap-4 bg-truist-valhalla px-5">
      <div className="flex items-center gap-3">
        <img src="/truist-logo1.svg" alt="Truist" className="logo-invert h-8 w-8" />
        <p className="text-sm font-semibold text-white">Truist Model Serving (TMS)</p>
      </div>

      <div className="ml-auto flex items-center gap-3">
        <div className="flex items-center gap-2 rounded-full border border-white/20 bg-white/10 px-3 py-1.5 text-xs text-white/80">
          <span className="h-1.5 w-1.5 rounded-full bg-truist-dawn" aria-hidden="true" />
          {user
            ? `${roleLabels[user.role] ?? user.role} · ${tenantId ?? 'All tenants'}`
            : 'Not signed in'}
        </div>
        {user && (
          <>
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-truist-dawn/20 text-sm font-semibold text-truist-dawn">
              {(user.name ?? '?').charAt(0).toUpperCase()}
            </div>
            <p className="hidden max-w-[160px] truncate text-sm font-medium text-white md:block">
              {user.name}
            </p>
            <button
              onClick={logout}
              className="rounded-lg border border-white/20 px-3 py-1.5 text-xs font-medium text-white/80 transition hover:bg-white/10 hover:text-white"
            >
              Sign out
            </button>
          </>
        )}
      </div>
    </header>
  );
}
