"""Pure DynamoDB CRUD for `mlserv-tenants`. No business logic here."""
from typing import List, Optional

from app.config import settings
from app.db.client import get_table


def _table():
    return get_table(settings.TABLE_TENANTS)


def put_tenant(item: dict) -> dict:
    _table().put_item(Item=item)
    return item


def get_tenant(tenant_id: str) -> Optional[dict]:
    resp = _table().get_item(Key={"tenant_id": tenant_id})
    return resp.get("Item")


def list_tenants() -> List[dict]:
    """Tenants table PK *is* the tenant identity -- there's no cross-tenant
    fan-out concern here (unlike pipelines/jobs/models), so a table Scan is
    acceptable at this table's expected scale (tens to low hundreds of rows)."""
    items = []
    resp = _table().scan()
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = _table().scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
        items.extend(resp.get("Items", []))
    return items


def update_tenant_status(tenant_id: str, status: str) -> dict:
    resp = _table().update_item(
        Key={"tenant_id": tenant_id},
        UpdateExpression="SET #s = :s",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": status},
        ReturnValues="ALL_NEW",
    )
    return resp["Attributes"]
