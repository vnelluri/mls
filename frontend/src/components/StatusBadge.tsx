import type { JobStatus, MonitoringStatus, PipelineEnvironment, StepStatus } from '@/types/platform';

// The SINGLE place that maps status enums to a colored pill. Every other
// component must render status via this component rather than inlining its
// own color logic, so the exact palette values stay consistent everywhere.

const monitoringStatusMeta: Record<MonitoringStatus, { label: string; var: string }> = {
  Passed: { label: 'Passed', var: '--status-passed' },
  Failed: { label: 'Failed', var: '--status-failed' },
  Rework: { label: 'Rework', var: '--status-rework' },
  InReview: { label: 'In review', var: '--status-in-review' },
  NotStarted: { label: 'Not started', var: '--status-not-started' },
};

const jobStatusMeta: Record<JobStatus, { label: string; var: string }> = {
  pending: { label: 'Pending', var: '--status-not-started' },
  running: { label: 'Running', var: '--status-in-review' },
  awaiting_approval: { label: 'Awaiting approval', var: '--status-rework' },
  success: { label: 'Success', var: '--status-passed' },
  failed: { label: 'Failed', var: '--status-failed' },
  cancelled: { label: 'Cancelled', var: '--status-not-started' },
};

const stepStatusMeta: Record<StepStatus, { label: string; var: string }> = {
  idle: { label: 'Idle', var: '--status-not-started' },
  running: { label: 'Running', var: '--status-in-review' },
  succeeded: { label: 'Succeeded', var: '--status-passed' },
  failed: { label: 'Failed', var: '--status-failed' },
  awaiting_approval: { label: 'Awaiting approval', var: '--status-rework' },
  approved: { label: 'Approved', var: '--status-passed' },
  rejected: { label: 'Rejected', var: '--status-failed' },
};

function Pill({ label, cssVar }: { label: string; cssVar: string }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold text-white"
      style={{ backgroundColor: `var(${cssVar})` }}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-white/80" aria-hidden="true" />
      {label}
    </span>
  );
}

export function MonitoringStatusBadge({ status }: { status: MonitoringStatus }) {
  const meta = monitoringStatusMeta[status];
  return <Pill label={meta.label} cssVar={meta.var} />;
}

export function JobStatusBadge({ status }: { status: JobStatus }) {
  const meta = jobStatusMeta[status];
  return <Pill label={meta.label} cssVar={meta.var} />;
}

export function StepStatusBadge({ status }: { status: StepStatus }) {
  const meta = stepStatusMeta[status];
  return <Pill label={meta.label} cssVar={meta.var} />;
}

const environmentMeta: Record<PipelineEnvironment, { label: string; var: string; title: string }> = {
  staging: {
    label: 'Staging',
    var: '--status-rework',
    title: 'In staging — manual runs only; the enterprise scheduler (ESP) cannot trigger it until promoted.',
  },
  production: {
    label: 'Production',
    var: '--status-passed',
    title: 'Promoted to production (ServiceNow-ticketed) — triggerable by the enterprise scheduler (ESP).',
  },
};

/** Staging/production environment of a pipeline (the promotable "job" definition). */
export function EnvironmentBadge({ environment }: { environment: PipelineEnvironment }) {
  const meta = environmentMeta[environment];
  return (
    <span title={meta.title}>
      <Pill label={meta.label} cssVar={meta.var} />
    </span>
  );
}

// EMR Serverless application ("cluster") lifecycle states, toned like TMT's
// compute panel: green while serving, amber in transition, gray at rest.
const emrAppStateVar: Record<string, string> = {
  STARTED: '--status-passed',
  CREATING: '--status-rework',
  STARTING: '--status-rework',
  STOPPING: '--status-rework',
};

/** EMR Serverless application state (STARTED, STOPPED, …). */
export function EmrAppStateBadge({ state }: { state: string }) {
  return <Pill label={state.toLowerCase()} cssVar={emrAppStateVar[state] ?? '--status-not-started'} />;
}

/** Generic entry point when the status "kind" isn't known statically. */
export function StatusBadge({
  kind,
  status,
}: {
  kind: 'monitoring' | 'job' | 'step';
  status: string;
}) {
  if (kind === 'monitoring') return <MonitoringStatusBadge status={status as MonitoringStatus} />;
  if (kind === 'job') return <JobStatusBadge status={status as JobStatus} />;
  return <StepStatusBadge status={status as StepStatus} />;
}
