import re
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import Field, field_validator, model_validator

from app.schemas.common import ApiModel

StepType = Literal[
    "data_pipeline", "execute_model", "data_quality_check", "approval", "load_to_snowflake"
]
PipelineStatus = Literal["draft", "active", "archived"]
# Deployment environment gate: every pipeline is born in "staging" (manual,
# reviewable runs only) and must be explicitly promoted to "production" —
# with a ServiceNow change ticket for audit — before the external scheduler
# (ESP) is allowed to trigger it.
PipelineEnvironment = Literal["staging", "production"]


# ---- Step config shapes (discriminated union on `type`) --------------------

# Unquoted-style Snowflake identifiers only (letters, digits, _, $; must not
# start with a digit) — this is the early, authoring-time copy of the same
# pattern data_pipeline_service.build_unload_sql enforces again at execution
# time (the authoritative SQL-injection guard); the two must stay identical.
_SNOWFLAKE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
# Keys snowflakeParams must carry to build a platform-generated COPY INTO
# statement — shared by DataPipelineConfig (unload, when no scriptS3Uri) and
# LoadToSnowflakeConfig (load, always).
_SNOWFLAKE_COPY_KEYS = ("database", "schema", "table", "warehouse")


def _check_snowflake_copy_params(params: Dict[str, Any]) -> None:
    missing = [k for k in _SNOWFLAKE_COPY_KEYS if not str(params.get(k) or "").strip()]
    if missing:
        raise ValueError(
            f"snowflakeParams must include {missing} (they build the platform's COPY INTO statement)"
        )
    invalid = [k for k in _SNOWFLAKE_COPY_KEYS if not _SNOWFLAKE_IDENTIFIER_RE.match(str(params[k]))]
    if invalid:
        raise ValueError(
            f"snowflakeParams{invalid} must be valid Snowflake identifiers "
            "(letters, digits, _ and $ only, must not start with a digit)"
        )


class DataPipelineConfig(ApiModel):
    sourceType: Literal["snowflake"] = "snowflake"
    # Every Snowflake-specific parameter as one JSON object, e.g.
    # {"database": "ANALYTICS_DB", "schema": "RISK", "table": "CUSTOMER_FEATURES",
    #  "warehouse": "COMPUTE_WH"}. With no scriptS3Uri, database/schema/table/
    # warehouse are REQUIRED (validated below) and drive the platform's own
    # COPY INTO unload; extra keys are accepted and simply unused. With
    # scriptS3Uri set, this object is opaque to the platform — handed to the
    # script verbatim as a JSON string (job_service.
    # _resolve_data_pipeline_script_config) — its shape is entirely up to
    # the script.
    snowflakeParams: Dict[str, Any] = Field(default_factory=dict)
    destinationS3Uri: str
    # Optional: an S3 script (Spark, e.g. via Snowpark for Python) that
    # REPLACES the platform's built-in COPY INTO unload — submitted to the
    # tenant's EMR Serverless application as the job's entryPoint. Unlike
    # execute_model's EMR fields, this is author-supplied: the script *is*
    # the pipeline author's own code, so nothing about which script runs is
    # platform-managed — only which EMR application/role it runs under
    # (resolved from the tenant's execution config, same as execute_model).
    scriptS3Uri: Optional[str] = None

    @field_validator("scriptS3Uri")
    @classmethod
    def _script_uri_shape(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.startswith("s3://"):
            raise ValueError("scriptS3Uri must be an s3:// URI")
        return v

    @model_validator(mode="after")
    def _validate_snowflake_params(self) -> "DataPipelineConfig":
        if self.scriptS3Uri:
            return self  # opaque to the platform; the script owns its own validation
        _check_snowflake_copy_params(self.snowflakeParams)
        return self


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


class LoadToSnowflakeConfig(ApiModel):
    """Loads a run's scored output back into Snowflake — the reverse of
    DataPipelineConfig's unload. Always the pipeline's LAST step (see
    pipeline_service.CANONICAL_STEP_ORDER): it only ever runs once a run has
    cleared the quality gate and, if the pipeline has one, the approval gate
    — a run that failed either never reaches this step, so nothing
    unreviewed is ever published to Snowflake.

    Unlike DataPipelineConfig, there is no `scriptS3Uri` escape hatch and no
    author-supplied source URI: the source is always the run's own
    execute_model output (resolved by job_service at step start, the same
    resultsS3Prefix the data_quality_check step inspects) — never
    configurable, so a load can never be pointed at stale or foreign data.
    Each run APPENDS its rows to the destination table (COPY INTO, matched
    by column name); nothing is ever overwritten."""

    snowflakeParams: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_snowflake_params(self) -> "LoadToSnowflakeConfig":
        _check_snowflake_copy_params(self.snowflakeParams)
        return self


class PipelineStep(ApiModel):
    step_id: str
    type: StepType
    config: Union[
        DataPipelineConfig, ExecuteModelConfig, DataQualityCheckConfig, ApprovalConfig,
        LoadToSnowflakeConfig,
    ]
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
    "load_to_snowflake": LoadToSnowflakeConfig,
}

ALLOWED_STEP_TYPES = set(CONFIG_MODEL_BY_TYPE.keys())
