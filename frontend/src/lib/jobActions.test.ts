import { describe, expect, it } from 'vitest';

import { getJobActions } from './jobActions';
import type { Job, JobStepState } from '@/types/platform';

const step = (status: JobStepState['status']): JobStepState => ({
  stepId: 's1',
  type: 'data_pipeline',
  status,
});

function job(overrides: Partial<Job> = {}): Job {
  return {
    tenantId: 'acme',
    jobId: 'job-1',
    pipelineId: 'pl-1',
    pipelineVersion: 1,
    runId: 'RUN-0001',
    status: 'pending',
    steps: [],
    runHistory: [],
    submittedBy: 'user',
    submittedAt: '2026-01-01T00:00:00Z',
    runEnvironment: 'staging',
    pipelineEnvironment: 'staging',
    ...overrides,
  };
}

// Role flag bundles mirroring useTenantContext's matrix.
const lead = { canOperateStagingJobs: true, canOperateProductionJobs: false, canOverrideFailedStep: true };
const dataScientist = { canOperateStagingJobs: true, canOperateProductionJobs: false, canOverrideFailedStep: false };
const operator = { canOperateStagingJobs: true, canOperateProductionJobs: true, canOverrideFailedStep: false };
const platformAdmin = { canOperateStagingJobs: false, canOperateProductionJobs: false, canOverrideFailedStep: false };

describe('getJobActions on staging jobs', () => {
  it('pending: scientists can start and stop, nothing else', () => {
    const actions = getJobActions(job(), lead);
    expect(actions.canStart).toBe(true);
    expect(actions.canStop).toBe(true);
    expect(actions.canRestart).toBe(false);
    expect(actions.canResume).toBe(false);
    expect(actions.canOverride).toBe(false);
  });

  it('running: stop only', () => {
    const actions = getJobActions(job({ status: 'running', steps: [step('running')] }), dataScientist);
    expect(actions.canStart).toBe(false);
    expect(actions.canStop).toBe(true);
    expect(actions.canRestart).toBe(false);
  });

  it('success: rerunnable as "Run Again", never resumable', () => {
    const actions = getJobActions(job({ status: 'success', steps: [step('succeeded')] }), lead);
    expect(actions.canRestart).toBe(true);
    expect(actions.restartLabel).toBe('Run Again');
    expect(actions.canResume).toBe(false);
    expect(actions.canStop).toBe(false);
  });

  it('failed with a completed step: Restart and Resume both offered', () => {
    const failed = job({ status: 'failed', steps: [step('succeeded'), step('failed')] });
    const actions = getJobActions(failed, lead);
    expect(actions.restartLabel).toBe('Restart');
    expect(actions.canRestart).toBe(true);
    expect(actions.canResume).toBe(true);
  });

  it('failed with no completed steps: Resume is pointless and hidden', () => {
    const actions = getJobActions(job({ status: 'failed', steps: [step('failed')] }), lead);
    expect(actions.canRestart).toBe(true);
    expect(actions.canResume).toBe(false);
  });

  it('override is Lead-only and requires a failed step on a failed job', () => {
    const failed = job({ status: 'failed', steps: [step('failed')] });
    expect(getJobActions(failed, lead).canOverride).toBe(true);
    expect(getJobActions(failed, dataScientist).canOverride).toBe(false);
    // Failed job whose steps all completed (e.g. rejected elsewhere): no override target.
    const noFailedStep = job({ status: 'failed', steps: [step('succeeded')] });
    expect(getJobActions(noFailedStep, lead).canOverride).toBe(false);
  });

  it('PlatformAdmin gets no operational controls at all', () => {
    const actions = getJobActions(job({ status: 'failed', steps: [step('failed')] }), platformAdmin);
    expect(actions).toMatchObject({
      canStart: false,
      canStop: false,
      canRestart: false,
      canResume: false,
      canOverride: false,
    });
  });
});

describe('getJobActions on production jobs', () => {
  const prodFailed = job({
    status: 'failed',
    steps: [step('failed')],
    pipelineEnvironment: 'production',
  });

  it('scientists lose stop/restart/resume; the Lead keeps only override', () => {
    const actions = getJobActions(prodFailed, lead);
    expect(actions.canStop).toBe(false);
    expect(actions.canRestart).toBe(false);
    expect(actions.canResume).toBe(false);
    expect(actions.canOverride).toBe(true); // the Lead's production lever
    expect(getJobActions(prodFailed, dataScientist).canOverride).toBe(false);
  });

  it('the Operator operates production runs', () => {
    const actions = getJobActions(prodFailed, operator);
    expect(actions.canRestart).toBe(true);
    expect(actions.canOverride).toBe(false);
  });

  it('gates on the pipeline CURRENT environment, falling back to the run snapshot', () => {
    // Pipeline promoted after the run: pipelineEnvironment wins.
    const promoted = job({ status: 'running', runEnvironment: 'staging', pipelineEnvironment: 'production' });
    expect(getJobActions(promoted, lead).canStop).toBe(false);
    // Join unavailable: the run snapshot decides.
    const snapshotOnly = job({ status: 'running', runEnvironment: 'production', pipelineEnvironment: null });
    expect(getJobActions(snapshotOnly, lead).canStop).toBe(false);
    expect(getJobActions(snapshotOnly, operator).canStop).toBe(true);
  });
});
