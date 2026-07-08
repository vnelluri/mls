"""Shared schema base + response envelopes used across all endpoints."""
from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

T = TypeVar("T")


class ApiModel(BaseModel):
    """Base for every request/response schema.

    The cross-repo API contract is camelCase on the wire (tenantId, jobId,
    modelName, stepId, runId, ...) -- that is what the frontend's TypeScript
    types are built against. Internally (services, repositories, DynamoDB
    storage) everything stays snake_case; `to_camel` translates at the API
    boundary only, and `populate_by_name=True` lets internal code keep
    constructing/validating models with the snake_case field names (and
    accepts snake_case request bodies too, e.g. from curl scripts).
    `protected_namespaces=()` frees the `model_*` field names (model_name)
    from Pydantic's reserved-prefix warning.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        protected_namespaces=(),
    )


class PageEnvelope(ApiModel, Generic[T]):
    """Every list endpoint returns exactly this shape -- never a bare array."""

    items: List[T]
    total: int
    page: int
    pageSize: int


class CurrentUser(ApiModel):
    user_id: str
    email: str
    name: str
    role: str  # PlatformAdmin | Operator | LeadDataScientist | DataScientist
    tenant_id: Optional[str] = None

    @property
    def sees_all_tenants(self) -> bool:
        """PlatformAdmin and Operator span all tenants (tenant_id is None)."""
        return self.role in ("PlatformAdmin", "Operator")
