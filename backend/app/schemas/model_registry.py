import re
from typing import Dict, List, Literal, Optional

from pydantic import field_validator, model_validator

from app.schemas.common import ApiModel

ModelStage = Literal["None", "Staging", "Production", "Archived"]
MonitoringStatus = Literal["Passed", "Failed", "Rework", "InReview", "NotStarted"]

# Versions are free-form strings (e.g. "1", "2.1.0") but become part of the
# DynamoDB sort key ("name#version") and URL paths, so '#', '/', whitespace
# and other separators are excluded.
VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class FeatureBaseline(ApiModel):
    """One feature's training-time distribution, captured when the model was
    trained: `bins` are the n+1 bucket edges, `proportions` the n bucket
    masses (must sum to ~1). Scoring runs bin current data into the same
    edges and compute PSI against these proportions."""

    bins: List[float]
    proportions: List[float]

    @model_validator(mode="after")
    def _validate_shape(self) -> "FeatureBaseline":
        if len(self.bins) < 3:
            raise ValueError("baseline needs at least 2 buckets (3 bin edges)")
        if len(self.proportions) != len(self.bins) - 1:
            raise ValueError("proportions must have exactly len(bins) - 1 entries")
        if any(p < 0 for p in self.proportions):
            raise ValueError("proportions must be non-negative")
        total = sum(self.proportions)
        if not 0.99 <= total <= 1.01:
            raise ValueError(f"proportions must sum to ~1.0 (got {total:.4f})")
        return self


class ModelRegisterRequest(ApiModel):
    model_name: str
    # Enterprise model inventory identifier (e.g. an MRM record id).
    model_id: str
    version: str
    framework: str
    artifactS3Uri: str
    description: Optional[str] = None
    driftThresholdOverride: Optional[float] = None
    errorRateThresholdOverride: Optional[float] = None
    # Per-feature training-time distributions. When present, scoring runs
    # compute real PSI against these instead of synthesizing drift numbers.
    driftBaseline: Optional[Dict[str, FeatureBaseline]] = None

    @field_validator("model_id")
    @classmethod
    def _model_id_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("modelId must not be blank")
        return v.strip()

    @field_validator("version")
    @classmethod
    def _version_shape(cls, v: str) -> str:
        v = v.strip()
        if not VERSION_RE.match(v):
            raise ValueError(
                "version must be non-empty and contain only letters, digits, '.', '_' or '-'"
            )
        return v


class ModelPromoteRequest(ApiModel):
    targetStage: ModelStage


class Model(ApiModel):
    tenant_id: str
    model_name: str
    # Optional because models registered before the field existed lack it.
    model_id: Optional[str] = None
    version: str
    stage: ModelStage
    framework: str
    artifactS3Uri: str
    description: Optional[str] = None
    driftThresholdOverride: Optional[float] = None
    errorRateThresholdOverride: Optional[float] = None
    driftBaseline: Optional[Dict[str, FeatureBaseline]] = None
    currentMonitoringStatus: MonitoringStatus
    lastSnapshotAt: Optional[str] = None
    registeredBy: str
    registeredAt: str
    promotedBy: Optional[str] = None
    promotedAt: Optional[str] = None

    # Models stored before the string-version change have integer versions.
    @field_validator("version", mode="before")
    @classmethod
    def _coerce_version(cls, v):
        return str(v) if isinstance(v, (int, float)) else v
