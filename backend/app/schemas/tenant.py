from typing import Literal, Optional

from app.schemas.common import ApiModel

TenantStatus = Literal["active", "suspended"]


class TenantCreate(ApiModel):
    tenant_id: Optional[str] = None  # auto-slugified from name if not provided
    name: str


class Tenant(ApiModel):
    tenant_id: str
    name: str
    status: TenantStatus
    createdAt: str
    createdBy: str


class GroupMappingUpsert(ApiModel):
    group_id: str
    role: Literal["PlatformAdmin", "LeadDataScientist", "DataScientist"]
    tenant_id: Optional[str] = None
    displayName: str


class GroupMapping(ApiModel):
    group_id: str
    role: Literal["PlatformAdmin", "LeadDataScientist", "DataScientist"]
    tenant_id: Optional[str] = None
    displayName: str
    updatedAt: str
    updatedBy: str
