import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { getDashboardSummary } from '@/api/dashboardApi';
import { uploadArtifact, type ArtifactUploadResult } from '@/api/modelsApi';
import { useTenantContext } from '@/auth/useTenantContext';
import { EmrAppStateBadge, JobStatusBadge, MonitoringStatusBadge } from '@/components/StatusBadge';
import { Button, Card, InlineAlert } from '@/components/shared/ui';
import { formatRelativeTime } from '@/lib/formatTime';
import type { DashboardSummary, EmrApplication, JobStatus, MonitoringStatus } from '@/types/platform';

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
      <span className="text-2xl font-semibold tabular-nums text-truist-purple">{value}</span>
    </Card>
  );
  return to ? (
    <Link
      to={to}
      className="block h-full rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-truist-skyBlue"
    >
      {body}
    </Link>
  ) : (
    body
  );
}

// Badge + proportional bar + count. Bars are relative to the largest bucket;
// color/label come from the shared status badges, the bar itself is decorative.
function StatusBreakdown({ rows }: { rows: { badge: ReactNode; count: number; key: string }[] }) {
  const max = Math.max(1, ...rows.map((r) => r.count));
  return (
    <ul className="space-y-2 text-sm">
      {rows.map(({ badge, count, key }) => (
        <li key={key} className="flex items-center gap-3">
          <span className="w-40 shrink-0">{badge}</span>
          <span aria-hidden="true" className="h-1.5 flex-1 overflow-hidden rounded-full bg-truist-gray07">
            <span
              className="block h-full rounded-full bg-truist-dawn"
              style={{ width: `${(count / max) * 100}%` }}
            />
          </span>
          <span className="w-10 text-right font-medium tabular-nums text-truist-charcoal">
            {count}
          </span>
        </li>
      ))}
    </ul>
  );
}

// ── EMR compute card, mirroring TMT's ComputePanel: state badge, running /
// queued counts, and an estimated capacity meter per application. ──────────

function EmrCapacityMeter({ app }: { app: EmrApplication }) {
  const pct = app.utilizationPct;
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between text-xs">
        <span className="text-truist-darkGray">
          Capacity{' '}
          <span className="text-truist-midGray">
            ({app.allocatedVcpuEstimate} / {app.maxVcpu ?? '—'} vCPU
            {app.estimated ? ', estimated' : ''})
          </span>
        </span>
        <span className="font-mono text-truist-charcoal">{pct !== null ? `${pct}%` : '—'}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-truist-gray07">
        <div
          className={`h-full rounded-full transition-all ${
            (pct ?? 0) >= 85 ? 'bg-status-rework' : 'bg-truist-purple'
          }`}
          style={{ width: `${Math.min(100, pct ?? 0)}%` }}
        />
      </div>
    </div>
  );
}

/** One application, full-size: big running/queued tiles above the meter. */
function EmrApplicationPanel({ app }: { app: EmrApplication }) {
  return (
    <div>
      <div className="mb-4 grid grid-cols-2 gap-4">
        <div className="rounded-lg border border-truist-gray06 px-4 py-3">
          <p className="text-xs uppercase tracking-wide text-truist-midGray">Running jobs</p>
          <p className="mt-1 text-2xl font-semibold tabular-nums text-truist-charcoal">
            {app.runningJobRuns}
          </p>
        </div>
        <div className="rounded-lg border border-truist-gray06 px-4 py-3">
          <p className="text-xs uppercase tracking-wide text-truist-midGray">Queued jobs</p>
          <p className="mt-1 text-2xl font-semibold tabular-nums text-truist-charcoal">
            {app.queuedJobRuns}
          </p>
        </div>
      </div>
      <EmrCapacityMeter app={app} />
      <p className="mt-3 truncate font-mono text-xs text-truist-midGray" title={app.applicationId}>
        {app.applicationId}
      </p>
    </div>
  );
}

/** One application, compact: a row per tenant when the platform admin sees
 * several applications in the same card. */
function EmrApplicationRow({ app }: { app: EmrApplication }) {
  return (
    <li>
      <div className="mb-1 flex items-center justify-between gap-2">
        <p className="truncate text-sm font-medium text-truist-charcoal">{app.tenantId}</p>
        <EmrAppStateBadge state={app.state} />
      </div>
      <p className="mb-1.5 text-xs text-truist-darkGray">
        <span className="font-semibold text-truist-charcoal">{app.runningJobRuns}</span> running ·{' '}
        <span className="font-semibold text-truist-charcoal">{app.queuedJobRuns}</span> queued
      </p>
      <EmrCapacityMeter app={app} />
      <p className="mt-1.5 truncate font-mono text-xs text-truist-midGray" title={app.applicationId}>
        {app.applicationId}
      </p>
    </li>
  );
}

/** Upload a model artifact into the platform artifacts bucket (tenant
 * prefix) and surface the returned S3 URI to paste into Register Model. */
