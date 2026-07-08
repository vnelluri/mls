"""
Resolves Entra group membership -> {role, tenant_id}.

Primary path (name convention): the org's `tms-*` security groups are synced
from on-prem AD, so the token's `groups` claim carries their sAMAccountName
group NAMES (the app registration's optional-claims config must emit
sAMAccountName for the groups claim). Role and tenancy are parsed straight
from the name — no table entry, no bootstrap seeding:

    tms-platform-admin               -> PlatformAdmin (tenantless)
    tms-platform-operator            -> Operator      (tenantless)
    tms-<tenant>-leaddatascientist   -> LeadDataScientist @ <tenant>
    tms-<tenant>-datascientist       -> DataScientist     @ <tenant>

The role is matched as the LONGEST known suffix, so tenant slugs containing
hyphens ("acme-capital") and hyphenated role spellings
("lead-data-scientist") never collide. Names may arrive domain-qualified
("CORP\\tms-...") — the qualifier is stripped. Matching is case-insensitive
and the parsed tenant slug (lowercased) must equal the platform's tenant_id
exactly: that equality is the tenant-onboarding contract. The prefix is
configurable via GROUP_NAME_PREFIX (default "tms").

Fallback (mapping table): claim entries that don't parse — group object IDs
(GUIDs), non-convention groups — are looked up in `mlserv-group-mappings` as
before. The table remains REQUIRED for service principals: app-only tokens
(e.g. the external scheduler, ESP) carry no groups claim at all, so those are
mapped by client ID through the table (see dependencies.get_current_user).

Resolution still happens fresh on EVERY request in prod mode and is never
cached in-process. For convention groups, freshness is that of the token's
groups claim — a membership change applies at the next token refresh rather
than instantly (accepted trade-off of claim-based resolution).
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

# Known role suffixes of convention group names: (suffix, role, platform_scoped).
# platform_scoped roles are tenantless and only valid as the exact name
# "<prefix>-platform-<suffix>"; the others require a non-empty tenant slug.
# Sorted longest-first below so "...-lead-data-scientist" can never match the
# plain "data-scientist" suffix with "lead" swallowed into the tenant slug.
_ROLE_SUFFIXES = sorted(
    [
        ("admin", "PlatformAdmin", True),
        ("operator", "Operator", True),
        ("leaddatascientist", "LeadDataScientist", False),
        ("lead-data-scientist", "LeadDataScientist", False),
        ("datascientist", "DataScientist", False),
        ("data-scientist", "DataScientist", False),
    ],
    key=lambda t: len(t[0]),
    reverse=True,
)


def parse_group_name(raw: str) -> Optional[Tuple[str, Optional[str]]]:
    """Parse a convention-named group into (role, tenant_id | None).

    Returns None for anything that isn't a valid convention name (wrong
    prefix, unknown role suffix, tenant-scoped role on "platform", platform
    role on a tenant, empty tenant slug) — those fall through to the mapping
    table.
    """
    # Synced groups can arrive domain-qualified ("CORP\\tms-...").
    name = raw.rsplit("\\", 1)[-1].strip().lower()
    prefix = settings.GROUP_NAME_PREFIX.lower() + "-"
    if not name.startswith(prefix):
        return None
    rest = name[len(prefix):]

    for suffix, role, platform_scoped in _ROLE_SUFFIXES:
        if platform_scoped:
            if rest == f"platform-{suffix}":
                return role, None
            continue
        if rest.endswith(f"-{suffix}"):
            tenant = rest[: -(len(suffix) + 1)]
            # "platform" is reserved: tenant-scoped roles can't live there,
            # and an empty slug ("tms--datascientist") is malformed.
            if tenant and tenant != "platform":
                return role, tenant
            return None
    return None


def resolve_role_and_tenant(group_ids: List[str]) -> Optional[Tuple[str, Optional[str], str]]:
    """
    Given the entries of a validated JWT's groups claim (names for AD-synced
    groups, object IDs otherwise) — or a service principal's client ID —
    resolve each one and return the highest-privilege match as
    (role, tenant_id, display_name). Returns None if nothing resolves.

    Convention-named entries resolve by parsing alone (no DynamoDB read);
    everything else is looked up in mlserv-group-mappings.
    """
    matches = []
    table = None
    for group_id in group_ids:
        parsed = parse_group_name(group_id)
        if parsed:
            role, tenant_id = parsed
            matches.append({"role": role, "tenant_id": tenant_id, "displayName": group_id})
            continue
        try:
            if table is None:
                table = get_table(settings.TABLE_GROUP_MAPPINGS)
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
