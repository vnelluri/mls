from fastapi import APIRouter, Depends

from app.auth.dependencies import require_role
from app.schemas.common import CurrentUser
from app.schemas.dashboard import DashboardSummary
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# Available to every role: tenant-scoped roles see their own tenant's numbers,
# PlatformAdmin and Operator see cross-tenant aggregates (require_role adds
# admin implicitly; Operator is listed explicitly).
READ_ROLES = ("LeadDataScientist", "DataScientist", "Operator")


@router.get("/summary", response_model=DashboardSummary)
def get_dashboard_summary(current_user: CurrentUser = Depends(require_role(*READ_ROLES))):
    return dashboard_service.get_summary(current_user)
