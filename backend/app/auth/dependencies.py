"""
FastAPI auth dependencies.

Two authorization dependencies matter most here:

  * require_role(*roles):
        allowed = set(roles) | {"PlatformAdmin"}   (PlatformAdmin always implicitly allowed)
        Use for admin-console-only endpoints and ALL read/list/detail GET endpoints.

  * require_tenant_scoped_role(*roles):
        Does NOT implicitly add PlatformAdmin, and 403s if current_user.tenant_id is None.
        Use for EVERY tenant-scoped create/mutate action. This deliberately prevents
        PlatformAdmin (whose tenant_id is always null) from ever attempting a
        tenant-scoped write -- they have no tenant to write into.
"""
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth import entra
from app.auth.dev_auth import build_dev_user
from app.auth.group_mapping import resolve_role_and_tenant
from app.config import settings
from app.repositories import tenant_repo
from app.schemas.common import CurrentUser

_bearer_scheme = HTTPBearer(auto_error=False)


def _reject_if_tenant_suspended(user: CurrentUser) -> CurrentUser:
    """Tenant suspension is enforced at the identity boundary: users mapped
    into a suspended tenant lose all platform access until reactivation.
    (Tenantless roles -- PlatformAdmin, Operator -- are unaffected; a missing
    tenant record is treated as not-suspended so partially-seeded dev
    environments keep working.) Resolved fresh per request, same as the
    role/tenant mapping itself."""
    if user.tenant_id is None:
        return user
    tenant = tenant_repo.get_tenant(user.tenant_id)
    if tenant and tenant.get("status") == "suspended":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tenant '{user.tenant_id}' is suspended — access is disabled until it is reactivated",
        )
    return user


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> CurrentUser:
    if settings.AUTH_MODE == "dev":
        return _reject_if_tenant_suspended(build_dev_user())

    # --- prod path: validate JWT, resolve role/tenant fresh from Entra groups ---
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    claims = entra.validate_token(credentials.credentials)
    group_ids = entra.extract_group_ids(claims)

    resolved = resolve_role_and_tenant(group_ids)
    if resolved is None:
        # Client-credentials (app-only) tokens carry no groups claim. Service
        # principals — e.g. the external scheduler (ESP) that calls
        # POST /pipelines/{id}/trigger — are instead mapped by their client
        # ID: create a group mapping whose group_id is the app registration's
        # client ID ("appid" in v1 tokens, "azp" in v2), typically with
        # role=Operator.
        app_id = claims.get("appid") or claims.get("azp")
        if app_id:
            resolved = resolve_role_and_tenant([app_id])
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No mlserv role is mapped for your Entra group membership",
        )
    role, tenant_id, _display_name = resolved

    return _reject_if_tenant_suspended(
        CurrentUser(
            user_id=claims.get("oid") or claims.get("sub", "unknown"),
            email=claims.get("preferred_username") or claims.get("email", "unknown"),
            name=claims.get("name", "unknown"),
            role=role,
            tenant_id=tenant_id,
        )
    )


def require_role(*roles: str):
    """Admin-implicit role gate: PlatformAdmin is always allowed in addition
    to whatever roles are explicitly listed. Use for all GET/list/detail
    endpoints and admin-console-only CRUD (tenants, group mappings)."""

    allowed = set(roles) | {"PlatformAdmin"}

    def _dependency(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current_user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_user.role}' is not permitted to perform this action",
            )
        return current_user

    return _dependency


def require_tenant_scoped_role(*roles: str):
    """Tenant-scoped mutation gate: NO implicit PlatformAdmin bypass, and
    403s if the caller has no tenant_id. Use for every tenant-scoped
    create/mutate action (pipelines, jobs, approvals, model register/promote)."""

    allowed = set(roles)

    def _dependency(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current_user.role not in allowed or current_user.tenant_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This action requires a tenant-scoped role with an assigned tenant",
            )
        return current_user

    return _dependency


def require_job_ops_role(*tenant_roles: str):
    """Job-operations gate: the listed tenant-scoped roles (which must have a
    tenant, exactly like require_tenant_scoped_role) OR the cross-tenant
    Operator role (which, like PlatformAdmin, never has a tenant — the target
    tenant comes from an explicit request parameter instead).

    Deliberately does NOT implicitly allow PlatformAdmin: the platform's rule
    that PlatformAdmin never mutates tenant-scoped resources stands. Operator
    is the cross-tenant *operations* actor — stop/retry only, no approvals,
    no pipeline/model writes."""

    tenant_allowed = set(tenant_roles)

    def _dependency(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current_user.role == "Operator":
            return current_user
        if current_user.role in tenant_allowed and current_user.tenant_id is not None:
            return current_user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires a tenant-scoped job role or the Operator role",
        )

    return _dependency
