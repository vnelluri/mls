from typing import Optional

from fastapi import APIRouter, Depends, Header, Query

from app.auth.dependencies import require_job_ops_role, require_role, require_tenant_scoped_role
from app.core.pagination import paginate
from app.schemas.common import CurrentUser, PageEnvelope
from app.schemas.job import Job, TriggerRequest
from app.schemas.pipeline import Pipeline, PipelineCreate, PipelinePromoteRequest, PipelineUpdate
from app.services import job_service, pipeline_service

router = APIRouter(prefix="/pipelines", tags=["pipelines"])

READ_ROLES = ("LeadDataScientist", "DataScientist")
WRITE_ROLES = ("LeadDataScientist",)


@router.post("", response_model=Pipeline, status_code=201)
def create_pipeline(data: PipelineCreate, current_user: CurrentUser = Depends(require_tenant_scoped_role(*WRITE_ROLES))):
    return pipeline_service.create_pipeline(current_user, data)


@router.get("", response_model=PageEnvelope[Pipeline])
def list_pipelines(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=200),
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
):
    items = pipeline_service.list_pipelines(current_user)
    return paginate(items, page, pageSize)


@router.get("/{pipeline_id}", response_model=Pipeline)
def get_pipeline(
    pipeline_id: str,
    tenant_id: Optional[str] = Query(None, alias="tenantId", description="Required for PlatformAdmin cross-tenant lookup"),
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
):
    return pipeline_service.get_pipeline_scoped(current_user, pipeline_id, tenant_id)


@router.patch("/{pipeline_id}", response_model=Pipeline)
def update_pipeline(
    pipeline_id: str, data: PipelineUpdate, current_user: CurrentUser = Depends(require_tenant_scoped_role(*WRITE_ROLES))
):
    return pipeline_service.update_pipeline(current_user, pipeline_id, data)


@router.patch("/{pipeline_id}/archive", response_model=Pipeline)
def archive_pipeline(pipeline_id: str, current_user: CurrentUser = Depends(require_tenant_scoped_role(*WRITE_ROLES))):
    return pipeline_service.archive_pipeline(current_user, pipeline_id)


@router.post("/{pipeline_id}/promote", response_model=Pipeline)
def promote_pipeline(
    pipeline_id: str,
    data: PipelinePromoteRequest,
    current_user: CurrentUser = Depends(require_tenant_scoped_role(*WRITE_ROLES)),
):
    """Promote a reviewed staging pipeline to production.

    Requires a ServiceNow change ticket (recorded on the pipeline and in the
    audit log) and at least one successful staging run. Only production
    pipelines can be triggered by the external scheduler (ESP)."""
    return pipeline_service.promote_pipeline(current_user, pipeline_id, data.service_now_ticket)


@router.post("/{pipeline_id}/trigger", response_model=Job, status_code=201)
def trigger_pipeline(
    pipeline_id: str,
    data: Optional[TriggerRequest] = None,
    tenant_id: Optional[str] = Query(None, alias="tenantId", description="Required for Operator (the external scheduler's role) — names the tenant to run in"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key", description="Scheduler retries with the same key return the original job instead of double-submitting"),
    current_user: CurrentUser = Depends(require_job_ops_role(*WRITE_ROLES)),
):
    """Machine-callable pipeline launch for the external scheduler (ESP).

    The scheduler polls ``GET /jobs/{jobId}?tenantId=...`` until the returned
    status is terminal (success / failed / cancelled)."""
    return job_service.trigger_pipeline(
        current_user,
        pipeline_id,
        tenant_id,
        external_run_id=data.external_run_id if data else None,
        idempotency_key=idempotency_key,
    )
