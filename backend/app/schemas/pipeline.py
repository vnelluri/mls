from typing import Dict, List, Literal, Optional, Union

from pydantic import Field, field_validator

from app.schemas.common import ApiModel

StepType = Literal["data_pipeline", "execute_model", "data_quality_check", "approval"]
PipelineStatus = Literal["draft", "active", "archived"]
# Deployment environment gate: every pipeline is born in "staging" (manual,
# reviewable runs only) and must be explicitly promoted to "production" —
# with a ServiceNow change ticket for audit — before the external scheduler
# (ESP) is allowed to trigger it.
PipelineEnvironment = Literal["staging", "production"]


# ---- Step config shapes (discriminated union on `type`) --------------------

class DataPipelineConfig(ApiModel):
    sourceType: Literal["snowflake"] = "snowflake"
    snowflakeDatabase: str
    snowflakeSchema: str
    snowflakeTable: str
    snowflakeWarehouse: str
    destinationS3Uri: str


class ExecuteModelConfig(ApiModel):
    modelName: str
    modelVersion: str
    # Platform-managed (resolved from the tenant's execution config /
    # EMR_ENTRYPOINT_S3_URI when the step starts). Optional only so pipelines
    # stored before the change still parse — pipeline_service rejects
    # user-supplied values on create/update: letting authors pick the EMR
    # application or execution role would be privilege escalation.
    emrApplicationId: Optional[str] = None
    executionRoleArn: Optional[str] = None
    entryPointS3Uri: Optional[str] = None
    inputS3Uri: str
    outputS3Uri: str
    sparkSubmitParameters: Optional[Dict] = None

    # Pipelines stored before the string-version change carry integer
    # versions; without coercion they would fall out of the config Union.
    @field_validator("modelVersion", mode="before")
    @classmethod
    def _coerce_model_version(cls, v):
        return str(v) if isinstance(v, (int, float)) else v


class DataQualityCheckItem(ApiModel):
    name: str
    type: Literal["null_rate", "row_count_delta", "schema_match"]
    threshold: float


class DataQualityCheckConfig(ApiModel):
    checks: List[DataQualityCheckItem]
    inputS3Uri: str
    # Real DQ engine only: the scoring-output column holding the model's
    # prediction. Its null fraction is the run's errorRate (a row the model
    # failed to score is an error). Unset -> errorRate is reported as 0.
    predictionColumn: Optional[str] = None


class ApprovalConfig(ApiModel):
    approverNote: Optional[str] = None


class PipelineStep(ApiModel):
    step_id: str
    type: StepType
    config: Union[DataPipelineConfig, ExecuteModelConfig, DataQualityCheckConfig, ApprovalConfig]
    dependsOn: List[str] = Field(default_factory=list)


class PipelineStepIn(ApiModel):
    """Input shape for step creation -- config validated by `type` in the service layer."""

    step_id: Optional[str] = None
    type: StepType
    config: dict
    dependsOn: List[str] = Field(default_factory=list)


class PipelineCreate(ApiModel):
    name: str
    description: Optional[str] = None
    requiresApproval: bool = False
    steps: List[PipelineStepIn]


class PipelineUpdate(ApiModel):
    name: Optional[str] = None
    description: Optional[str] = None
    requiresApproval: Optional[bool] = None
    status: Optional[PipelineStatus] = None
    steps: Optional[List[PipelineStepIn]] = None


class PipelinePromoteRequest(ApiModel):
    """Body of POST /pipelines/{id}/promote — the ServiceNow change ticket
    that authorizes the promotion, recorded on the pipeline and in the audit
    log."""

    service_now_ticket: str


class Pipeline(ApiModel):
    tenant_id: str
    pipeline_id: str
    name: str
    description: Optional[str] = None
    version: int
    status: PipelineStatus
    requiresApproval: bool
    # Defaults to "staging" so pipelines created before this field existed
    # also stay ESP-untriggerable until explicitly promoted.
    environment: PipelineEnvironment = "staging"
    promotedBy: Optional[str] = None
    promotedAt: Optional[str] = None
    serviceNowTicket: Optional[str] = None
    # Stamped by job_service whenever one of this pipeline's jobs persists a
    # `success` run — promotion eligibility reads this instead of scanning
    # job history. Absent on pipelines that predate the stamp.
    lastSuccessfulRunAt: Optional[str] = None
    steps: List[PipelineStep]
    createdBy: str
    createdAt: str
    updatedBy: str
    updatedAt: str


CONFIG_MODEL_BY_TYPE = {
    "data_pipeline": DataPipelineConfig,
    "execute_model": ExecuteModelConfig,
    "data_quality_check": DataQualityCheckConfig,
    "approval": ApprovalConfig,
}

ALLOWED_STEP_TYPES = set(CONFIG_MODEL_BY_TYPE.keys())
