"""Business logic for Tenant CRUD (PlatformAdmin console only)."""
import re
from datetime import datetime, timezone
from typing import List

from app.core.exceptions import conflict, not_found
from app.repositories import tenant_repo
from app.schemas.common import CurrentUser
from app.schemas.tenant import TenantCreate, TenantExecutionConfig
from app.services import audit_service

PLATFORM_PARTITION = "PLATFORM"


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "tenant"


def create_tenant(current_user: CurrentUser, data: TenantCreate) -> dict:
    tenant_id = data.tenant_id or _slugify(data.name)
    if tenant_repo.get_tenant(tenant_id):
        raise conflict(f"Tenant '{tenant_id}' already exists")

    now = datetime.now(timezone.utc).isoformat()
    item = {
        "tenant_id": tenant_id,
        "name": data.name,
        "status": "active",
        "execution": data.execution.model_dump() if data.execution else None,
        "createdAt": now,
        "createdBy": current_user.user_id,
    }
    tenant_repo.put_tenant(item)

    audit_service.write_event(
        PLATFORM_PARTITION, current_user.user_id, current_user.role,
        "tenant.create", "tenant", tenant_id, f"Created tenant '{data.name}' ({tenant_id})",
    )
    return item


def list_tenants(current_user: CurrentUser) -> List[dict]:
    return sorted(tenant_repo.list_tenants(), key=lambda t: t.get("createdAt", ""))


def get_tenant(tenant_id: str) -> dict:
    item = tenant_repo.get_tenant(tenant_id)
    if not item:
        raise not_found("Tenant", tenant_id)
    return item


def set_execution_config(
    current_user: CurrentUser, tenant_id: str, execution: TenantExecutionConfig
) -> dict:
    """Replace the tenant's platform-managed execution resources (EMR
    application/role, scoring entrypoint, data prefix). PlatformAdmin only —
    these bound what the tenant's pipelines can run as and where they can
    read/write, so changes are audited like any other platform action."""
    item = tenant_repo.get_tenant(tenant_id)
    if not item:
        raise not_found("Tenant", tenant_id)
    item["execution"] = execution.model_dump()
    tenant_repo.put_tenant(item)

    audit_service.write_event(
        PLATFORM_PARTITION, current_user.user_id, current_user.role,
        "tenant.execution_config", "tenant", tenant_id,
        f"Updated execution config for tenant '{item['name']}' ({tenant_id})",
    )
    return item


def suspend_tenant(current_user: CurrentUser, tenant_id: str) -> dict:
    item = tenant_repo.get_tenant(tenant_id)
    if not item:
        raise not_found("Tenant", tenant_id)
    updated = tenant_repo.update_tenant_status(tenant_id, "suspended")

    audit_service.write_event(
        PLATFORM_PARTITION, current_user.user_id, current_user.role,
        "tenant.suspend", "tenant", tenant_id, f"Suspended tenant '{item['name']}' ({tenant_id})",
    )
    return updated


def reactivate_tenant(current_user: CurrentUser, tenant_id: str) -> dict:
    item = tenant_repo.get_tenant(tenant_id)
    if not item:
        raise not_found("Tenant", tenant_id)
    updated = tenant_repo.update_tenant_status(tenant_id, "active")

    audit_service.write_event(
        PLATFORM_PARTITION, current_user.user_id, current_user.role,
        "tenant.reactivate", "tenant", tenant_id, f"Reactivated tenant '{item['name']}' ({tenant_id})",
    )
    return updated
