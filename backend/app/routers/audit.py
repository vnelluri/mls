from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.auth.dependencies import require_role
from app.core.pagination import paginate
from app.schemas.audit import AuditEvent
from app.schemas.common import CurrentUser, PageEnvelope
from app.repositories import audit_repo

router = APIRouter(prefix="/audit", tags=["audit"])

READ_ROLES = ("LeadDataScientist", "DataScientist")


@router.get("", response_model=PageEnvelope[AuditEvent])
def list_audit_events(
    action: Optional[str] = Query(None, description="Filter by exact action, e.g. 'model.promote'"),
    entityType: Optional[str] = Query(None),
    date: Optional[str] = Query(None, description="YYYY-MM-DD; PlatformAdmin cross-tenant view pages by date (default today)"),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=200),
    current_user: CurrentUser = Depends(require_role(*READ_ROLES)),
):
    if current_user.role == "PlatformAdmin":
        items = audit_repo.list_events_all_tenants(date)
    else:
        items = audit_repo.list_events_for_tenant(current_user.tenant_id)

    if action is not None:
        items = [e for e in items if e.get("action") == action]
    if entityType is not None:
        items = [e for e in items if e.get("entityType") == entityType]
    return paginate(items, page, pageSize)
