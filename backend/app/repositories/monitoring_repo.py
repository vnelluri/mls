"""Pure DynamoDB CRUD for `mlserv-monitoring-snapshots`.

No write endpoint is ever exposed via the API for this table -- snapshots are
only created internally by job_service when a data_quality_check step
completes. This repo simply persists/reads what job_service builds.

The sort key is deterministic per (model, version, job, run) -- exactly one
snapshot can ever exist for a run. Racing writers (per-GET refresh vs the
background loop in another task) collide on the conditional put and the
loser adopts the stored snapshot instead of double-recording. Time ordering
for trends comes from the `recordedAt` attribute (model-trend-index /
all-index range key), not from the sk.
"""
from typing import List, Optional

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from app.config import settings
from app.db.client import get_table, serialize_item, transact_write

ALL_PARTITION = "ALL"


def _sk(model_name: str, version, job_id: str, run_id: str) -> str:
    return f"{model_name}#{version}#{job_id}#{run_id}"


def _table():
    return get_table(settings.TABLE_MONITORING_SNAPSHOTS)


def put_snapshot_once(item: dict) -> dict:
    """Idempotent snapshot write: persists the snapshot unless one already
    exists for this (model, version, job, run), in which case the existing
    row is returned and the new one discarded -- callers always proceed with
    the snapshot that actually won."""
    item = dict(item)
    item["sk"] = _sk(item["model_name"], item["version"], item["job_id"], item["run_id"])
    try:
        _table().put_item(Item=item, ConditionExpression=Attr("sk").not_exists())
        return item
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
    return _get_existing(item)


def _get_existing(item: dict) -> dict:
    resp = _table().get_item(Key={"tenant_id": item["tenant_id"], "sk": item["sk"]})
    return resp.get("Item") or item


def record_snapshot_with_model_status(item: dict, update_model: bool) -> dict:
    """Snapshot put + the model's denormalized currentMonitoringStatus/
    lastSnapshotAt in ONE TransactWriteItems, so a crash can never leave the
    snapshot recorded but the model stale (or vice versa). Cross-table by
    design -- this is the snapshot's own consistency boundary.

    Idempotent like put_snapshot_once: if a racing writer already recorded
    this run's snapshot, the whole transaction cancels on the Put condition
    and the existing row is returned (that writer's transaction already
    updated the model)."""
    item = dict(item)
    item["sk"] = _sk(item["model_name"], item["version"], item["job_id"], item["run_id"])

    if not update_model:
        return put_snapshot_once(item)

    actions = [
        {
            "Put": {
                "TableName": settings.TABLE_MONITORING_SNAPSHOTS,
                "Item": serialize_item(item),
                "ConditionExpression": "attribute_not_exists(sk)",
            }
        },
        {
            "Update": {
                "TableName": settings.TABLE_MODELS,
                "Key": serialize_item(
                    {"tenant_id": item["tenant_id"], "sk": f"{item['model_name']}#{item['version']}"}
                ),
                "UpdateExpression": "SET #cms = :status, lastSnapshotAt = :at",
                "ConditionExpression": "attribute_exists(sk)",
                "ExpressionAttributeNames": {"#cms": "currentMonitoringStatus"},
                "ExpressionAttributeValues": serialize_item(
                    {":status": item["derivedStatus"], ":at": item["recordedAt"]}
                ),
            }
        },
    ]
    try:
        transact_write(actions)
        return item
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "TransactionCanceledException":
            raise
        reasons = exc.response.get("CancellationReasons", [])
        put_reason = reasons[0].get("Code") if reasons else None
        if put_reason == "ConditionalCheckFailed":
            # Duplicate run snapshot: the writer that won also updated the model.
            return _get_existing(item)
        # The model row condition failed (model removed mid-run?) -- record
        # the snapshot alone rather than losing monitoring evidence.
        return put_snapshot_once(item)


def list_snapshots_for_tenant(tenant_id: str) -> List[dict]:
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


def list_snapshots_all_tenants() -> List[dict]:
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


def list_trend_for_model(tenant_id: str, model_name: str, version: str) -> List[dict]:
    pk = f"{tenant_id}#{model_name}#{version}"
    items = []
    resp = _table().query(
        IndexName="model-trend-index",
        KeyConditionExpression=Key("model_trend_pk").eq(pk),
        ScanIndexForward=False,
    )
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = _table().query(
            IndexName="model-trend-index",
            KeyConditionExpression=Key("model_trend_pk").eq(pk),
            ScanIndexForward=False,
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        items.extend(resp.get("Items", []))
    return items
