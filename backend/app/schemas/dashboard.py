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


class EmrApplication(ApiModel):
    """One tenant's EMR Serverless application ("cluster"): state, capacity
    limits, run counts, and utilization for the dashboard's capacity meter.
    Utilization is always an ESTIMATE derived from run counts (real worker
    metrics would need CloudWatch), which the frontend labels as such."""

    tenant_id: str
    application_id: str
    state: str
    max_cpu: str
    max_memory: str
    running_job_runs: int
    queued_job_runs: int
    max_vcpu: Optional[int] = None
    allocated_vcpu_estimate: int
    utilization_pct: Optional[int] = None


class EmrStats(ApiModel):
    """execute_model (EMR) steps across the caller's visible jobs, bucketed by
    step status — the platform's mirror of the EMR Serverless run state."""

    total: int
    by_status: Dict[str, int]
    applications: List[EmrApplication]


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
    emr: EmrStats
    models: ModelStats
    recent_jobs: List[Job]
    recent_audit_events: List[AuditEvent]
