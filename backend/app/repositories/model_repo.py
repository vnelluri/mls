"""Pure DynamoDB CRUD for `mlserv-models`.

The model item has two independently-updated regions: the registration facts
(immutable after create), the promotion state (`stage`), and the denormalized
monitoring state (`currentMonitoringStatus`/`lastSnapshotAt`). Promotion and
monitoring are written with field-level UpdateExpressions -- never full-item
puts -- so a snapshot recording can never silently revert a concurrent stage
promotion (or vice versa).
"""
from typing import List, Optional

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from app.config import settings
from app.core.exceptions import ConcurrentWriteError
from app.db.client import get_table

ALL_PARTITION = "ALL"


def _table():
    return get_table(settings.TABLE_MODELS)


def _sk(model_name: str, version) -> str:
    return f"{model_name}#{version}"


def _key(tenant_id: str, model_name: str, version) -> dict:
    return {"tenant_id": tenant_id, "sk": _sk(model_name, version)}


def _is_conditional_failure(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"


def create_model(item: dict) -> dict:
    """Register a new (name, version). Conditional on the key not existing:
    two concurrent registrations of the same version can't both win."""
    item = dict(item)
    # The table's range key is always derived from name+version here, so no
    # caller can forget it or drift from the get_model key format.
    item["sk"] = _sk(item["model_name"], item["version"])
    try:
        _table().put_item(Item=item, ConditionExpression=Attr("sk").not_exists())
    except ClientError as exc:
        if _is_conditional_failure(exc):
            raise ConcurrentWriteError(f"Model '{item['sk']}' already exists")
        raise
    return item


def update_stage(
    tenant_id: str,
    model_name: str,
    version,
    target_stage: str,
    expected_stage: str,
    promoted_by: str,
    promoted_at: str,
) -> dict:
    """Atomic stage transition, conditional on the stage still being the one
    the caller validated the transition from. A concurrent promotion (or any
    other stage change) raises ConcurrentWriteError instead of double-firing."""
    try:
        resp = _table().update_item(
            Key=_key(tenant_id, model_name, version),
            UpdateExpression="SET #stage = :target, promotedBy = :by, promotedAt = :at",
            ConditionExpression="attribute_exists(sk) AND #stage = :expected",
            ExpressionAttributeNames={"#stage": "stage"},
            ExpressionAttributeValues={
                ":target": target_stage,
                ":expected": expected_stage,
                ":by": promoted_by,
                ":at": promoted_at,
            },
            ReturnValues="ALL_NEW",
        )
    except ClientError as exc:
        if _is_conditional_failure(exc):
            raise ConcurrentWriteError(
                f"Model '{_sk(model_name, version)}' stage changed concurrently"
            )
        raise
    return resp.get("Attributes", {})


def update_monitoring_status(
    tenant_id: str,
    model_name: str,
    version,
    status: str,
    last_snapshot_at: Optional[str] = None,
    expect_changed: bool = False,
) -> Optional[dict]:
    """Field-level update of the denormalized monitoring state. Returns the
    updated item, or None if the model doesn't exist (or, with
    `expect_changed`, if the status already had that value -- lets callers
    skip duplicate audit rows without a read-modify-write race)."""
    names = {"#cms": "currentMonitoringStatus"}
    update = "SET #cms = :status"
    values = {":status": status}
    condition = "attribute_exists(sk)"
    if expect_changed:
        condition += " AND #cms <> :status"
    if last_snapshot_at is not None:
        update += ", lastSnapshotAt = :snap"
        values[":snap"] = last_snapshot_at
    try:
        resp = _table().update_item(
            Key=_key(tenant_id, model_name, version),
            UpdateExpression=update,
            ConditionExpression=condition,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
        )
    except ClientError as exc:
        if _is_conditional_failure(exc):
            return None
        raise
    return resp.get("Attributes", {})


def get_model(tenant_id: str, model_name: str, version: str) -> Optional[dict]:
    resp = _table().get_item(Key={"tenant_id": tenant_id, "sk": _sk(model_name, version)})
    return resp.get("Item")


def list_models_for_tenant(tenant_id: str) -> List[dict]:
    items = []
    resp = _table().query(KeyConditionExpression=Key("tenant_id").eq(tenant_id))
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = _table().query(
            KeyConditionExpression=Key("tenant_id").eq(tenant_id),
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        items.extend(resp.get("Items", []))
    return items


def list_models_all_tenants() -> List[dict]:
    items = []
    resp = _table().query(
        IndexName="all-index",
        KeyConditionExpression=Key("all_pk").eq(ALL_PARTITION),
        ScanIndexForward=False,
    )
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = _table().query(
            IndexName="all-index",
            KeyConditionExpression=Key("all_pk").eq(ALL_PARTITION),
            ScanIndexForward=False,
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        items.extend(resp.get("Items", []))
    return items


# NOTE: there is deliberately no "list versions by model name across tenants"
# accessor. The old name-index GSI (model_name, version) was keyed without a
# tenant -- any future consumer would have been a cross-tenant data leak --
# and nothing ever queried it, so the index was dropped. Per-tenant version
# listings come from list_models_for_tenant.
