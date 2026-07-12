from typing import Optional

from fastapi import APIRouter, Depends, Query, UploadFile

from app.auth.dependencies import require_role, require_tenant_scoped_role
from app.core.pagination import paginate
from app.schemas.common import CurrentUser, PageEnvelope
from app.schemas.model_registry import (
    ArtifactUploadResponse,
    Model,
    ModelPromoteRequest,
    ModelRegisterRequest,
)
from app.services import artifact_service, model_registry_service

router = APIRouter(prefix="/models", tags=["models"])

READ_ROLES = ("LeadDataScientist", "DataScientist")
WRITE_ROLES = ("LeadDataScientist",)


@router.post("", response_model=Model, status_code=201)
def register_model(
    data: ModelRegisterRequest, current_user: CurrentUser = Depends(require_tenant_scoped_role(*WRITE_ROLES))
):
    return model_registry_service.register_model(current_user, data)


@router.post("/artifacts", response_model=ArtifactUploadResponse, status_code=201)
def upload_artifact(
    file: UploadFile,
    current_user: CurrentUser = Depends(require_tenant_scoped_role(*WRITE_ROLES)),
):
    """Upload a model artifact (multipart file) into the tenant's prefix of
    the shared artifacts bucket; register the model with the returned URI."""
    return artifact_service.upload_artifact(current_user, file.filename or "", file.file)


@router.get("", response_model=PageEnvelope[Model])
def list_models(
    monitoringStatus: Optional[str] = Query(None, description="Filter by currentMonitoringStatus, e.g. 'Failed'"),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=200),
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
):
    items = model_registry_service.list_models(current_user)
    if monitoringStatus is not None:
        items = [m for m in items if m.get("currentMonitoringStatus") == monitoringStatus]
    return paginate(items, page, pageSize)


@router.get("/{model_name}/{version}", response_model=Model)
def get_model(
    model_name: str,
    version: str,
    tenant_id: Optional[str] = Query(None, alias="tenantId", description="Required for PlatformAdmin cross-tenant lookup"),
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
):
    return model_registry_service.get_model_scoped(current_user, model_name, version, tenant_id)


@router.patch("/{model_name}/{version}/promote", response_model=Model)
def promote_model(
    model_name: str,
    version: str,
    data: ModelPromoteRequest,
    current_user: CurrentUser = Depends(require_tenant_scoped_role(*WRITE_ROLES)),
):
    return model_registry_service.promote_model(current_user, model_name, version, data)
