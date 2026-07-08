import { useCallback, useEffect, useState } from 'react';
import { listAuditEvents } from '@/api/auditApi';
import type { AuditEvent } from '@/types/platform';
import { useTenantContext } from '@/auth/useTenantContext';
import { Field, InlineAlert, Input } from '@/components/shared/ui';
import { DataTable, type DataTableColumn } from '@/components/shared/DataTable';
import { Pagination } from '@/components/shared/Pagination';

export function AuditLogPage() {
  const { isPlatformAdmin } = useTenantContext();
  const [page, setPage] = useState(1);
  const [pageSize] = useState(25);
  const [actionFilter, setActionFilter] = useState('');
  const [entityTypeFilter, setEntityTypeFilter] = useState('');
  const [data, setData] = useState<{ items: AuditEvent[]; total: number }>({ items: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listAuditEvents({
        page,
        pageSize,
        action: actionFilter.trim() || undefined,
        entityType: entityTypeFilter.trim() || undefined,
      });
      setData({ items: res.items, total: res.total });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load audit log.');
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, actionFilter, entityTypeFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const columns: DataTableColumn<AuditEvent>[] = [
    { key: 'timestamp', header: 'Timestamp', render: (e) => new Date(e.timestamp).toLocaleString() },
    ...(isPlatformAdmin
      ? [{ key: 'tenantId', header: 'Tenant', render: (e: AuditEvent) => e.tenantId } as DataTableColumn<AuditEvent>]
      : []),
    { key: 'actor', header: 'Actor', render: (e) => e.actor },
    { key: 'actorRole', header: 'Role', render: (e) => e.actorRole },
    { key: 'action', header: 'Action', render: (e) => e.action },
    { key: 'entityType', header: 'Entity type', render: (e) => e.entityType },
    { key: 'entityId', header: 'Entity ID', render: (e) => <code className="text-xs">{e.entityId}</code> },
    { key: 'summary', header: 'Summary', render: (e) => e.summary },
  ];

  return (
    <div>
      <h1 className="mb-1 text-xl font-semibold text-truist-purple">Audit Log</h1>
      <p className="mb-4 text-sm text-truist-darkGray">
        {isPlatformAdmin ? 'All tenants.' : 'Scoped to your tenant.'}
      </p>

      <div className="mb-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:max-w-lg">
        <Field label="Filter by action">
          <Input
            value={actionFilter}
            onChange={(e) => {
              setPage(1);
              setActionFilter(e.target.value);
            }}
            placeholder="e.g. pipeline.create"
          />
        </Field>
        <Field label="Filter by entity type">
          <Input
            value={entityTypeFilter}
            onChange={(e) => {
              setPage(1);
              setEntityTypeFilter(e.target.value);
            }}
            placeholder="e.g. Pipeline, Job, Model"
          />
        </Field>
      </div>

      {error && (
        <div className="mb-4">
          <InlineAlert kind="error">{error}</InlineAlert>
        </div>
      )}

      <DataTable
        columns={columns}
        rows={data.items}
        rowKey={(e) => e.eventId}
        loading={loading}
        emptyTitle="No audit events found"
        emptyDescription="Try adjusting the filters above."
      />
      <Pagination data={{ total: data.total, page, pageSize }} onPageChange={setPage} />
    </div>
  );
}
