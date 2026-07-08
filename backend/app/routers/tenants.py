from fastapi import APIRouter, Depends, Query

from app.auth.dependencies import require_role
from app.core.pagination import paginate
from app.schemas.common import CurrentUser, PageEnvelope
from app.schemas.tenant import Tenant, TenantCreate, TenantExecutionConfig
from app.services import tenant_service

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.post("", response_model=Tenant, status_code=201)
def create_tenant(data: TenantCreate, current_user: CurrentUser = Depends(require_role())):
    return tenant_service.create_tenant(current_user, data)


@router.get("", response_model=PageEnvelope[Tenant])
def list_tenants(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=200),
    current_user: CurrentUser = Depends(require_role()),
):
    items = tenant_service.list_tenants(current_user)
    return paginate(items, page, pageSize)


@router.get("/{tenant_id}", response_model=Tenant)
def get_tenant(tenant_id: str, current_user: CurrentUser = Depends(require_role())):
    return tenant_service.get_tenant(tenant_id)


@router.put("/{tenant_id}/execution", response_model=Tenant)
def set_execution_config(
    tenant_id: str,
    execution: TenantExecutionConfig,
    current_user: CurrentUser = Depends(require_role()),
):
    return tenant_service.set_execution_config(current_user, tenant_id, execution)


@router.patch("/{tenant_id}/suspend", response_model=Tenant)
def suspend_tenant(tenant_id: str, current_user: CurrentUser = Depends(require_role())):
    return tenant_service.suspend_tenant(current_user, tenant_id)


@router.patch("/{tenant_id}/reactivate", response_model=Tenant)
def reactivate_tenant(tenant_id: str, current_user: CurrentUser = Depends(require_role())):
    return tenant_service.reactivate_tenant(current_user, tenant_id)
