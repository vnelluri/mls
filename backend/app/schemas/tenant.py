from typing import Literal, Optional

from pydantic import field_validator

from app.schemas.common import ApiModel

TenantStatus = Literal["active", "suspended"]


class TenantExecutionConfig(ApiModel):
    """Platform-managed execution resources for one tenant, set by the
    PlatformAdmin. Pipeline authors never supply these: the EMR application,
    the job execution role, and the scoring entrypoint are resolved from here
    when an execute_model step starts (EMR_MODE=real), and every S3 URI in a
    tenant's pipelines must live under dataS3Prefix when it is set. This is
    what keeps one tenant's Spark code and data physically inside that
    tenant's resources."""

    emrApplicationId: Optional[str] = None
    emrExecutionRoleArn: Optional[str] = None
    # Per-tenant override of the platform-wide EMR_ENTRYPOINT_S3_URI.
    entryPointS3Uri: Optional[str] = None
    # e.g. "s3://mlserv-data/acme-capital/" — pipeline URIs must start with it.
    dataS3Prefix: Optional[str] = None

    @field_validator("dataS3Prefix", "entryPointS3Uri")
    @classmethod
    def _s3_uri_shape(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.startswith("s3://"):
            raise ValueError("must be an s3:// URI")
        return v


class TenantCreate(ApiModel):
    tenant_id: Optional[str] = None  # auto-slugified from name if not provided
    name: str
    execution: Optional[TenantExecutionConfig] = None


class Tenant(ApiModel):
    tenant_id: str
    name: str
    status: TenantStatus
    # Optional because tenants created before the field existed lack it.
    execution: Optional[TenantExecutionConfig] = None
    createdAt: str
    createdBy: str


# Operator is included so the ESP scheduler's service principal (mapped by
# client ID — app-only tokens carry no groups claim) can be registered.
MappableRole = Literal["PlatformAdmin", "Operator", "LeadDataScientist", "DataScientist"]


class GroupMappingUpsert(ApiModel):
    group_id: str
    role: MappableRole
    tenant_id: Optional[str] = None
    displayName: str


class GroupMapping(ApiModel):
    group_id: str
    role: MappableRole
    tenant_id: Optional[str] = None
    displayName: str
    updatedAt: str
    updatedBy: str
