import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { getMonitoringDashboard, listMonitoringSnapshots } from '@/api/monitoringApi';
import type { MonitoringSnapshot, MonitoringStatus } from '@/types/platform';
import { useTenantContext } from '@/auth/useTenantContext';
import { Card, Field, InlineAlert, Select } from '@/components/shared/ui';
import { LoadingSpinner } from '@/components/shared/LoadingSpinner';
import { DataTable, type DataTableColumn } from '@/components/shared/DataTable';
import { MonitoringStatusBadge } from '@/components/StatusBadge';

const statusMeta: { status: MonitoringStatus; label: string; cssVar: string; description: string }[] = [
  {
    status: 'Passed',
    label: 'Passed',
    cssVar: '--status-passed',
    description: 'Latest data quality check passed within thresholds.',
  },
  {
    status: 'Failed',
    label: 'Failed',
    cssVar: '--status-failed',
    description: 'Latest data quality check failed thresholds.',
  },
  {
    status: 'Rework',
    label: 'Rework',
    cssVar: '--status-rework',
    description: 'Flagged for rework after an approval rejection or repeated failures.',
  },
  {
    status: 'InReview',
    label: 'In review',
    cssVar: '--status-in-review',
    description: 'Awaiting approval or manual review before completion.',
  },
  {
    status: 'NotStarted',
    label: 'Not started',
    cssVar: '--status-not-started',
    description: 'No monitoring snapshot has been recorded yet for this model version.',
  },
];

const snapshotColumns: DataTableColumn<MonitoringSnapshot>[] = [
  { key: 'recordedAt', header: 'Recorded', render: (s) => new Date(s.recordedAt).toLocaleString() },
  { key: 'derivedStatus', header: 'Status', render: (s) => <MonitoringStatusBadge status={s.derivedStatus} /> },
  { key: 'requestCount', header: 'Requests', render: (s) => s.requestCount.toLocaleString() },
  { key: 'avgLatencyMs', header: 'Avg latency (ms)', render: (s) => s.avgLatencyMs.toFixed(1) },
  { key: 'errorRate', header: 'Error rate', render: (s) => `${(s.errorRate * 100).toFixed(2)}%` },
  { key: 'maxPsi', header: 'Max PSI', render: (s) => s.maxPsi.toFixed(3) },
  { key: 'dataQualityPassed', header: 'DQ passed', render: (s) => (s.dataQualityPassed ? 'Yes' : 'No') },
  {
    key: 'driftMetrics',
    header: 'Drift metrics (PSI per feature)',
    render: (s) => {
      const entries = Object.entries(s.driftMetrics);
      if (entries.length === 0) return '—';
      return (
        <span className="text-xs text-truist-darkGray">
          {entries.map(([k, v]) => `${k}: ${v.toFixed(3)}`).join(', ')}
        </span>
      );
    },
  },
  { key: 'jobId', header: 'Job', render: (s) => <code className="text-xs">{s.jobId}</code> },
];

export function MonitoringDashboardPage() {
  const { seesAllTenants } = useTenantContext();
  const [searchParams, setSearchParams] = useSearchParams();
  const [counts, setCounts] = useState<Record<MonitoringStatus, number> | null>(null);
  const [snapshots, setSnapshots] = useState<MonitoringSnapshot[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [dash, snaps] = await Promise.all([
        getMonitoringDashboard(),
        listMonitoringSnapshots({ pageSize: 200 }),
      ]);
      setCounts(dash.counts);
      setSnapshots(snaps.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load monitoring dashboard.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Model selector options come from the snapshots themselves — every model
  // version that has ever been monitored.
  const modelOptions = useMemo(() => {
    const seen = new Map<string, { modelName: string; version: string }>();
    for (const s of snapshots) {
      seen.set(`${s.modelName}#${s.version}`, { modelName: s.modelName, version: s.version });
    }
    return [...seen.values()].sort(
      (a, b) =>
        a.modelName.localeCompare(b.modelName) ||
        a.version.localeCompare(b.version, undefined, { numeric: true }),
    );
  }, [snapshots]);

  const selectedKey = (() => {
    const model = searchParams.get('model');
    const version = searchParams.get('version');
    if (model && version) return `${model}#${version}`;
    return modelOptions.length > 0 ? `${modelOptions[0].modelName}#${modelOptions[0].version}` : '';
  })();

  const selectModel = (key: string) => {
    const [modelName, version] = key.split('#');
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set('model', modelName);
      next.set('version', version);
      return next;
    });
  };

  const trend = useMemo(() => {
    if (!selectedKey) return [];
    const [modelName, version] = selectedKey.split('#');
    return snapshots
      .filter((s) => s.modelName === modelName && s.version === version)
      .sort((a, b) => new Date(b.recordedAt).getTime() - new Date(a.recordedAt).getTime());
  }, [snapshots, selectedKey]);

  return (
    <div>
      <h1 className="mb-1 text-xl font-semibold text-truist-purple">Monitoring Dashboard</h1>
      <p className="mb-6 text-sm text-truist-darkGray">
        {seesAllTenants
          ? 'Aggregate model monitoring status across all tenants.'
          : 'Model monitoring status for your tenant.'}{' '}
        Select a model below to see its drift metrics run by run.
      </p>

      {error && (
        <div className="mb-4">
          <InlineAlert kind="error">{error}</InlineAlert>
        </div>
      )}

      {loading ? (
        <LoadingSpinner />
      ) : (
        <>
          {counts && (
            <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
              {statusMeta.map((s) => (
                <div
                  key={s.status}
                  className="flex flex-col items-start gap-2 rounded-lg p-5 text-left text-white shadow-sm"
                  style={{ backgroundColor: `var(${s.cssVar})` }}
                >
                  <span className="text-xs font-semibold uppercase tracking-wide opacity-90">{s.label}</span>
                  <span className="text-3xl font-bold">{counts[s.status] ?? 0}</span>
                  <span className="text-xs opacity-90">{s.description}</span>
                </div>
              ))}
            </div>
          )}

          <Card>
            <h2 className="mb-3 text-sm font-semibold text-truist-charcoal">Drift metrics by model</h2>
            {modelOptions.length === 0 ? (
              <p className="text-sm text-truist-darkGray">
                No monitoring snapshots yet — snapshots are recorded when a job's data quality check
                step completes.
              </p>
            ) : (
              <>
                <div className="mb-4 max-w-sm">
                  <Field label="Model version">
                    <Select value={selectedKey} onChange={(e) => selectModel(e.target.value)}>
                      {modelOptions.map((o) => (
                        <option key={`${o.modelName}#${o.version}`} value={`${o.modelName}#${o.version}`}>
                          {o.modelName} v{o.version}
                        </option>
                      ))}
                    </Select>
                  </Field>
                </div>
                <DataTable
                  columns={snapshotColumns}
                  rows={trend}
                  rowKey={(s) => `${s.jobId}-${s.recordedAt}`}
                  emptyTitle="No snapshots for this model version"
                />
              </>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
