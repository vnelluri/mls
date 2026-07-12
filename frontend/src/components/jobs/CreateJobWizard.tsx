import { useState } from 'react';
import { createPipeline } from '@/api/pipelinesApi';
import { submitJob } from '@/api/jobsApi';
import type {
  ApprovalConfig,
  DataPipelineConfig,
  DataQualityConfig,
  ExecuteModelConfig,
  Job,
  LoadToSnowflakeConfig,
  PipelineStep,
  StepType,
} from '@/types/platform';
import { Button, Field, InlineAlert, Input, Modal, Textarea } from '@/components/shared/ui';
import { PipelineCanvas, stepsToCanvasSteps } from '@/components/canvas/PipelineCanvas';
import { stepTypeLabels } from '@/components/canvas/StepNode';
import { DataPipelineStepPanel } from '@/components/canvas/panels/DataPipelineStepPanel';
import { ExecuteModelStepPanel } from '@/components/canvas/panels/ExecuteModelStepPanel';
import { DataQualityStepPanel } from '@/components/canvas/panels/DataQualityStepPanel';
import { ApprovalStepPanel } from '@/components/canvas/panels/ApprovalStepPanel';
import { LoadToSnowflakeStepPanel } from '@/components/canvas/panels/LoadToSnowflakeStepPanel';

const WIZARD_STEPS = ['Job Details', 'Pipeline', 'Review'] as const;

const addableStepTypes: StepType[] = [
  'data_pipeline', 'execute_model', 'data_quality_check', 'approval', 'load_to_snowflake',
];

const stepTypeHints: Record<StepType, string> = {
  data_pipeline: 'Snowflake → S3',
  execute_model: 'EMR Serverless',
  data_quality_check: 'DQ + drift checks',
  approval: 'Manual review gate',
  load_to_snowflake: 'S3 → Snowflake',
};

function defaultConfigFor(type: StepType): PipelineStep['config'] {
  switch (type) {
    case 'data_pipeline':
      return {
        sourceType: 'snowflake',
        snowflakeParams: {},
        destinationS3Uri: '',
      } satisfies DataPipelineConfig;
    case 'execute_model':
      // EMR application/role/entrypoint are platform-managed (tenant
      // execution config) — the backend rejects authored values.
      return {
        modelName: '',
        modelVersion: '',
        inputS3Uri: '',
        outputS3Uri: '',
      } satisfies ExecuteModelConfig;
    case 'data_quality_check':
      return { checks: [], inputS3Uri: '' } satisfies DataQualityConfig;
    case 'approval':
      return {} satisfies ApprovalConfig;
    case 'load_to_snowflake':
      // No source field: the platform always loads the run's own
      // execute_model output, never author-chosen.
      return { snowflakeParams: {} } satisfies LoadToSnowflakeConfig;
    default:
      throw new Error(`Unknown step type: ${type satisfies never}`);
  }
}

function newStepId(): string {
  return `step-${Math.random().toString(36).slice(2, 9)}`;
}

