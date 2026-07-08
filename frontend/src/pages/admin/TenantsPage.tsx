import { useCallback, useEffect, useState } from 'react';
import { createTenant, listTenants, reactivateTenant, suspendTenant } from '@/api/tenantsApi';
import type { Tenant } from '@/types/platform';
import { Button, Field, InlineAlert, Input, Modal } from '@/components/shared/ui';
import { DataTable, type DataTableColumn } from '@/components/shared/DataTable';
import { Pagination } from '@/components/shared/Pagination';
import { ConfirmDialog } from '@/components/shared/ConfirmDialog';
import { useTenantContext } from '@/auth/useTenantContext';

export function TenantsPage() {
  const { canManageTenants } = useTenantContext();
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [tenants, setTenants] = useState<{ items: Tenant[]; total: number }>({ items: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [newTenantName, setNewTenantName] = useState('');
  const [creating, setCreating] = useState(false);
  const [suspendTarget, setSuspendTarget] = useState<Tenant | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listTenants({ page, pageSize });
      setTenants({ items: res.items, total: res.total });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load tenants.');
    } finally {
      setLoading(false);
    }
  }, [page, pageSize]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleCreate = async () => {
    if (!canManageTenants) {
      setActionError('Only Platform Admins can create tenants.');
      return;
    }
    setCreating(true);
    setActionError(null);
    try {
      await createTenant({ name: newTenantName.trim() });
      setCreateOpen(false);
      setNewTenantName('');
      await load();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to create tenant.');
    } finally {
      setCreating(false);
    }
  };

  const handleSuspendConfirm = async () => {
    if (!suspendTarget) return;
    setActionError(null);
    try {
      await suspendTenant(suspendTarget.tenantId);
      setSuspendTarget(null);
      await load();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to suspend tenant.');
    }
  };

  const handleReactivate = async (tenant: Tenant) => {
    setActionError(null);
    try {
      await reactivateTenant(tenant.tenantId);
      await load();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to reactivate tenant.');
    }
  };

  const columns: DataTableColumn<Tenant>[] = [
    { key: 'name', header: 'Name', render: (t) => <span className="font-medium">{t.name}</span> },
    { key: 'tenantId', header: 'Tenant ID', render: (t) => t.tenantId },
    {
      key: 'status',
      header: 'Status',
      render: (t) => (
        <span
          className={
            t.status === 'active'
              ? 'text-[color:var(--status-passed)] font-medium'
              : 'text-[color:var(--status-failed)] font-medium'
          }
        >
          {t.status}
        </span>
      ),
    },
    { key: 'createdAt', header: 'Created', render: (t) => new Date(t.createdAt).toLocaleString() },
    { key: 'createdBy', header: 'Created by', render: (t) => t.createdBy },
    {
      key: 'actions',
      header: 'Actions',
      render: (t) =>
        t.status === 'active' ? (
          <Button variant="danger" size="sm" onClick={() => setSuspendTarget(t)}>
            Suspend
          </Button>
        ) : (
          <Button variant="secondary" size="sm" onClick={() => void handleReactivate(t)}>
            Reactivate
          </Button>
        ),
    },
  ];

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold text-truist-purple">Tenants</h1>
        <Button onClick={() => setCreateOpen(true)}>Create Tenant</Button>
      </div>

      {error && (
        <div className="mb-4">
          <InlineAlert kind="error">{error}</InlineAlert>
        </div>
      )}
      {actionError && (
        <div className="mb-4">
          <InlineAlert kind="error">{actionError}</InlineAlert>
        </div>
      )}

      <DataTable
        columns={columns}
        rows={tenants.items}
        rowKey={(t) => t.tenantId}
        loading={loading}
        emptyTitle="No tenants yet"
        emptyDescription="Create the first tenant to onboard a business unit."
      />
      <Pagination data={{ total: tenants.total, page, pageSize }} onPageChange={setPage} />

      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title="Create Tenant">
        <Field label="Tenant name" required>
          <Input value={newTenantName} onChange={(e) => setNewTenantName(e.target.value)} />
        </Field>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setCreateOpen(false)} disabled={creating}>
            Cancel
          </Button>
          <Button onClick={() => void handleCreate()} disabled={creating || !newTenantName.trim()}>
            {creating ? 'Creating…' : 'Create'}
          </Button>
        </div>
      </Modal>

      <ConfirmDialog
        open={!!suspendTarget}
        title="Suspend tenant"
        description={`Suspending "${suspendTarget?.name}" blocks every user in this tenant from accessing the platform until it is reactivated. Are you sure?`}
        confirmLabel="Suspend"
        danger
        onConfirm={() => handleSuspendConfirm()}
        onCancel={() => setSuspendTarget(null)}
      />
    </div>
  );
}
