from typing import Dict, Optional

from fastapi import APIRouter, Depends, Query

from app.auth.dependencies import require_role
from app.core.pagination import paginate
from app.schemas.common import ApiModel, CurrentUser, PageEnvelope
from app.schemas.monitoring import MonitoringSnapshot
from app.services import monitoring_service

router = APIRouter(prefix="/monitoring", tags=["monitoring"])

READ_ROLES = ("LeadDataScientist", "DataScientist", "Operator")


class MonitoringDashboard(ApiModel):
    counts: Dict[str, int]
    totalModels: int


@router.get("/snapshots", response_model=PageEnvelope[MonitoringSnapshot])
def list_snapshots(
    modelName: Optional[str] = Query(None),
    version: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=200),
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
):
    items = monitoring_service.list_snapshots(current_user, modelName, version)
    return paginate(items, page, pageSize)


@router.get("/models/{model_name}/{version}/trend", response_model=PageEnvelope[MonitoringSnapshot])
def model_trend(
    model_name: str,
    version: str,
    tenant_id: Optional[str] = Query(None, alias="tenantId", description="Required for PlatformAdmin/Operator cross-tenant lookup"),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=200),
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
):
    """Snapshot history for one model version, newest first — the data behind
    a drift/error-rate trend chart."""
    items = monitoring_service.model_trend(current_user, model_name, version, tenant_id)
    return paginate(items, page, pageSize)


@router.get("/dashboard", response_model=MonitoringDashboard)
def dashboard(current_user: CurrentUser = Depends(require_role(*READ_ROLES))):
    return monitoring_service.dashboard(current_user)
