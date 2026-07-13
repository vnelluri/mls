import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { listJobs, resumeJob, retryJob, startJob, stopJob } from '@/api/jobsApi';
import type { Job } from '@/types/platform';
import { useTenantContext } from '@/auth/useTenantContext';
import { Button, InlineAlert } from '@/components/shared/ui';
import { ConfirmDialog } from '@/components/shared/ConfirmDialog';
import { DataTable, type DataTableColumn } from '@/components/shared/DataTable';
import { Pagination } from '@/components/shared/Pagination';
import { JobStatusBadge } from '@/components/StatusBadge';
import { CreateJobWizard } from '@/components/jobs/CreateJobWizard';
import { formatRelativeTime } from '@/lib/formatTime';
import { getJobActions } from '@/lib/jobActions';

const TERMINAL_STATUSES: Job['status'][] = ['success', 'failed', 'cancelled'];
const POLL_INTERVAL_MS = 5000;

type StatusFilter = 'all' | Job['status'];

// Ordered by operator triage priority — needs-action statuses first, so the
// most useful filter is never scrolled off on narrow screens.
const STATUS_FILTERS: { value: StatusFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'awaiting_approval', label: 'Awaiting approval' },
  { value: 'failed', label: 'Failed' },
  { value: 'running', label: 'Running' },
  { value: 'pending', label: 'Pending' },
  { value: 'success', label: 'Success' },
  { value: 'cancelled', label: 'Cancelled' },
];

function rowClassName(job: Job): string {
  if (job.status === 'failed') return 'bg-red-50/60';
  if (job.status === 'awaiting_approval') return 'bg-orange-50/50';
  return '';
}

