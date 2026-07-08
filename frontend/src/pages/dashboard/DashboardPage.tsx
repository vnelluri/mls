import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getDashboardSummary } from '@/api/dashboardApi';
import { useTenantContext } from '@/auth/useTenantContext';
import { JobStatusBadge } from '@/components/StatusBadge';
import { LoadingSpinner } from '@/components/shared/LoadingSpinner';
import { Card, InlineAlert } from '@/components/shared/ui';
import type { DashboardSummary, JobStatus, MonitoringStatus } from '@/types/platform';

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

function StatTile({ label, value, to }: { label: string; value: number | string; to?: string }) {
  const body = (
    <Card className="flex h-full flex-col gap-1 transition-shadow hover:shadow-md">
      <span className="text-xs font-medium uppercase tracking-wide text-truist-darkGray">{label}</span>
      <span className="text-2xl font-semibold text-truist-purple">{value}</span>
    </Card>
  );
  return to ? <Link to={to}>{body}</Link> : body;
}

function formatWhen(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

export function DashboardPage() {
  const { isPlatformAdmin, canSubmitJob, tenantId } = useTenantContext();
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const summary = await getDashboardSummary();
        if (!cancelled) setData(summary);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load dashboard data.');
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
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="mb-1 text-xl font-semibold text-truist-purple">Dashboard</h1>
          <p className="text-sm text-truist-darkGray">
            {isPlatformAdmin
              ? 'Cross-tenant platform overview (view-only).'
              : `Overview for tenant ${tenantId ?? '—'}.`}
          </p>
        </div>
        {canSubmitJob && (
          <Link
            to="/jobs"
            className="rounded-md bg-truist-purple px-4 py-2 text-sm font-medium text-white hover:bg-truist-dusk"
          >
            Create New Job
          </Link>
        )}
      </div>

      {error && (
        <div className="mb-4">
          <InlineAlert kind="error">{error}</InlineAlert>
        </div>
      )}

      {loading && !data ? (
        <LoadingSpinner label="Loading dashboard…" />
      ) : data ? (
        <>
          <div
            className={`mb-6 grid grid-cols-2 gap-4 ${isPlatformAdmin ? 'md:grid-cols-4' : 'md:grid-cols-3'}`}
          >
            {isPlatformAdmin && data.tenantCount !== null && (
              <StatTile label="Tenants" value={data.tenantCount} to="/admin/tenants" />
            )}
            <StatTile label="Jobs running" value={data.jobs.byStatus.running} to="/jobs" />
            <StatTile
              label="Awaiting approval"
              value={data.jobs.byStatus.awaiting_approval}
              to="/jobs"
            />
            <StatTile label="Models" value={data.models.total} to="/models" />
          </div>

          <div className="mb-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
            <Card>
              <h2 className="mb-3 text-sm font-semibold text-truist-charcoal">Jobs by status</h2>
              <ul className="space-y-1.5 text-sm">
                {jobStatuses.map((status) => (
                  <li key={status} className="flex justify-between">
                    <span className="text-truist-darkGray">{status.replace('_', ' ')}</span>
                    <span className="font-medium text-truist-charcoal">
                      {data.jobs.byStatus[status] ?? 0}
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
            <Card>
              <h2 className="mb-3 text-sm font-semibold text-truist-charcoal">
                Models by monitoring status
              </h2>
              <ul className="space-y-1.5 text-sm">
                {monitoringStatuses.map((status) => (
                  <li key={status} className="flex justify-between">
                    <span className="text-truist-darkGray">{status}</span>
                    <span className="font-medium text-truist-charcoal">
                      {data.models.byMonitoringStatus[status] ?? 0}
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          </div>

          <div className="mb-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
            <Card>
              <h2 className="mb-3 text-sm font-semibold text-truist-charcoal">Recent jobs</h2>
              {data.recentJobs.length === 0 ? (
                <p className="text-sm text-truist-darkGray">No jobs yet.</p>
              ) : (
                <ul className="divide-y divide-truist-gray06 text-sm">
                  {data.recentJobs.map((job) => (
                    <li key={job.jobId} className="flex items-center justify-between gap-3 py-2">
                      <div className="min-w-0">
                        <Link
                          to={`/jobs/${job.jobId}`}
                          className="block truncate font-medium text-truist-purple hover:underline"
                          title={job.jobId}
                        >
                          {job.pipelineName ?? job.pipelineId}
                        </Link>
                        <span className="block truncate text-xs text-truist-darkGray">
                          {isPlatformAdmin ? `${job.tenantId} · ` : ''}
                          Run {job.runId} · {formatWhen(job.submittedAt)}
                        </span>
                      </div>
                      <JobStatusBadge status={job.status} />
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card>
              <h2 className="mb-3 text-sm font-semibold text-truist-charcoal">Recent activity</h2>
              {data.recentAuditEvents.length === 0 ? (
                <p className="text-sm text-truist-darkGray">No audit events yet.</p>
              ) : (
                <ul className="divide-y divide-truist-gray06 text-sm">
                  {data.recentAuditEvents.map((event) => (
                    <li key={`${event.timestamp}-${event.eventId}`} className="py-2">
                      <span className="block font-medium text-truist-charcoal">{event.action}</span>
                      <span className="block truncate text-xs text-truist-darkGray">
                        {event.summary} · {formatWhen(event.timestamp)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              <div className="mt-3">
                <Link to="/audit" className="text-sm font-medium text-truist-purple hover:underline">
                  View full audit log →
                </Link>
              </div>
            </Card>
          </div>

          {isPlatformAdmin && (
            <div className="flex flex-wrap gap-4">
              <Link
                to="/admin"
                className="rounded-md border border-truist-purple px-4 py-2 text-sm font-medium text-truist-purple hover:bg-truist-tint07"
              >
                Admin Console
              </Link>
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}
