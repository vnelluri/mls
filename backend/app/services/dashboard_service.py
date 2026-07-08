"""
Landing-page dashboard aggregation -- available to ALL roles.

Reuses the existing role-aware list paths (own-tenant Query for
LeadDataScientist/DataScientist, ALL-GSI Query for PlatformAdmin) and folds
the results into a single summary payload so the dashboard page renders from
one round-trip instead of fanning out per-status list calls.
"""
from typing import List

from app.repositories import audit_repo, tenant_repo
from app.schemas.common import CurrentUser
from app.services import job_service, model_registry_service, pipeline_service

PIPELINE_STATUSES = ["draft", "active", "archived"]
JOB_STATUSES = ["pending", "running", "awaiting_approval", "success", "failed", "cancelled"]
MODEL_STAGES = ["None", "Staging", "Production", "Archived"]
MONITORING_STATUSES = ["Passed", "Failed", "Rework", "InReview", "NotStarted"]

RECENT_LIMIT = 5


def _count_by(items: List[dict], key: str, buckets: List[str]) -> dict:
    counts = {b: 0 for b in buckets}
    for item in items:
        value = item.get(key)
        if value in counts:
            counts[value] += 1
        elif value is not None:
            counts[str(value)] = counts.get(str(value), 0) + 1
    return counts


def get_summary(current_user: CurrentUser) -> dict:
    pipelines = pipeline_service.list_pipelines(current_user)
    jobs = job_service.list_jobs(current_user)
    models = model_registry_service.list_models(current_user)

    if current_user.sees_all_tenants:
        tenant_count = len(tenant_repo.list_tenants())
        audit_events = audit_repo.list_events_all_tenants(None)
    else:
        tenant_count = None
        audit_events = audit_repo.list_events_for_tenant(current_user.tenant_id)

    recent_jobs = sorted(jobs, key=lambda j: j.get("submittedAt", ""), reverse=True)[:RECENT_LIMIT]
    recent_audit = sorted(audit_events, key=lambda e: e.get("timestamp", ""), reverse=True)[:RECENT_LIMIT]

    return {
        "role": current_user.role,
        "tenant_id": current_user.tenant_id,
        "tenant_count": tenant_count,
        "pipelines": {
            "total": len(pipelines),
            "by_status": _count_by(pipelines, "status", PIPELINE_STATUSES),
        },
        "jobs": {
            "total": len(jobs),
            "by_status": _count_by(jobs, "status", JOB_STATUSES),
        },
        "models": {
            "total": len(models),
            "by_stage": _count_by(models, "stage", MODEL_STAGES),
            "by_monitoring_status": _count_by(models, "currentMonitoringStatus", MONITORING_STATUSES),
        },
        "recent_jobs": recent_jobs,
        "recent_audit_events": recent_audit,
    }
