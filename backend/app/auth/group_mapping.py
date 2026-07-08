"""
Resolves Entra group membership -> {role, tenant_id} via the
`mlserv-group-mappings` DynamoDB table.

This is intentionally resolved fresh on EVERY request in prod mode -- role and
tenancy are NEVER cached and NEVER trusted directly from a raw JWT claim,
since group membership (and therefore authorization) can change at any time
and we want that reflected immediately.
"""
import logging
from typing import List, Optional, Tuple

from app.config import settings
from app.db.client import get_table

logger = logging.getLogger(__name__)

# Highest-privilege-first; used to pick a single role when a user belongs to
# multiple mapped groups (e.g. accidentally added to two groups).
# Operator is the cross-tenant job-operations role (view/stop/retry jobs in
# every tenant, no other writes) — broader visibility than the tenant-scoped
# roles, but no pipeline/model/approval authority, so it sits directly below
# PlatformAdmin.
ROLE_PRIORITY = ["PlatformAdmin", "Operator", "LeadDataScientist", "DataScientist"]


def resolve_role_and_tenant(group_ids: List[str]) -> Optional[Tuple[str, Optional[str], str]]:
    """
    Given a list of Entra group object IDs from a validated JWT, look each one
    up in mlserv-group-mappings and return the highest-privilege match as
    (role, tenant_id, display_name). Returns None if no group is mapped.
    """
    table = get_table(settings.TABLE_GROUP_MAPPINGS)
    matches = []
    for group_id in group_ids:
        try:
            resp = table.get_item(Key={"group_id": group_id})
        except Exception:
            logger.exception("Failed to resolve group mapping for group_id=%s", group_id)
            continue
        item = resp.get("Item")
        if item:
            matches.append(item)

    if not matches:
        return None

    matches.sort(key=lambda m: ROLE_PRIORITY.index(m["role"]) if m["role"] in ROLE_PRIORITY else 99)
    best = matches[0]
    return best["role"], best.get("tenant_id"), best.get("displayName", "")
