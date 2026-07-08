import { useCallback, useEffect, useState } from 'react';
import { deleteGroupMapping, listGroupMappings, upsertGroupMapping } from '@/api/groupMappingsApi';
import { listTenants } from '@/api/tenantsApi';
import type { GroupMapping, Role, Tenant } from '@/types/platform';
import { Button, Field, InlineAlert, Input, Modal, Select } from '@/components/shared/ui';
import { DataTable, type DataTableColumn } from '@/components/shared/DataTable';
import { ConfirmDialog } from '@/components/shared/ConfirmDialog';

const roles: Role[] = ['PlatformAdmin', 'LeadDataScientist', 'DataScientist'];

const emptyForm = {
  mappingId: undefined as string | undefined,
  entraGroupId: '',
  entraGroupName: '',
  role: 'DataScientist' as Role,
  tenantId: '' as string,
};

export function GroupMappingsPage() {
  const [mappings, setMappings] = useState<GroupMapping[]>([]);
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<GroupMapping | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [mappingsRes, tenantsRes] = await Promise.all([
        listGroupMappings(),
        listTenants({ pageSize: 100 }),
      ]);
      setMappings(mappingsRes.items);
      setTenants(tenantsRes.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load group mappings.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const openCreate = () => {
    setForm(emptyForm);
    setFormOpen(true);
  };

  const openEdit = (m: GroupMapping) => {
    setForm({
      mappingId: m.mappingId,
      entraGroupId: m.entraGroupId,
      entraGroupName: m.entraGroupName,
      role: m.role,
      tenantId: m.tenantId ?? '',
    });
    setFormOpen(true);
  };

  const handleSave = async () => {
    setSaving(true);
    setActionError(null);
    try {
      await upsertGroupMapping({
        mappingId: form.mappingId,
        entraGroupId: form.entraGroupId.trim(),
        entraGroupName: form.entraGroupName.trim(),
        role: form.role,
        tenantId: form.role === 'PlatformAdmin' ? null : form.tenantId || null,
      });
      setFormOpen(false);
      await load();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to save group mapping.');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setActionError(null);
    try {
      await deleteGroupMapping(deleteTarget.mappingId);
      setDeleteTarget(null);
      await load();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to delete group mapping.');
    }
  };

  const columns: DataTableColumn<GroupMapping>[] = [
    { key: 'entraGroupName', header: 'Entra Group', render: (m) => m.entraGroupName },
    { key: 'entraGroupId', header: 'Group ID', render: (m) => <code className="text-xs">{m.entraGroupId}</code> },
    { key: 'role', header: 'Role', render: (m) => m.role },
    { key: 'tenantId', header: 'Tenant', render: (m) => m.tenantId ?? '— (all tenants)' },
    {
      key: 'actions',
      header: 'Actions',
      render: (m) => (
        <div className="flex gap-2">
          <Button variant="secondary" size="sm" onClick={() => openEdit(m)}>
            Edit
          </Button>
          <Button variant="danger" size="sm" onClick={() => setDeleteTarget(m)}>
            Delete
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold text-truist-purple">Group Mappings</h1>
        <Button onClick={openCreate}>Add Mapping</Button>
      </div>
      <p className="mb-4 text-sm text-truist-darkGray">
        Maps an Entra ID group to a role and tenant. When a user signs in through MSAL, their group
        memberships resolve to a role/tenant through these mappings.
      </p>

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
        rows={mappings}
        rowKey={(m) => m.mappingId}
        loading={loading}
        emptyTitle="No group mappings yet"
        emptyDescription="Add a mapping to grant an Entra group a role within a tenant."
      />

      <Modal open={formOpen} onClose={() => setFormOpen(false)} title={form.mappingId ? 'Edit Mapping' : 'Add Mapping'}>
        <Field label="Entra group name" required>
          <Input
            value={form.entraGroupName}
            onChange={(e) => setForm((f) => ({ ...f, entraGroupName: e.target.value }))}
          />
        </Field>
        <Field label="Entra group ID" required>
          <Input
            value={form.entraGroupId}
            onChange={(e) => setForm((f) => ({ ...f, entraGroupId: e.target.value }))}
            placeholder="00000000-0000-0000-0000-000000000000"
          />
        </Field>
        <Field label="Role" required>
          <Select
            value={form.role}
            onChange={(e) => setForm((f) => ({ ...f, role: e.target.value as Role }))}
          >
            {roles.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </Select>
        </Field>
        {form.role !== 'PlatformAdmin' && (
          <Field label="Tenant" required hint="Platform Admin mappings are not scoped to a tenant.">
            <Select
              value={form.tenantId}
              onChange={(e) => setForm((f) => ({ ...f, tenantId: e.target.value }))}
            >
              <option value="">Select a tenant…</option>
              {tenants.map((t) => (
                <option key={t.tenantId} value={t.tenantId}>
                  {t.name}
                </option>
              ))}
            </Select>
          </Field>
        )}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setFormOpen(false)} disabled={saving}>
            Cancel
          </Button>
          <Button
            onClick={() => void handleSave()}
            disabled={
              saving ||
              !form.entraGroupId.trim() ||
              !form.entraGroupName.trim() ||
              (form.role !== 'PlatformAdmin' && !form.tenantId)
            }
          >
            {saving ? 'Saving…' : 'Save'}
          </Button>
        </div>
      </Modal>

      <ConfirmDialog
        open={!!deleteTarget}
        title="Delete group mapping"
        description={`Remove the mapping for "${deleteTarget?.entraGroupName}"? Users in this Entra group will lose access mapped through this rule.`}
        confirmLabel="Delete"
        danger
        onConfirm={() => handleDelete()}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
