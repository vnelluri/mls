"""Convention-based group-name resolution (tms-platform-<role> /
tms-<tenant>-<role>) and its merge with the mapping-table fallback."""
import pytest

from app.auth.group_mapping import parse_group_name, resolve_role_and_tenant
from app.config import settings
from app.db.client import get_table


# ---- parse_group_name: pure parsing, no DynamoDB ---------------------------

@pytest.mark.parametrize(
    "name,expected",
    [
        # Platform-scoped (tenantless) roles: exact names only.
        ("tms-platform-admin", ("PlatformAdmin", None)),
        ("tms-platform-operator", ("Operator", None)),
        # Tenant-scoped roles, including hyphenated tenant slugs.
        ("tms-acme-capital-leaddatascientist", ("LeadDataScientist", "acme-capital")),
        ("tms-acme-capital-datascientist", ("DataScientist", "acme-capital")),
        ("tms-blue-harbor-bank-datascientist", ("DataScientist", "blue-harbor-bank")),
        # Hyphenated role spellings must not bleed into the tenant slug:
        # longest-suffix matching keeps "lead" out of the tenant.
        ("tms-acme-lead-data-scientist", ("LeadDataScientist", "acme")),
        ("tms-acme-data-scientist", ("DataScientist", "acme")),
        # Case-insensitive; domain qualifier stripped.
        ("TMS-Platform-Admin", ("PlatformAdmin", None)),
        ("CORP\\tms-acme-capital-datascientist", ("DataScientist", "acme-capital")),
    ],
)
def test_parse_valid_names(name, expected):
    assert parse_group_name(name) == expected


@pytest.mark.parametrize(
    "name",
    [
        "acme-capital-datascientist",  # wrong prefix
        "tms2-acme-datascientist",  # prefix must match exactly
        "tms-acme-capital-approver",  # unknown role suffix
        "tms-platform-datascientist",  # tenant-scoped role on reserved "platform"
        "tms-platform-leaddatascientist",
        "tms-acme-capital-admin",  # platform role on a tenant
        "tms-acme-capital-operator",
        "tms--datascientist",  # empty tenant slug
        "tms-platform",  # no role segment
        "tms-datascientist",  # role with no tenant ("datascientist" IS the slug-less rest)
        "a7f3c9d1-1234-5678-9abc-def012345678",  # a GUID -> table fallback
        "",
    ],
)
def test_parse_rejects_non_convention_names(name):
    assert parse_group_name(name) is None


def test_prefix_is_configurable(monkeypatch):
    monkeypatch.setattr(settings, "GROUP_NAME_PREFIX", "mlp")
    assert parse_group_name("mlp-acme-datascientist") == ("DataScientist", "acme")
    assert parse_group_name("tms-acme-datascientist") is None


# ---- resolve_role_and_tenant: priority + table merge ------------------------

def test_convention_only_resolution_needs_no_table():
    # No aws fixture: if resolution touched DynamoDB this would error.
    role, tenant, display = resolve_role_and_tenant(
        ["tms-acme-capital-datascientist", "tms-acme-capital-leaddatascientist"]
    )
    assert (role, tenant) == ("LeadDataScientist", "acme-capital")  # highest privilege wins
    assert display == "tms-acme-capital-leaddatascientist"


def test_platform_role_outranks_tenant_role():
    role, tenant, _ = resolve_role_and_tenant(
        ["tms-acme-capital-leaddatascientist", "tms-platform-operator"]
    )
    assert (role, tenant) == ("Operator", None)


def test_unresolvable_entries_return_none(aws):
    assert resolve_role_and_tenant([]) is None
    assert resolve_role_and_tenant(["unmapped-guid", "not-a-tms-group"]) is None


def test_table_fallback_merges_with_convention(aws):
    # A legacy/exception mapping (e.g. an ESP client ID) still resolves and
    # competes on role priority with convention-named groups.
    get_table(settings.TABLE_GROUP_MAPPINGS).put_item(
        Item={"group_id": "esp-client-id-1", "role": "Operator", "displayName": "ESP scheduler"}
    )
    role, tenant, display = resolve_role_and_tenant(
        ["tms-acme-capital-datascientist", "esp-client-id-1"]
    )
    assert (role, tenant) == ("Operator", None)
    assert display == "ESP scheduler"
