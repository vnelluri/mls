from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.auth.dependencies import require_job_ops_role, require_role, require_tenant_scoped_role
from app.core.pagination import paginate
from app.schemas.common import CurrentUser, PageEnvelope
from app.schemas.job import Job, JobCreate
from app.services import job_service

router = APIRouter(prefix="/jobs", tags=["jobs"])

# Operator: cross-tenant job monitoring — reads everywhere plus stop/retry/
# resume (via require_job_ops_role below). Submission and approvals stay with
# LeadDataScientist only.
READ_ROLES = ("LeadDataScientist", "DataScientist", "Operator")
WRITE_ROLES = ("LeadDataScientist",)
# Stop/retry/resume: both scientist roles may operate their tenant's jobs.
# job_service adds the environment gate — production runs are Operator-only.
OPS_ROLES = ("LeadDataScientist", "DataScientist")


@router.post("", response_model=Job, status_code=201)
def submit_job(data: JobCreate, current_user: CurrentUser = Depends(require_tenant_scoped_role(*WRITE_ROLES))):
    return job_service.create_job(current_user, data)


@router.get("", response_model=PageEnvelope[Job])
def list_jobs(
    status: Optional[str] = Query(None, description="Filter by job status, e.g. 'running'"),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=200),
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
):
    items = job_service.list_jobs(current_user)
    if status is not None:
        items = [j for j in items if j.get("status") == status]
    return paginate(items, page, pageSize)


@router.get("/{job_id}", response_model=Job)
def get_job(
    job_id: str,
    tenant_id: Optional[str] = Query(None, alias="tenantId", description="Required for PlatformAdmin cross-tenant lookup"),
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
):
    return job_service.get_job_and_refresh(current_user, job_id, tenant_id)


@router.post("/{job_id}/start", response_model=Job)
def start_job(
    job_id: str,
    tenant_id: Optional[str] = Query(None, alias="tenantId", description="Required for Operator cross-tenant start"),
    current_user: CurrentUser = Depends(require_job_ops_role(*OPS_ROLES)),
):
    return job_service.start_job(current_user, job_id, tenant_id)


@router.post("/{job_id}/stop", response_model=Job)
def stop_job(
    job_id: str,
    tenant_id: Optional[str] = Query(None, alias="tenantId", description="Required for Operator cross-tenant stop"),
    current_user: CurrentUser = Depends(require_job_ops_role(*OPS_ROLES)),
):
    return job_service.stop_job(current_user, job_id, tenant_id)


@router.post("/{job_id}/retry", response_model=Job)
def retry_job(
    job_id: str,
    tenant_id: Optional[str] = Query(None, alias="tenantId", description="Required for Operator cross-tenant retry"),
    current_user: CurrentUser = Depends(require_job_ops_role(*OPS_ROLES)),
):
    return job_service.retry_job(current_user, job_id, tenant_id)


@router.post("/{job_id}/resume", response_model=Job)
def resume_job(
    job_id: str,
    tenant_id: Optional[str] = Query(None, alias="tenantId", description="Required for Operator cross-tenant resume"),
    current_user: CurrentUser = Depends(require_job_ops_role(*OPS_ROLES)),
):
    return job_service.resume_job(current_user, job_id, tenant_id)


@router.post("/{job_id}/steps/{step_id}/override", response_model=Job)
def override_step(job_id: str, step_id: str, current_user: CurrentUser = Depends(require_tenant_scoped_role(*WRITE_ROLES))):
    return job_service.override_failed_step(current_user, job_id, step_id)


@router.post("/{job_id}/steps/{step_id}/approve", response_model=Job)
def approve_step(job_id: str, step_id: str, current_user: CurrentUser = Depends(require_tenant_scoped_role(*WRITE_ROLES))):
    return job_service.approve_step(current_user, job_id, step_id)


@router.post("/{job_id}/steps/{step_id}/reject", response_model=Job)
def reject_step(job_id: str, step_id: str, current_user: CurrentUser = Depends(require_tenant_scoped_role(*WRITE_ROLES))):
    return job_service.reject_step(current_user, job_id, step_id)
