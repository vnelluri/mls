from typing import Dict, List, Literal, Optional

from app.schemas.common import ApiModel

JobStatus = Literal["pending", "running", "awaiting_approval", "success", "failed", "cancelled"]
StepRunStatus = Literal[
    "idle", "running", "succeeded", "failed", "awaiting_approval", "approved", "rejected"
]


class JobStepState(ApiModel):
    step_id: str
    type: str
    status: StepRunStatus = "idle"
    startedAt: Optional[str] = None
    completedAt: Optional[str] = None
    emrJobRunId: Optional[str] = None
    emrStateDetail: Optional[str] = None
    # data_pipeline steps: the Snowflake query id of the async COPY INTO
    # unload — polled to completion, cancellable, survives restarts (the
    # data-pipeline analogue of emrJobRunId).
    snowflakeQueryId: Optional[str] = None
    errorMessage: Optional[str] = None
    output: Optional[dict] = None
    # NOTE: `config` is not in the original field list from the platform spec,
    # but is snapshotted here from the pipeline step at submit/retry time so
    # that step execution is correct and reproducible even if the parent
    # Pipeline is edited (new version) after this job was submitted. It is
    # additive and does not change any of the specified field names.
    config: Optional[dict] = None


class RunHistoryEntry(ApiModel):
    run_id: str
    startedAt: str
    endedAt: Optional[str] = None
    finalStatus: str
    # Snapshot of the run's step states (outputs, errors, EMR run ids) taken
    # when the run was retried/resumed — the per-run evidence trail. Only the
    # most recent archived runs keep this detail (older entries drop it to
    # bound item size); entries written before the field existed lack it.
    steps: Optional[List[JobStepState]] = None


class JobCreate(ApiModel):
    pipeline_id: str


class TriggerRequest(ApiModel):
    """Body of POST /pipelines/{id}/trigger — the external scheduler's own
    run identifier, recorded on the job for cross-system lineage."""

    external_run_id: Optional[str] = None


class Job(ApiModel):
    tenant_id: str
    job_id: str
    pipeline_id: str
    pipeline_version: int
    run_id: str
    status: JobStatus
    steps: List[JobStepState]
    runHistory: List[RunHistoryEntry] = []
    submittedBy: str
    submittedAt: str
    # Set only on scheduler-triggered jobs (POST /pipelines/{id}/trigger):
    # how the job was launched and the external scheduler's run id.
    triggeredVia: Optional[str] = None
    externalRunId: Optional[str] = None
    # Snapshot of the pipeline's environment when this run started (also
    # re-snapshotted on restart/resume). The ESP trigger only ever creates
    # production runs.
    runEnvironment: Optional[Literal["staging", "production"]] = None
    # The pipeline's CURRENT environment, joined at read time (never stored):
    # flips to "production" the moment the pipeline is promoted, even for
    # jobs whose runs happened in staging.
    pipelineEnvironment: Optional[Literal["staging", "production"]] = None
    # The pipeline's display name, joined at read time (never stored) — the
    # UI shows this instead of the raw pipeline id.
    pipelineName: Optional[str] = None


class ApproveRejectResponse(ApiModel):
    job_id: str
    step_id: str
    status: str
    job_status: JobStatus
