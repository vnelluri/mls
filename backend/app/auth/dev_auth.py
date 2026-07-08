"""
AUTH_MODE=dev synthetic CurrentUser builder.

Strictly gated on AUTH_MODE == "dev" by the caller (dependencies.py) -- this
module itself has no gating logic, it simply builds a CurrentUser from the
DEV_USER_* env vars every time it's called.
"""
from app.config import settings
from app.schemas.common import CurrentUser


def build_dev_user() -> CurrentUser:
    tenant_id = settings.DEV_USER_TENANT_ID
    # PlatformAdmin and Operator never have a tenant, regardless of what's
    # configured — both are platform-wide roles.
    if settings.DEV_USER_ROLE in ("PlatformAdmin", "Operator"):
        tenant_id = None
    return CurrentUser(
        user_id=settings.DEV_USER_ID,
        email=settings.DEV_USER_EMAIL,
        name=settings.DEV_USER_NAME,
        role=settings.DEV_USER_ROLE,
        tenant_id=tenant_id,
    )
