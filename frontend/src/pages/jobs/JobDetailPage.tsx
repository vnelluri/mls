import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { approveStep, getJob, overrideStep, rejectStep, resumeJob, retryJob, startJob, stopJob } from '@/api/jobsApi';
import { getPipeline, promotePipeline } from '@/api/pipelinesApi';
import type { ExecuteModelConfig, Job, Pipeline, PipelineStep } from '@/types/platform';
import { useTenantContext } from '@/auth/useTenantContext';
import { Button, Card, Field, InlineAlert, Input, Modal } from '@/components/shared/ui';
import { LoadingSpinner } from '@/components/shared/LoadingSpinner';
import { ConfirmDialog } from '@/components/shared/ConfirmDialog';
import { EnvironmentBadge, JobStatusBadge, StepStatusBadge } from '@/components/StatusBadge';
import { PipelineCanvas, stepsToCanvasSteps } from '@/components/canvas/PipelineCanvas';
import { stepTypeLabels } from '@/components/canvas/StepNode';
import { formatRelativeTime } from '@/lib/formatTime';
import { getJobActions } from '@/lib/jobActions';

const NON_TERMINAL: Job['status'][] = ['pending', 'running', 'awaiting_approval'];
const POLL_INTERVAL_MS = 5000;

function emrConsoleUrl(applicationId: string, jobRunId: string): string {
  return `https://console.aws.amazon.com/emr/serverless/home?region=us-east-1#/applications/${applicationId}/job-runs/${jobRunId}`;
}

