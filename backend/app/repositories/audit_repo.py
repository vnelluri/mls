"""Pure DynamoDB CRUD for `mlserv-audit`."""
from typing import List, Optional

from boto3.dynamodb.conditions import Key

from app.config import settings
from app.db.client import get_table


def _table():
    return get_table(settings.TABLE_AUDIT)


def put_event(item: dict) -> dict:
    _table().put_item(Item=item)
    return item


def list_events_for_tenant(tenant_id: str) -> List[dict]:
    items = []
    resp = _table().query(KeyConditionExpression=Key("tenant_id").eq(tenant_id), ScanIndexForward=False)
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = _table().query(
            KeyConditionExpression=Key("tenant_id").eq(tenant_id),
            ScanIndexForward=False,
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        items.extend(resp.get("Items", []))
    return items


def list_events_all_tenants(event_date: Optional[str] = None) -> List[dict]:
    """Cross-tenant admin listing. GSI3 (all-index) is partitioned by
    eventDate (YYYY-MM-DD) rather than a single constant "ALL" value (unlike
    the other tables' all-index) since audit volume is much higher and a
    single constant partition would become a hot key; callers page by date,
    defaulting to today if none given."""
    from datetime import datetime, timezone

    date_key = event_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    items = []
    resp = _table().query(
        IndexName="all-index",
        KeyConditionExpression=Key("event_date").eq(date_key),
        ScanIndexForward=False,
    )
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = _table().query(
            IndexName="all-index",
            KeyConditionExpression=Key("event_date").eq(date_key),
            ScanIndexForward=False,
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        items.extend(resp.get("Items", []))
    return items


def list_events_by_actor(actor: str) -> List[dict]:
    items = []
    resp = _table().query(
        IndexName="actor-index",
        KeyConditionExpression=Key("actor").eq(actor),
        ScanIndexForward=False,
    )
    items.extend(resp.get("Items", []))
    return items


def list_events_by_entity(entity_type: str, entity_id: str) -> List[dict]:
    pk = f"{entity_type}#{entity_id}"
    items = []
    resp = _table().query(
        IndexName="entity-index",
        KeyConditionExpression=Key("entity_pk").eq(pk),
        ScanIndexForward=False,
    )
    items.extend(resp.get("Items", []))
    return items