export function JobsListPage() {
  const tenantContext = useTenantContext();
  const { canSubmitJob, isPlatformAdmin, isOperator, seesAllTenants } = tenantContext;
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [data, setData] = useState<{ items: Job[]; total: number }>({ items: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<Date | null>(null);

  const [wizardOpen, setWizardOpen] = useState(false);

  const [actionBusyId, setActionBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [stopTarget, setStopTarget] = useState<Job | null>(null);

  const load = useCallback(
    async (opts?: { silent?: boolean }) => {
      if (!opts?.silent) setLoading(true);
      setError(null);
      try {
        const res = await listJobs({
          page,
          pageSize,
          status: statusFilter === 'all' ? undefined : statusFilter,
        });
        setData({ items: res.items, total: res.total });
        setLastUpdatedAt(new Date());
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load jobs.');
      } finally {
        if (!opts?.silent) setLoading(false);
      }
    },
    [page, pageSize, statusFilter],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const handleStatusFilterChange = (value: StatusFilter) => {
    setStatusFilter(value);
    setPage(1);
  };

  const runAction = async (job: Job, action: () => Promise<Job>, verb: string) => {
    setActionBusyId(job.jobId);
    setActionError(null);
    try {
      await action();
      await load({ silent: true });
    } catch (err) {
      setActionError(err instanceof Error ? `Failed to ${verb} ${job.jobId}: ${err.message}` : `Failed to ${verb} job.`);
    } finally {
      setActionBusyId(null);
    }
  };

  const hasNonTerminal = data.items.some((j) => !TERMINAL_STATUSES.includes(j.status));
  const hasNonTerminalRef = useRef(hasNonTerminal);
  hasNonTerminalRef.current = hasNonTerminal;

  useEffect(() => {
    if (!hasNonTerminal) return;
    const interval = setInterval(() => {
      if (hasNonTerminalRef.current) void load({ silent: true });
    }, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasNonTerminal, load]);

  const columns: DataTableColumn<Job>[] = [
    {
      key: 'name',
      header: 'Job',
      render: (j) => (
        <span className="font-medium" title={j.jobId}>
          {j.pipelineName ?? j.pipelineId}
        </span>
      ),
    },
    ...(seesAllTenants
      ? [{ key: 'tenantId', header: 'Tenant', render: (j: Job) => j.tenantId } as DataTableColumn<Job>]
      : []),
    {
      key: 'runId',
      header: 'Run ID',
      render: (j) => (
        <code className="text-xs" title="Results of each run land under <output path>/<date>/<run ID>/.">
          {j.runId}
        </code>
      ),
    },
    { key: 'status', header: 'Status', render: (j) => <JobStatusBadge status={j.status} /> },
    {
      key: 'environment',
      header: 'Environment',
      render: (j) => {
        // The pipeline's current environment — flips to Production as soon
        // as the job's pipeline is promoted (runEnvironment is only the
        // fallback for jobs whose pipeline no longer exists).
        const env = j.pipelineEnvironment ?? j.runEnvironment;
        if (!env) return '—';
        return (
          <span
            className={`rounded-full px-2 py-0.5 text-xs font-medium ${
              env === 'production'
                ? 'bg-green-50 text-[color:var(--status-passed)]'
                : 'bg-orange-50 text-[color:var(--status-rework)]'
            }`}
            title={
              env === 'production'
                ? 'Promoted to Production — the enterprise scheduler (ESP) can trigger this job; it is operated by Operators.'
                : 'Staging — manual, reviewable runs until promoted to Production with a ServiceNow ticket.'
            }
          >
            {env === 'production' ? 'Production' : 'Staging'}
          </span>
        );
      },
    },
    { key: 'submittedBy', header: 'Submitted by', render: (j) => j.submittedBy },
    {
      key: 'submittedAt',
      header: 'Submitted',
      render: (j) => (
        <span title={new Date(j.submittedAt).toLocaleString()}>{formatRelativeTime(j.submittedAt)}</span>
      ),
    },
    {
      key: 'actions',
      header: 'Actions',
      render: (j) => {
        const actions = getJobActions(j, tenantContext);
        const tenantArg = seesAllTenants ? j.tenantId : undefined;
        const busy = actionBusyId === j.jobId;
        if (!actions.canStart && !actions.canStop && !actions.canRestart && !actions.canResume) {
          return <span className="text-xs text-truist-midGray">—</span>;
        }
        return (
          // Buttons must not trigger the row's navigate-to-detail click.
          <div className="flex gap-1.5" onClick={(e) => e.stopPropagation()}>
            {actions.canStart && (
              <Button
                size="sm"
                disabled={busy}
                title="Run this job now — newly created jobs wait until started."
                onClick={() => void runAction(j, () => startJob(j.jobId, tenantArg), 'start')}
              >
                Start
              </Button>
            )}
            {actions.canStop && (
              <Button variant="danger" size="sm" disabled={busy} onClick={() => setStopTarget(j)}>
                Stop
              </Button>
            )}
            {actions.canResume && (
              <Button
                size="sm"
                disabled={busy}
                title="Continue this job — completed steps keep their results, the rest re-run."
                onClick={() => void runAction(j, () => resumeJob(j.jobId, tenantArg), 'resume')}
              >
                Resume
              </Button>
            )}
            {actions.canRestart && (
              <Button
                variant="secondary"
                size="sm"
                disabled={busy}
                title="Run the job from the first step as a fresh run — each run's results land under their own date/run-ID prefix."
                onClick={() => void runAction(j, () => retryJob(j.jobId, tenantArg), 'rerun')}
              >
                {actions.restartLabel}
              </Button>
            )}
          </div>
        );
      },
    },
  ];

  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <h1 className="text-xl font-semibold text-truist-purple">Jobs</h1>
        {canSubmitJob ? (
          <Button onClick={() => setWizardOpen(true)}>Create New Job</Button>
        ) : (
          <span title="Platform Admins have view-only access across tenants — sign in as a Lead Data Scientist to create a job.">
            <Button disabled>Create New Job</Button>
          </span>
        )}
      </div>

      <div className="mb-4 flex items-center gap-1.5 text-xs text-truist-midGray">
        {hasNonTerminal && (
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[color:var(--status-passed)]" aria-hidden="true" />
        )}
        <span>
          {hasNonTerminal ? 'Live — ' : ''}
          {lastUpdatedAt ? `Updated ${formatRelativeTime(lastUpdatedAt.toISOString())}` : 'Loading…'}
        </span>
        <button
          onClick={() => void load({ silent: true })}
          className="ml-1 font-medium text-truist-purple hover:underline"
        >
          Refresh
        </button>
      </div>

      <div className="mb-4 flex flex-wrap gap-2" role="tablist" aria-label="Filter jobs by status">
        {STATUS_FILTERS.map((f) => (
          <button
            key={f.value}
            role="tab"
            aria-selected={statusFilter === f.value}
            onClick={() => handleStatusFilterChange(f.value)}
            className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-truist-skyBlue focus-visible:ring-offset-1 ${
              statusFilter === f.value
                ? 'border-truist-purple bg-truist-purple text-white'
                : 'border-truist-lightGray bg-white text-truist-darkGray hover:bg-truist-tint07'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {!canSubmitJob && isPlatformAdmin && (
        <div className="mb-4">
          <InlineAlert kind="info">
            Platform Admins have view-only access across tenants — sign in as a Lead Data Scientist to
            submit a job.
          </InlineAlert>
        </div>
      )}
      {isOperator && (
        <div className="mb-4">
          <InlineAlert kind="info">
            Operators operate jobs across every tenant — stop, restart, resume, including production
            runs — job submission is a Lead Data Scientist action.
          </InlineAlert>
        </div>
      )}

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
        rows={data.items}
        rowKey={(j) => j.jobId}
        rowClassName={rowClassName}
        loading={loading}
        emptyTitle={statusFilter === 'all' ? 'No jobs yet' : 'No jobs match this filter'}
        emptyDescription={
          statusFilter !== 'all'
            ? 'Try a different status filter, or select "All" to see every job.'
            : canSubmitJob
              ? 'Create a new job — define its details and pipeline, review, then start it when ready.'
              : undefined
        }
        onRowClick={(j) =>
          // Cross-tenant viewers have no tenant of their own — the detail
          // page needs the job's tenant to look it up.
          navigate(seesAllTenants ? `/jobs/${j.jobId}?tenantId=${j.tenantId}` : `/jobs/${j.jobId}`)
        }
      />
      <Pagination data={{ total: data.total, page, pageSize }} onPageChange={setPage} />

      <ConfirmDialog
        open={!!stopTarget}
        title="Stop job"
        description={`Stop job ${stopTarget?.jobId ?? ''}? Its current run is cancelled — you can resume or restart it afterwards.`}
        confirmLabel="Stop job"
        onConfirm={() => {
          if (stopTarget) {
            const target = stopTarget;
            setStopTarget(null);
            void runAction(target, () => stopJob(target.jobId, seesAllTenants ? target.tenantId : undefined), 'stop');
          }
        }}
        onCancel={() => setStopTarget(null)}
      />

      {wizardOpen && (
        <CreateJobWizard
          open={wizardOpen}
          onClose={() => setWizardOpen(false)}
          onCreated={(job) => {
            setWizardOpen(false);
            navigate(`/jobs/${job.jobId}`);
          }}
        />
      )}
    </div>
  );
}