export function JobDetailPage() {
  const { jobId } = useParams<{ jobId: string }>();
  // Set by the jobs list for cross-tenant viewers (PlatformAdmin / Operator);
  // absent for tenant-scoped users, whose own tenant is used server-side.
  const [searchParams] = useSearchParams();
  const tenantParam = searchParams.get('tenantId') ?? undefined;
  const navigate = useNavigate();
  const tenantContext = useTenantContext();
  const { canSubmitJob, canApproveStep } = tenantContext;

  const [job, setJob] = useState<Job | null>(null);
  const [pipeline, setPipeline] = useState<Pipeline | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [stopOpen, setStopOpen] = useState(false);
  const [rejectStepId, setRejectStepId] = useState<string | null>(null);

  const [promoteOpen, setPromoteOpen] = useState(false);
  const [ticket, setTicket] = useState('');
  const [promoting, setPromoting] = useState(false);
  const [promoteError, setPromoteError] = useState<string | null>(null);
  const [promoteSuccess, setPromoteSuccess] = useState<string | null>(null);

  const load = useCallback(
    async (opts?: { silent?: boolean }) => {
      if (!jobId) return;
      if (!opts?.silent) setLoading(true);
      setError(null);
      try {
        const j = await getJob(jobId, tenantParam);
        setJob(j);
        // Best-effort: fetch the pipeline definition to get step dependsOn
        // edges and execute_model EMR application IDs for the canvas/console
        // link. Note the pipeline may have since been edited past the
        // version this job actually ran (job.pipelineVersion) — this is
        // still the best available source for step wiring.
        try {
          const p = await getPipeline(j.pipelineId);
          setPipeline(p);
        } catch {
          setPipeline(null);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load job.');
      } finally {
        if (!opts?.silent) setLoading(false);
      }
    },
    [jobId, tenantParam],
  );

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!job || !NON_TERMINAL.includes(job.status)) return;
    const interval = setInterval(() => void load({ silent: true }), POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [job, load]);

  const pipelineStepsById = useMemo(() => {
    const map = new Map<string, PipelineStep>();
    pipeline?.steps.forEach((s) => map.set(s.stepId, s));
    return map;
  }, [pipeline]);

  const canvasSteps = useMemo(() => {
    if (!job) return [];
    const pipelineSteps: PipelineStep[] =
      pipeline?.steps ??
      // Fall back to a flat chain (no known dependsOn) if the pipeline
      // couldn't be fetched, so the canvas still renders something useful.
      job.steps.map((s, i, arr) => ({
        stepId: s.stepId,
        type: s.type,
        dependsOn: i > 0 ? [arr[i - 1].stepId] : [],
        config: {} as PipelineStep['config'],
      }));
    return stepsToCanvasSteps(pipelineSteps, job.steps);
  }, [job, pipeline]);

  // Staging jobs: the tenant's scientists (and Operator). Production jobs:
  // Operator stop/rerun; LDS overrides failed steps instead. Gate on the
  // pipeline's CURRENT environment — the freshly fetched pipeline object is
  // the most up-to-date source (it flips the instant promotion succeeds).
  const currentEnv = pipeline?.environment ?? job?.pipelineEnvironment ?? job?.runEnvironment;
  const actions = job
    ? getJobActions({ ...job, pipelineEnvironment: currentEnv }, tenantContext)
    : {
        canStart: false,
        canStop: false,
        canRestart: false,
        canResume: false,
        canOverride: false,
        restartLabel: 'Restart' as const,
      };
  const opsAllowed =
    currentEnv === 'production'
      ? tenantContext.canOperateProductionJobs
      : tenantContext.canOperateStagingJobs;
  // Promotion is the Lead Data Scientist's post-review action: only offered
  // once this job (the pipeline's staging run) has succeeded — the backend
  // enforces the same gate plus the ServiceNow ticket.
  const canPromote =
    canSubmitJob &&
    job?.status === 'success' &&
    pipeline?.environment === 'staging' &&
    pipeline.status !== 'archived';

  const handlePromote = async () => {
    if (!pipeline) return;
    setPromoteError(null);
    setPromoting(true);
    try {
      const updated = await promotePipeline(pipeline.pipelineId, ticket.trim());
      setPipeline(updated);
      setPromoteOpen(false);
      setTicket('');
      setPromoteSuccess(
        `Promoted to production under ServiceNow ${updated.serviceNowTicket} — the enterprise scheduler (ESP) can now trigger this job's pipeline.`,
      );
    } catch (err) {
      setPromoteError(err instanceof Error ? err.message : 'Failed to promote to production.');
    } finally {
      setPromoting(false);
    }
  };

  const handleStop = async () => {
    if (!job) return;
    setActionError(null);
    setBusy(true);
    try {
      const updated = await stopJob(job.jobId, tenantParam);
      setJob(updated);
      setStopOpen(false);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to stop job.');
    } finally {
      setBusy(false);
    }
  };

  const handleRetry = async () => {
    if (!job) return;
    setActionError(null);
    setBusy(true);
    try {
      const updated = await retryJob(job.jobId, tenantParam);
      setJob(updated);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to restart job.');
    } finally {
      setBusy(false);
    }
  };

  const handleStart = async () => {
    if (!job) return;
    setActionError(null);
    setBusy(true);
    try {
      const updated = await startJob(job.jobId, tenantParam);
      setJob(updated);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to start job.');
    } finally {
      setBusy(false);
    }
  };

  const handleResume = async () => {
    if (!job) return;
    setActionError(null);
    setBusy(true);
    try {
      const updated = await resumeJob(job.jobId, tenantParam);
      setJob(updated);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to resume job.');
    } finally {
      setBusy(false);
    }
  };

  const handleOverride = async (stepId: string) => {
    if (!job) return;
    setActionError(null);
    setBusy(true);
    try {
      const updated = await overrideStep(job.jobId, stepId);
      setJob(updated);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to override step.');
    } finally {
      setBusy(false);
    }
  };

  const handleApprove = async (stepId: string) => {
    if (!job) return;
    if (!canApproveStep) {
      setActionError('Only Lead Data Scientists can approve steps.');
      return;
    }
    setActionError(null);
    setBusy(true);
    try {
      const updated = await approveStep(job.jobId, stepId);
      setJob(updated);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to approve step.');
    } finally {
      setBusy(false);
    }
  };

  const handleReject = async (comment?: string) => {
    if (!job || !rejectStepId) return;
    if (!canApproveStep) {
      setActionError('Only Lead Data Scientists can reject steps.');
      return;
    }
    setActionError(null);
    try {
      const updated = await rejectStep(job.jobId, rejectStepId, comment ?? '');
      setJob(updated);
      setRejectStepId(null);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to reject step.');
    }
  };

  if (loading) return <LoadingSpinner label="Loading job…" />;
  if (error) return <InlineAlert kind="error">{error}</InlineAlert>;
  if (!job) return <InlineAlert kind="error">Job not found.</InlineAlert>;

  return (
    <div>
      <button
        onClick={() => navigate('/jobs')}
        className="mb-3 text-sm text-truist-purple hover:underline"
      >
        ← Back to jobs
      </button>
      <div className="mb-4 flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-truist-purple" title={job.jobId}>
            {pipeline?.name ?? job.pipelineName ?? job.pipelineId}
          </h1>
          <p className="text-sm text-truist-darkGray">
            Run <code className="text-xs">{job.runId}</code> · Submitted by {job.submittedBy}{' '}
            <span title={new Date(job.submittedAt).toLocaleString()}>
              ({formatRelativeTime(job.submittedAt)})
            </span>
            {job.triggeredVia === 'api' && (
              <span>
                {' '}
                · Triggered via scheduler API
                {job.externalRunId ? ` (external run ${job.externalRunId})` : ''}
              </span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {pipeline && <EnvironmentBadge environment={pipeline.environment} />}
          {job.runEnvironment && (
            <span
              className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                job.runEnvironment === 'production'
                  ? 'bg-green-50 text-[color:var(--status-passed)]'
                  : 'bg-orange-50 text-[color:var(--status-rework)]'
              }`}
              title={
                job.runEnvironment === 'staging' && currentEnv === 'production'
                  ? 'This run executed in staging, before the pipeline was promoted — restarting or resuming creates a production run.'
                  : 'Environment this run executed in.'
              }
            >
              {job.runEnvironment === 'production' ? 'Production run' : 'Staging run'}
            </span>
          )}
          <JobStatusBadge status={job.status} />
          <div className="flex gap-2">
            {canPromote && (
              <Button size="sm" onClick={() => setPromoteOpen(true)}>
                Promote to Production
              </Button>
            )}
            {actions.canStart && (
              <Button
                size="sm"
                onClick={() => void handleStart()}
                disabled={busy}
                title="Run this job now — newly created jobs wait until started."
              >
                Start
              </Button>
            )}
            {actions.canStop && (
              <Button variant="danger" size="sm" onClick={() => setStopOpen(true)}>
                Stop
              </Button>
            )}
            {actions.canResume && (
              <Button
                size="sm"
                onClick={() => void handleResume()}
                disabled={busy}
                title="Continue this job — completed steps keep their results, the rest re-run."
              >
                Resume
              </Button>
            )}
            {actions.canRestart && (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => void handleRetry()}
                disabled={busy}
                title="Run the job from the first step as a fresh run — each run's results land under their own date/run-ID prefix."
              >
                {actions.restartLabel}
              </Button>
            )}
            {!opsAllowed && (job.status === 'failed' || NON_TERMINAL.includes(job.status)) && (
              <span
                className="text-xs text-truist-midGray"
                title={
                  currentEnv === 'production'
                    ? 'Production jobs are operated by the Operator role — Lead Data Scientists can override a failed step below.'
                    : 'Your role has view-only access to jobs in this tenant.'
                }
              >
                View-only
              </span>
            )}
          </div>
        </div>
      </div>

      {actionError && (
        <div className="mb-4">
          <InlineAlert kind="error">{actionError}</InlineAlert>
        </div>
      )}

      {promoteSuccess && (
        <div className="mb-4">
          <InlineAlert kind="success">{promoteSuccess}</InlineAlert>
        </div>
      )}

      {pipeline?.environment === 'production' && pipeline.serviceNowTicket && (
        <div className="mb-4">
          <InlineAlert kind="info">
            Pipeline promoted to production by {pipeline.promotedBy}
            {pipeline.promotedAt ? ` on ${new Date(pipeline.promotedAt).toLocaleString()}` : ''} · ServiceNow{' '}
            {pipeline.serviceNowTicket}
          </InlineAlert>
        </div>
      )}

      {canPromote && (
        <div className="mb-4">
          <InlineAlert kind="warning">
            This job's pipeline is in <strong>Staging</strong> — the enterprise scheduler (ESP) cannot
            trigger it. The run succeeded; once you've reviewed the results, promote it to Production
            (a ServiceNow ticket is required for audit).
          </InlineAlert>
        </div>
      )}

      <Card className="mb-6">
        <h2 className="mb-3 text-sm font-semibold text-truist-charcoal">Pipeline diagram</h2>
        <PipelineCanvas steps={canvasSteps} />
      </Card>

      <Card className="mb-6">
        <h2 className="mb-3 text-sm font-semibold text-truist-charcoal">Step timeline</h2>
        <ol className="space-y-3">
          {job.steps.map((step) => {
            const pipelineStep = pipelineStepsById.get(step.stepId);
            const execConfig =
              pipelineStep?.type === 'execute_model' ? (pipelineStep.config as ExecuteModelConfig) : null;
            // The EMR application is platform-managed: new runs carry it in
            // step.resolved; pipelines stored before the change still have
            // it in their authored config.
            const emrApplicationId =
              (step.resolved?.emrApplicationId as string | undefined) ?? execConfig?.emrApplicationId;
            return (
              <li key={step.stepId} className="rounded-md border border-truist-gray06 p-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-truist-charcoal">
                      {stepTypeLabels[step.type]}
                    </span>
                    <span className="text-xs text-truist-midGray">{step.stepId}</span>
                  </div>
                  <StepStatusBadge status={step.status} />
                </div>
                <div className="mt-1 flex flex-wrap gap-x-4 text-xs text-truist-darkGray">
                  {step.startedAt && <span>Started {new Date(step.startedAt).toLocaleString()}</span>}
                  {step.completedAt && <span>Completed {new Date(step.completedAt).toLocaleString()}</span>}
                  {step.emrJobRunId && <span>EMR job run: {step.emrJobRunId}</span>}
                </div>
                {step.emrJobRunId && emrApplicationId && (
                  <a
                    href={emrConsoleUrl(emrApplicationId, step.emrJobRunId)}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-1 inline-block text-xs text-truist-purple underline"
                  >
                    View in AWS EMR Serverless console
                  </a>
                )}
                {step.emrStateDetail && (
                  <p className="mt-1 text-xs text-truist-darkGray">Detail: {step.emrStateDetail}</p>
                )}
                {step.errorMessage && (
                  <div className="mt-2">
                    <InlineAlert kind="error">{step.errorMessage}</InlineAlert>
                  </div>
                )}
                {step.status === 'failed' && tenantContext.canOverrideFailedStep && (
                  <div className="mt-2">
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={busy}
                      title="Mark this failed step as succeeded (recorded in the audit log) so the run continues."
                      onClick={() => void handleOverride(step.stepId)}
                    >
                      Override failure
                    </Button>
                  </div>
                )}
                {step.output && Object.keys(step.output).length > 0 && (
                  <pre className="mt-2 overflow-x-auto rounded bg-truist-gray07 p-2 text-xs">
                    {JSON.stringify(step.output, null, 2)}
                  </pre>
                )}

                {step.type === 'approval' && step.status === 'awaiting_approval' && (
                  <div className="mt-3 border-t border-truist-gray06 pt-3">
                    {job.steps.some(
                      (s) => s.type === 'data_quality_check' && s.output?.derivedStatus === 'Rework',
                    ) && (
                      <div className="mb-3">
                        <InlineAlert kind="warning">
                          This run's monitoring derived <strong>Rework</strong> (warning-zone drift or
                          error rate) and the model is now <strong>InReview</strong>. Approving accepts
                          the warning-zone metrics (model returns to Passed); rejecting sends it back
                          for rework.
                        </InlineAlert>
                      </div>
                    )}
                    <div className="flex gap-2">
                    {canApproveStep ? (
                      <>
                        <Button size="sm" onClick={() => void handleApprove(step.stepId)} disabled={busy}>
                          Approve
                        </Button>
                        <Button
                          variant="danger"
                          size="sm"
                          onClick={() => setRejectStepId(step.stepId)}
                          disabled={busy}
                        >
                          Reject
                        </Button>
                      </>
                    ) : (
                      <span
                        className="text-xs text-truist-midGray"
                        title="Platform Admins have view-only access across tenants — sign in as a Lead Data Scientist to approve or reject this step."
                      >
                        Awaiting a Lead Data Scientist's review — view-only in your current role.
                      </span>
                    )}
                    </div>
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      </Card>

      {job.runHistory.length > 0 && (
        <Card>
          <h2 className="mb-3 text-sm font-semibold text-truist-charcoal">Run history</h2>
          <ul className="space-y-1 text-sm text-truist-darkGray">
            {job.runHistory.map((run) => (
              <li key={run.runId} className="flex justify-between">
                <span>{run.runId}</span>
                <span>
                  {new Date(run.startedAt).toLocaleString()}
                  {run.endedAt ? ` – ${new Date(run.endedAt).toLocaleString()}` : ' (in progress)'}
                </span>
                <span className="font-medium">{run.finalStatus}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <ConfirmDialog
        open={stopOpen}
        title="Stop job"
        description="This stops the job in its current state. It can be resumed or restarted afterwards. Are you sure?"
        confirmLabel="Stop job"
        danger
        onConfirm={() => handleStop()}
        onCancel={() => setStopOpen(false)}
      />

      <Modal
        open={promoteOpen}
        onClose={() => {
          setPromoteOpen(false);
          setPromoteError(null);
        }}
        title="Promote to Production"
      >
        <p className="mb-4 text-sm text-truist-darkGray">
          Promoting makes this job's pipeline triggerable by the enterprise scheduler (ESP). A ServiceNow
          change ticket is required — it is recorded on the pipeline and in the audit log.
        </p>
        {promoteError && (
          <div className="mb-3">
            <InlineAlert kind="error">{promoteError}</InlineAlert>
          </div>
        )}
        <Field
          label="ServiceNow ticket"
          required
          hint="Change-management record authorizing this promotion, e.g. CHG0031245, RITM0012003 or INC0045678."
        >
          <Input
            value={ticket}
            onChange={(e) => setTicket(e.target.value)}
            placeholder="CHG0031245"
            autoFocus
          />
        </Field>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setPromoteOpen(false)} disabled={promoting}>
            Cancel
          </Button>
          <Button onClick={() => void handlePromote()} disabled={promoting || !ticket.trim()}>
            {promoting ? 'Promoting…' : 'Promote'}
          </Button>
        </div>
      </Modal>

      <ConfirmDialog
        open={!!rejectStepId}
        title="Reject step"
        description="Rejecting sends this job back for rework. A comment is required so the submitter understands why."
        confirmLabel="Reject"
        danger
        requireComment
        commentLabel="Reason for rejection (required)"
        onConfirm={(comment) => handleReject(comment)}
        onCancel={() => setRejectStepId(null)}
      />

      <div className="mt-4">
        <Button variant="ghost" size="sm" onClick={() => navigate('/jobs')}>
          Back to jobs
        </Button>
      </div>
    </div>
  );
}
