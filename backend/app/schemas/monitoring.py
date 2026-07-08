from typing import Dict, Literal, Optional

from pydantic import field_validator

from app.schemas.common import ApiModel

DerivedStatus = Literal["Passed", "Failed", "Rework", "InReview", "NotStarted"]


class DataQualityCheckDetail(ApiModel):
    passed: bool
    observedValue: float


class Thresholds(ApiModel):
    psiWarn: float
    psiFail: float
    errorRateWarn: float
    errorRateFail: float


class MonitoringSnapshot(ApiModel):
    tenant_id: str
    model_name: str
    version: str
    job_id: str
    run_id: str
    recordedAt: str
    requestCount: int
    avgLatencyMs: float
    errorRate: float
    driftMetrics: Dict[str, float]
    maxPsi: float
    dataQualityPassed: bool
    dataQualityDetails: Dict[str, DataQualityCheckDetail]
    derivedStatus: DerivedStatus
    thresholdsUsed: Thresholds

    # Snapshots stored before the string-version change have integer versions.
    @field_validator("version", mode="before")
    @classmethod
    def _coerce_version(cls, v):
        return str(v) if isinstance(v, (int, float)) else v
