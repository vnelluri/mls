import type { Job } from '@/types/platform';
import type { TenantContext } from '@/auth/useTenantContext';

const NON_TERMINAL: Job['status'][] = ['pending', 'running', 'awaiting_approval'];
// A successful job can be rerun (next sequential run id — results land under
// their own <date>/<runId>/ prefix). Resume only applies to interrupted runs.
const RERUNNABLE: Job['status'][] = ['failed', 'cancelled', 'success'];
const RESUMABLE: Job['status'][] = ['failed', 'cancelled'];

export interface JobActions {
  /** Kick off a newly created job — jobs sit in `pending` until started. */
  canStart: boolean;
  canStop: boolean;
  /** Button label for the rerun action: "Run Again" after a success,
   * "Restart" after a failure/cancellation. */
  restartLabel: 'Run Again' | 'Restart';
  canRestart: boolean;
  /** Restart that keeps completed steps — only offered when there is at
   * least one completed step to keep (otherwise it equals Restart). */
  canResume: boolean;
  /** LDS-only: mark a failed step succeeded so the run proceeds. */
  canOverride: boolean;
}

/** Single source of truth for which job operations the current user may take
 * on a given job — staging runs are operated by the tenant's scientists,
 * production runs by the Operator (ESP triggers them; LDS overrides failed
 * steps instead). Keep the list page and the detail page on this matrix. */
export function getJobActions(
  job: Job,
  ctx: Pick<TenantContext, 'canOperateStagingJobs' | 'canOperateProductionJobs' | 'canOverrideFailedStep'>,
): JobActions {
  // Gate on the pipeline's CURRENT environment — a staging job becomes
  // Operator territory the moment its pipeline is promoted. Fall back to the
  // run's snapshot when the join is unavailable.
  const isProduction = (job.pipelineEnvironment ?? job.runEnvironment) === 'production';
  const opsAllowed = isProduction ? ctx.canOperateProductionJobs : ctx.canOperateStagingJobs;
  const hasCompletedStep = job.steps.some((s) => s.status === 'succeeded' || s.status === 'approved');

  return {
    canStart: opsAllowed && job.status === 'pending',
    canStop: opsAllowed && NON_TERMINAL.includes(job.status),
    restartLabel: job.status === 'success' ? 'Run Again' : 'Restart',
    canRestart: opsAllowed && RERUNNABLE.includes(job.status),
    canResume: opsAllowed && RESUMABLE.includes(job.status) && hasCompletedStep,
    canOverride:
      ctx.canOverrideFailedStep && job.status === 'failed' && job.steps.some((s) => s.status === 'failed'),
  };
}