function Chevron({ dir }: { dir: 'up' | 'down' }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      aria-hidden="true"
      className={dir === 'up' ? 'rotate-180' : ''}
    >
      <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Keep the steps a linear chain: each step depends on the one before it. */
function rechain(steps: PipelineStep[]): PipelineStep[] {
  return steps.map((s, i) => ({ ...s, dependsOn: i === 0 ? [] : [steps[i - 1].stepId] }));
}

export function CreateJobWizard({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  /** Called with the submitted (staging) job after the wizard finishes. */
  onCreated: (job: Job) => void;
}) {
  const [page, setPage] = useState(0);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [requiresApproval, setRequiresApproval] = useState(false);
  const [steps, setSteps] = useState<PipelineStep[]>([]);
  const [openStepId, setOpenStepId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  // Set once the pipeline is created so a retry after a failed job submit
  // doesn't create a duplicate pipeline.
  const [createdPipelineId, setCreatedPipelineId] = useState<string | null>(null);

  const addStep = (type: StepType) => {
    const step: PipelineStep = { stepId: newStepId(), type, dependsOn: [], config: defaultConfigFor(type) };
    setSteps((prev) => rechain([...prev, step]));
    setOpenStepId(step.stepId);
  };

  const removeStep = (stepId: string) => {
    setSteps((prev) => rechain(prev.filter((s) => s.stepId !== stepId)));
    if (openStepId === stepId) setOpenStepId(null);
  };

  const moveStep = (stepId: string, dir: -1 | 1) => {
    setSteps((prev) => {
      const i = prev.findIndex((s) => s.stepId === stepId);
      if (i < 0 || i + dir < 0 || i + dir >= prev.length) return prev;
      const next = [...prev];
      [next[i], next[i + dir]] = [next[i + dir], next[i]];
      return rechain(next);
    });
  };

  const updateStepConfig = (stepId: string, config: PipelineStep['config']) => {
    setSteps((prev) => prev.map((s) => (s.stepId === stepId ? { ...s, config } : s)));
  };

  // The backend rejects data-quality checks with blank names (the name keys
  // the check's results), so block advancing until every check is named.
  const hasUnnamedDqCheck = steps.some(
    (s) =>
      s.type === 'data_quality_check' &&
      (s.config as DataQualityConfig).checks.some((c) => !c.name.trim()),
  );
  const canAdvance =
    page === 0 ? name.trim().length > 0 : page === 1 ? steps.length > 0 && !hasUnnamedDqCheck : true;

  const handleSubmit = async () => {
    setSubmitting(true);
    setSubmitError(null);
    try {
      let pipelineId = createdPipelineId;
      if (!pipelineId) {
        const pipeline = await createPipeline({ name, description, requiresApproval, steps });
        pipelineId = pipeline.pipelineId;
        setCreatedPipelineId(pipelineId);
      }
      const job = await submitJob({ pipelineId });
      onCreated(job);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : 'Failed to create job.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Create new job" width="max-w-3xl">
      {/* Step indicator — numbered circles with connectors, same as TMT */}
      <div className="mb-6 flex items-center gap-2 overflow-x-auto pb-1">
        {WIZARD_STEPS.map((label, i) => (
          <div key={label} className="flex flex-shrink-0 items-center gap-2">
            <button
              onClick={() => i < page && setPage(i)}
              disabled={i > page}
              className={`flex h-8 w-8 items-center justify-center rounded-full text-xs font-semibold transition ${
                i === page
                  ? 'bg-truist-purple text-white'
                  : i < page
                    ? 'bg-truist-purple/20 text-truist-purple'
                    : 'bg-truist-tint07 text-truist-midGray'
              }`}
            >
              {i + 1}
            </button>
            <span
              className={`text-xs font-medium ${
                i === page ? 'text-truist-charcoal' : 'text-truist-midGray'
              }`}
            >
              {label}
            </span>
            {i < WIZARD_STEPS.length - 1 && <span className="mx-1 h-px w-6 bg-truist-gray06" />}
          </div>
        ))}
      </div>

      {submitError && (
        <div className="mb-4">
          <InlineAlert kind="error">{submitError}</InlineAlert>
        </div>
      )}

      {/* Page 0: Job Details */}
      {page === 0 && (
        <div className="max-w-md">
          <Field label="Job name" required hint="Also names the pipeline this job runs.">
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Daily Fraud Score"
              autoFocus
            />
          </Field>
          <Field label="Description">
            <Textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Describe what this job does"
              rows={2}
            />
          </Field>
          <label className="flex items-center gap-2 text-sm text-truist-charcoal">
            <input
              type="checkbox"
              checked={requiresApproval}
              onChange={(e) => setRequiresApproval(e.target.checked)}
            />
            Requires approval gate before job completion
          </label>
        </div>
      )}

      {/* Page 1: Pipeline builder */}
      {page === 1 && (
        <div>
          <p className="mb-3 text-sm font-semibold text-truist-charcoal">Add step</p>
          <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {addableStepTypes.map((type) => (
              <button
                key={type}
                onClick={() => addStep(type)}
                className="rounded-xl border border-truist-gray06 p-4 text-left transition hover:border-truist-purple/40 hover:bg-truist-purple/5"
              >
                <p className="text-sm font-semibold text-truist-charcoal">+ {stepTypeLabels[type]}</p>
                <p className="mt-1 text-xs text-truist-darkGray">{stepTypeHints[type]}</p>
              </button>
            ))}
          </div>

          {steps.length === 0 ? (
            <div className="rounded-xl border border-dashed border-truist-lightGray py-10 text-center text-sm text-truist-midGray">
              No steps yet — add steps above to build your pipeline.
            </div>
          ) : (
            <ol className="space-y-2">
              {steps.map((step, i) => (
                <li key={step.stepId} className="overflow-hidden rounded-xl border border-truist-gray06">
                  <div className="flex items-center gap-3 bg-truist-gray07 px-3 py-2">
                    <span className="flex flex-col leading-none">
                      <button
                        onClick={() => moveStep(step.stepId, -1)}
                        disabled={i === 0}
                        aria-label="Move step up"
                        className="text-truist-midGray hover:text-truist-charcoal disabled:opacity-25"
                      >
                        <Chevron dir="up" />
                      </button>
                      <button
                        onClick={() => moveStep(step.stepId, 1)}
                        disabled={i === steps.length - 1}
                        aria-label="Move step down"
                        className="text-truist-midGray hover:text-truist-charcoal disabled:opacity-25"
                      >
                        <Chevron dir="down" />
                      </button>
                    </span>
                    <span className="flex h-6 w-6 items-center justify-center rounded-full bg-truist-purple/20 text-xs font-semibold text-truist-purple">
                      {i + 1}
                    </span>
                    <span className="flex-1 text-sm font-medium text-truist-charcoal">
                      {stepTypeLabels[step.type]}
                    </span>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setOpenStepId(openStepId === step.stepId ? null : step.stepId)}
                    >
                      Configure <Chevron dir={openStepId === step.stepId ? 'up' : 'down'} />
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => removeStep(step.stepId)}>
                      Remove
                    </Button>
                  </div>
                  {openStepId === step.stepId && (
                    <div className="border-t border-truist-gray06 p-4">
                      {step.type === 'data_pipeline' && (
                        <DataPipelineStepPanel
                          config={step.config as DataPipelineConfig}
                          onChange={(c) => updateStepConfig(step.stepId, c)}
                        />
                      )}
                      {step.type === 'execute_model' && (
                        <ExecuteModelStepPanel
                          config={step.config as ExecuteModelConfig}
                          onChange={(c) => updateStepConfig(step.stepId, c)}
                        />
                      )}
                      {step.type === 'data_quality_check' && (
                        <DataQualityStepPanel
                          config={step.config as DataQualityConfig}
                          onChange={(c) => updateStepConfig(step.stepId, c)}
                        />
                      )}
                      {step.type === 'approval' && (
                        <ApprovalStepPanel
                          config={step.config as ApprovalConfig}
                          onChange={(c) => updateStepConfig(step.stepId, c)}
                        />
                      )}
                      {step.type === 'load_to_snowflake' && (
                        <LoadToSnowflakeStepPanel
                          config={step.config as LoadToSnowflakeConfig}
                          onChange={(c) => updateStepConfig(step.stepId, c)}
                        />
                      )}
                    </div>
                  )}
                </li>
              ))}
            </ol>
          )}

          {hasUnnamedDqCheck && (
            <div className="mt-3">
              <InlineAlert kind="warning">
                Every data quality check needs a name before you can continue.
              </InlineAlert>
            </div>
          )}
        </div>
      )}

      {/* Page 2: Review */}
      {page === 2 && (
        <div className="space-y-5">
          <h3 className="text-sm font-semibold text-truist-charcoal">Review and submit</h3>
          <dl className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-xs uppercase tracking-wide text-truist-midGray">Job name</dt>
              <dd className="mt-1 text-truist-charcoal">{name}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-truist-midGray">Approval gate</dt>
              <dd className="mt-1 text-truist-charcoal">{requiresApproval ? 'Yes' : 'No'}</dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-xs uppercase tracking-wide text-truist-midGray">
                Pipeline ({steps.length} step{steps.length !== 1 ? 's' : ''})
              </dt>
              <dd className="mt-1 text-truist-charcoal">
                {steps.map((s) => stepTypeLabels[s.type]).join(' → ')}
              </dd>
            </div>
          </dl>

          {steps.length > 0 && (
            <div>
              <p className="mb-2 text-sm font-medium text-truist-charcoal">Pipeline preview</p>
              <PipelineCanvas steps={stepsToCanvasSteps(steps)} />
            </div>
          )}

          <InlineAlert kind="warning">
            This job is created in <strong>Staging</strong> and does not run yet — start it from its job
            page when ready. The enterprise scheduler (ESP) <strong>cannot</strong> trigger it. After
            reviewing a successful run, promote it to Production with a ServiceNow ticket.
          </InlineAlert>
        </div>
      )}

      {/* Footer — Back left, Next/submit right, same as TMT */}
      <div className="mt-5 flex items-center justify-between border-t border-truist-gray06 pt-4">
        <Button variant="secondary" onClick={() => setPage((p) => p - 1)} disabled={page === 0 || submitting}>
          Back
        </Button>
        {page < WIZARD_STEPS.length - 1 ? (
          <Button onClick={() => setPage((p) => p + 1)} disabled={!canAdvance}>
            Next
          </Button>
        ) : (
          <Button onClick={() => void handleSubmit()} disabled={submitting}>
            {submitting ? 'Creating…' : 'Create job'}
          </Button>
        )}
      </div>
    </Modal>
  );
}
