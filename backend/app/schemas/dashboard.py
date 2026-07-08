from typing import Dict, List, Optional

from app.schemas.audit import AuditEvent
from app.schemas.common import ApiModel
from app.schemas.job import Job


class PipelineStats(ApiModel):
    total: int
    by_status: Dict[str, int]


class JobStats(ApiModel):
    total: int
    by_status: Dict[str, int]


class ModelStats(ApiModel):
    total: int
    by_stage: Dict[str, int]
    by_monitoring_status: Dict[str, int]


class DashboardSummary(ApiModel):
    """One-round-trip landing-page summary, scoped to the caller's role:
    own tenant for LeadDataScientist/DataScientist, cross-tenant (via the
    ALL GSIs) for PlatformAdmin. `tenant_count` is only populated for
    PlatformAdmin (other roles have no visibility into the tenant list)."""

    role: str
    tenant_id: Optional[str] = None
    tenant_count: Optional[int] = None
    pipelines: PipelineStats
    jobs: JobStats
    models: ModelStats
    recent_jobs: List[Job]
    recent_audit_events: List[AuditEvent]
