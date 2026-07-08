import { useAuth } from '@/auth/AuthContext';
import { useTenantContext } from '@/auth/useTenantContext';
import { Button } from '@/components/shared/ui';

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
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-truist-gray06 bg-white px-6">
      <div className="text-sm text-truist-darkGray">
        {tenantId ? (
          <span>
            Tenant: <span className="font-medium text-truist-charcoal">{tenantId}</span>
          </span>
        ) : (
          <span className="font-medium text-truist-charcoal">All tenants (Platform Admin view)</span>
        )}
      </div>
      <div className="flex items-center gap-4">
        {user && (
          <div className="text-right text-sm">
            <div className="font-medium text-truist-charcoal">{user.name}</div>
            <div className="text-xs text-truist-darkGray">
              {roleLabels[user.role] ?? user.role}
            </div>
          </div>
        )}
        <Button variant="secondary" size="sm" onClick={logout}>
          Sign out
        </Button>
      </div>
    </header>
  );
}