function ArtifactUploadCard() {
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<ArtifactUploadResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const handleFile = async (file: File) => {
    setUploading(true);
    setError(null);
    setResult(null);
    setCopied(false);
    try {
      setResult(await uploadArtifact(file));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to upload artifact.');
    } finally {
      setUploading(false);
    }
  };

  return (
    <Card>
      <h2 className="mb-1 text-sm font-semibold text-truist-charcoal">Upload model artifact</h2>
      <p className="mb-3 text-xs text-truist-darkGray">
        Uploads to the platform artifacts bucket under your tenant&apos;s prefix. Use the returned
        URI when{' '}
        <Link to="/models" className="font-medium text-truist-purple hover:underline">
          registering a model
        </Link>
        .
      </p>
      {error && (
        <div className="mb-3">
          <InlineAlert kind="error">{error}</InlineAlert>
        </div>
      )}
      <div className="flex items-center gap-3 text-sm">
        <input
          type="file"
          disabled={uploading}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void handleFile(file);
            // allow re-selecting the same file after a failure
            e.target.value = '';
          }}
        />
        {uploading && <span className="text-truist-darkGray">Uploading…</span>}
      </div>
      {result && (
        <div className="mt-3 flex items-center gap-2">
          <code
            className="min-w-0 flex-1 truncate rounded bg-truist-gray07 px-2 py-1 font-mono text-xs text-truist-charcoal"
            title={result.artifactS3Uri}
          >
            {result.artifactS3Uri}
          </code>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              void navigator.clipboard.writeText(result.artifactS3Uri);
              setCopied(true);
            }}
          >
            {copied ? 'Copied' : 'Copy'}
          </Button>
        </div>
      )}
    </Card>
  );
}

function DashboardSkeleton() {
  return (
    <div role="status" aria-label="Loading dashboard" className="animate-pulse motion-reduce:animate-none">
      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-20 rounded-lg bg-truist-gray07" />
        ))}
      </div>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {[0, 1].map((i) => (
          <div key={i} className="h-52 rounded-lg bg-truist-gray07" />
        ))}
      </div>
    </div>
  );
}


export function DashboardPage() {
  const { isPlatformAdmin, canSubmitJob, canRegisterModel, tenantId } = useTenantContext();
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (isCancelled: () => boolean = () => false) => {
    setLoading(true);
    setError(null);
    try {
      const summary = await getDashboardSummary();
      if (!isCancelled()) setData(summary);
    } catch (err) {
      if (!isCancelled()) {
        setError(err instanceof Error ? err.message : 'Failed to load dashboard data.');
      }
    } finally {
      if (!isCancelled()) setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    void load(() => cancelled);
    return () => {
      cancelled = true;
    };
  }, [load]);

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
            className="rounded-md bg-truist-purple px-4 py-2 text-sm font-medium text-white hover:bg-truist-dusk focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-truist-skyBlue"
          >
            Create New Job
          </Link>
        )}
      </div>

      {error && (
        <div className="mb-4 flex items-start gap-3">
          <div className="flex-1">
            <InlineAlert kind="error">{error}</InlineAlert>
          </div>
          <Button variant="secondary" size="sm" disabled={loading} onClick={() => void load()}>
            Retry
          </Button>
        </div>
      )}

      {loading && !data ? (
        <DashboardSkeleton />
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

          <div className="mb-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
            <Card>
              <h2 className="mb-3 text-sm font-semibold text-truist-charcoal">Jobs by status</h2>
              <StatusBreakdown
                rows={jobStatuses.map((status) => ({
                  key: status,
                  badge: <JobStatusBadge status={status} />,
                  count: data.jobs.byStatus[status] ?? 0,
                }))}
              />
            </Card>
            <Card>
              <div className="mb-3 flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <img src="/emr.svg" alt="" className="h-4 w-4" />
                  <h2 className="text-sm font-semibold text-truist-charcoal">EMR compute</h2>
                </div>
                {data.emr.applications.length === 1 && (
                  <EmrAppStateBadge state={data.emr.applications[0].state} />
                )}
              </div>
              {data.emr.applications.length === 0 ? (
                <p className="text-sm text-truist-darkGray">No EMR applications.</p>
              ) : data.emr.applications.length === 1 ? (
                <EmrApplicationPanel app={data.emr.applications[0]} />
              ) : (
                <ul className="divide-y divide-truist-gray06 [&>li]:py-3 [&>li:first-child]:pt-0 [&>li:last-child]:pb-0">
                  {data.emr.applications.map((app) => (
                    <EmrApplicationRow key={app.applicationId} app={app} />
                  ))}
                </ul>
              )}
            </Card>
            <Card>
              <h2 className="mb-3 text-sm font-semibold text-truist-charcoal">
                Models by monitoring status
              </h2>
              <StatusBreakdown
                rows={monitoringStatuses.map((status) => ({
                  key: status,
                  badge: <MonitoringStatusBadge status={status} />,
                  count: data.models.byMonitoringStatus[status] ?? 0,
                }))}
              />
            </Card>
          </div>

          <div className="mb-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
            <Card>
              <h2 className="mb-3 text-sm font-semibold text-truist-charcoal">Recent jobs</h2>
              {data.recentJobs.length === 0 ? (
                <p className="text-sm text-truist-darkGray">
                  No jobs yet.
                  {canSubmitJob && (
                    <>
                      {' '}
                      <Link to="/jobs" className="font-medium text-truist-purple hover:underline">
                        Create your first job
                      </Link>
                    </>
                  )}
                </p>
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
                        <span
                          className="block truncate text-xs text-truist-darkGray"
                          title={new Date(job.submittedAt).toLocaleString()}
                        >
                          {isPlatformAdmin ? `${job.tenantId} · ` : ''}
                          Run {job.runId} · {formatRelativeTime(job.submittedAt)}
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
                      <span
                        className="block truncate text-xs text-truist-darkGray"
                        title={new Date(event.timestamp).toLocaleString()}
                      >
                        {event.summary} · {formatRelativeTime(event.timestamp)}
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

          {canRegisterModel && (
            <div className="mb-6">
              <ArtifactUploadCard />
            </div>
          )}

          {isPlatformAdmin && (
            <div className="flex flex-wrap gap-4">
              <Link
                to="/admin"
                className="rounded-md border border-truist-purple px-4 py-2 text-sm font-medium text-truist-purple hover:bg-truist-tint07 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-truist-skyBlue"
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
