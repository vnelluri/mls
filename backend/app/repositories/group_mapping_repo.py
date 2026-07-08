"""Pure DynamoDB CRUD for `mlserv-group-mappings`."""
from typing import List, Optional

from app.config import settings
from app.db.client import get_table


def _table():
    return get_table(settings.TABLE_GROUP_MAPPINGS)


def put_mapping(item: dict) -> dict:
    _table().put_item(Item=item)
    return item


def get_mapping(group_id: str) -> Optional[dict]:
    resp = _table().get_item(Key={"group_id": group_id})
    return resp.get("Item")


def delete_mapping(group_id: str) -> None:
    _table().delete_item(Key={"group_id": group_id})


def list_mappings() -> List[dict]:
    items = []
    resp = _table().scan()
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = _table().scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
        items.extend(resp.get("Items", []))
    return items
