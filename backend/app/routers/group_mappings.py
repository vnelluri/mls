from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from app.auth.dependencies import require_role
from app.core.exceptions import not_found
from app.core.pagination import paginate
from app.repositories import group_mapping_repo
from app.schemas.common import CurrentUser, PageEnvelope
from app.schemas.tenant import GroupMapping, GroupMappingUpsert
from app.services import audit_service

router = APIRouter(prefix="/group-mappings", tags=["group-mappings"])

PLATFORM_PARTITION = "PLATFORM"


@router.post("", response_model=GroupMapping, status_code=201)
def upsert_group_mapping(data: GroupMappingUpsert, current_user: CurrentUser = Depends(require_role())):
    now = datetime.now(timezone.utc).isoformat()
    item = {
        "group_id": data.group_id,
        "role": data.role,
        "tenant_id": data.tenant_id,
        "displayName": data.displayName,
        "updatedAt": now,
        "updatedBy": current_user.user_id,
    }
    group_mapping_repo.put_mapping(item)
    audit_service.write_event(
        PLATFORM_PARTITION, current_user.user_id, current_user.role,
        "group_mapping.upsert", "group_mapping", data.group_id,
        f"Mapped group '{data.displayName}' -> role={data.role} tenant={data.tenant_id}",
    )
    return item


@router.get("", response_model=PageEnvelope[GroupMapping])
def list_group_mappings(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=200),
    current_user: CurrentUser = Depends(require_role()),
):
    items = sorted(group_mapping_repo.list_mappings(), key=lambda m: m.get("displayName", ""))
    return paginate(items, page, pageSize)


@router.get("/{group_id}", response_model=GroupMapping)
def get_group_mapping(group_id: str, current_user: CurrentUser = Depends(require_role())):
    item = group_mapping_repo.get_mapping(group_id)
    if not item:
        raise not_found("GroupMapping", group_id)
    return item


@router.delete("/{group_id}", status_code=204)
def delete_group_mapping(group_id: str, current_user: CurrentUser = Depends(require_role())):
    item = group_mapping_repo.get_mapping(group_id)
    if not item:
        raise not_found("GroupMapping", group_id)
    group_mapping_repo.delete_mapping(group_id)
    audit_service.write_event(
        PLATFORM_PARTITION, current_user.user_id, current_user.role,
        "group_mapping.delete", "group_mapping", group_id, f"Deleted mapping for group '{group_id}'",
    )
    return None
