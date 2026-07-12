"""
Landing-page dashboard aggregation -- available to ALL roles.

Reuses the existing role-aware list paths (own-tenant Query for
LeadDataScientist/DataScientist, ALL-GSI Query for PlatformAdmin) and folds
the results into a single summary payload so the dashboard page renders from
one round-trip instead of fanning out per-status list calls.
"""
import re
from typing import List, Optional

from app.config import settings
from app.repositories import audit_repo, tenant_repo
from app.schemas.common import CurrentUser
from app.services import job_service, model_registry_service, pipeline_service
from app.services.emr_execution_service import get_emr_execution_service

PIPELINE_STATUSES = ["draft", "active", "archived"]
JOB_STATUSES = ["pending", "running", "awaiting_approval", "success", "failed", "cancelled"]
STEP_STATUSES = ["idle", "running", "succeeded", "failed", "awaiting_approval", "approved", "rejected"]
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


# Rough sizing for the utilization ESTIMATE (mirrors TMT's compute panel):
# EMR Serverless default workers are 4 vCPU. Real per-application worker
# metrics would need CloudWatch, so the meter is derived from running run
# counts and labeled estimated.
_EST_VCPU_PER_WORKER = 4


def _parse_vcpu(max_cpu) -> Optional[int]:
    """maximumCapacity.cpu is a string like "400 vCPU"."""
    digits = re.search(r"\d+", str(max_cpu or ""))
    return int(digits.group()) if digits else None


def _emr_applications(current_user: CurrentUser, jobs: List[dict]) -> List[dict]:
    """One row per visible tenant's EMR Serverless application ("cluster"):
    application state + capacity limits from the execution service, run
    counts and estimated utilization from the jobs already in hand. Mock mode
    synthesizes one application per tenant (tenants only carry a real
    emrApplicationId in EMR_MODE=real, where tenants without one are
    skipped)."""
    if current_user.sees_all_tenants:
        tenants = [(t["tenant_id"], t.get("execution") or {}) for t in tenant_repo.list_tenants()]
    else:
        record = tenant_repo.get_tenant(current_user.tenant_id) or {}
        tenants = [(current_user.tenant_id, record.get("execution") or {})]

    running_by_tenant: dict = {}
    queued_by_tenant: dict = {}
    for job in jobs:
        for s in job.get("steps", []):
            if s.get("type") != "execute_model":
                continue
            if s.get("status") == "running":
                running_by_tenant[job["tenant_id"]] = running_by_tenant.get(job["tenant_id"], 0) + 1
            # An idle EMR step on a still-active job is queued to run; idle
            # steps on terminal jobs never will be.
            elif s.get("status") == "idle" and job.get("status") in ("pending", "running"):
                queued_by_tenant[job["tenant_id"]] = queued_by_tenant.get(job["tenant_id"], 0) + 1

    # ponytail: one get_application call per tenant per dashboard load; cache
    # if tenant count grows past the low hundreds or EMR throttles.
    svc = get_emr_execution_service()
    apps = []
    for tenant_id, execution in tenants:
        app_id = execution.get("emrApplicationId")
        if not app_id:
            if settings.EMR_MODE == "real":
                continue
            app_id = f"mock-emr-{tenant_id}"
        info = svc.get_application(app_id)
        max_vcpu = info.pop("max_vcpu", None) or _parse_vcpu(info.get("max_cpu"))
        running = running_by_tenant.get(tenant_id, 0)
        allocated = running * _EST_VCPU_PER_WORKER
        apps.append({
            "tenant_id": tenant_id,
            "application_id": app_id,
            **info,
            "running_job_runs": running,
            "queued_job_runs": queued_by_tenant.get(tenant_id, 0),
            "max_vcpu": max_vcpu,
            "allocated_vcpu_estimate": allocated,
            "utilization_pct": min(100, round(allocated / max_vcpu * 100)) if max_vcpu else None,
            "estimated": True,
        })
    return apps


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

    # EMR compute status: execute_model steps run on EMR Serverless; their
    # step status is the platform's mirror of the EMR run state.
    emr_steps = [
        s for job in jobs for s in job.get("steps", []) if s.get("type") == "execute_model"
    ]

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
        "emr": {
            "total": len(emr_steps),
            "by_status": _count_by(emr_steps, "status", STEP_STATUSES),
            "applications": _emr_applications(current_user, jobs),
        },
        "models": {
            "total": len(models),
            "by_stage": _count_by(models, "stage", MODEL_STAGES),
            "by_monitoring_status": _count_by(models, "currentMonitoringStatus", MONITORING_STATUSES),
        },
        "recent_jobs": recent_jobs,
        "recent_audit_events": recent_audit,
    }
