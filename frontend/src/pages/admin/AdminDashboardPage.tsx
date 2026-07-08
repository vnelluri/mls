import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { listTenants } from '@/api/tenantsApi';
import { listJobs } from '@/api/jobsApi';
import { getMonitoringDashboard } from '@/api/monitoringApi';
import { Card } from '@/components/shared/ui';
import { LoadingSpinner } from '@/components/shared/LoadingSpinner';
import { InlineAlert } from '@/components/shared/ui';
import type { JobStatus, MonitoringStatus } from '@/types/platform';

const jobStatuses: JobStatus[] = [
  'pending',
  'running',
  'awaiting_approval',
  'success',
  'failed',
  'cancelled',
];

const monitoringStatuses: MonitoringStatus[] = [
  'Passed',
  'Failed',
  'Rework',
  'InReview',
  'NotStarted',
];

interface DashboardData {
  tenantCount: number;
  jobsByStatus: Record<JobStatus, number>;
  modelsByStatus: Record<MonitoringStatus, number>;
}

function StatTile({ label, value }: { label: string; value: number | string }) {
  return (
    <Card className="flex flex-col gap-1">
      <span className="text-xs font-medium uppercase tracking-wide text-truist-darkGray">{label}</span>
      <span className="text-2xl font-semibold text-truist-purple">{value}</span>
    </Card>
  );
}

export function AdminDashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [tenants, dashboard, ...jobCounts] = await Promise.all([
          listTenants({ pageSize: 1 }),
          getMonitoringDashboard(),
          ...jobStatuses.map((status) => listJobs({ status, pageSize: 1 })),
        ]);

        if (cancelled) return;

        const jobsByStatus = jobStatuses.reduce((acc, status, i) => {
          acc[status] = jobCounts[i].total;
          return acc;
        }, {} as Record<JobStatus, number>);

        setData({
          tenantCount: tenants.total,
          jobsByStatus,
          modelsByStatus: dashboard.counts,
        });
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load admin dashboard data.');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div>
      <h1 className="mb-1 text-xl font-semibold text-truist-purple">Admin Dashboard</h1>
      <p className="mb-6 text-sm text-truist-darkGray">
        Cross-tenant, view-only summary. Platform Admins never create or mutate tenant-scoped
        resources — use the links below to manage tenants and Entra group mappings.
      </p>

      {error && (
        <div className="mb-4">
          <InlineAlert kind="error">{error}</InlineAlert>
        </div>
      )}

      {loading && !data ? (
        <LoadingSpinner />
      ) : data ? (
        <>
          <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-3">
            <StatTile label="Tenants" value={data.tenantCount} />
            <StatTile label="Jobs running" value={data.jobsByStatus.running} />
            <StatTile label="Jobs awaiting approval" value={data.jobsByStatus.awaiting_approval} />
          </div>

          <div className="mb-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
            <Card>
              <h2 className="mb-3 text-sm font-semibold text-truist-charcoal">Jobs by status</h2>
              <ul className="space-y-1.5 text-sm">
                {jobStatuses.map((status) => (
                  <li key={status} className="flex justify-between">
                    <span className="text-truist-darkGray">{status.replace('_', ' ')}</span>
                    <span className="font-medium text-truist-charcoal">{data.jobsByStatus[status]}</span>
                  </li>
                ))}
              </ul>
            </Card>
            <Card>
              <h2 className="mb-3 text-sm font-semibold text-truist-charcoal">Models by monitoring status</h2>
              <ul className="space-y-1.5 text-sm">
                {monitoringStatuses.map((status) => (
                  <li key={status} className="flex justify-between">
                    <span className="text-truist-darkGray">{status}</span>
                    <span className="font-medium text-truist-charcoal">
                      {data.modelsByStatus[status] ?? 0}
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          </div>

          <div className="flex gap-4">
            <Link
              to="/admin/tenants"
              className="rounded-md bg-truist-purple px-4 py-2 text-sm font-medium text-white hover:bg-truist-dusk"
            >
              Manage Tenants
            </Link>
            <Link
              to="/admin/group-mappings"
              className="rounded-md border border-truist-purple px-4 py-2 text-sm font-medium text-truist-purple hover:bg-truist-tint07"
            >
              Manage Group Mappings
            </Link>
          </div>
        </>
      ) : null}
    </div>
  );
}
