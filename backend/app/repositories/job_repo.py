"""Pure DynamoDB CRUD for `mlserv-jobs`.

Writes are guarded: `create_job` refuses to overwrite an existing job id and
`put_job` uses optimistic locking on `item_version`, so concurrent writers
(the per-GET refresh, the background loop in every API task, and user
actions) can never silently clobber each other -- the loser gets
ConcurrentWriteError and decides what losing means.
"""
from typing import List, Optional

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from app.config import settings
from app.core.exceptions import ConcurrentWriteError
from app.db.client import get_table

ALL_PARTITION = "ALL"


def _table():
    return get_table(settings.TABLE_JOBS)


def _is_conditional_failure(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"


def create_job(item: dict) -> dict:
    """First persist of a new job. Conditional on the job id not existing --
    an id collision (or a concurrent create with the same deterministic
    idempotency-derived id) raises ConcurrentWriteError instead of silently
    overwriting another job."""
    item["item_version"] = 1
    try:
        _table().put_item(Item=item, ConditionExpression=Attr("job_id").not_exists())
    except ClientError as exc:
        if _is_conditional_failure(exc):
            item.pop("item_version", None)
            raise ConcurrentWriteError(f"Job '{item.get('job_id')}' already exists")
        raise
    return item


def put_job(item: dict) -> dict:
    """Optimistically-locked full-item write of an existing job.

    The item must have been read from the table; its `item_version` is the
    expected current value (absent on legacy/seeded rows, which are upgraded
    on their first write). If another writer bumped the version in between,
    raises ConcurrentWriteError and leaves `item` unmodified."""
    expected = item.get("item_version")
    item["item_version"] = (expected or 0) + 1
    condition = (
        Attr("item_version").eq(expected)
        if expected is not None
        else Attr("item_version").not_exists()
    )
    try:
        _table().put_item(Item=item, ConditionExpression=condition)
    except ClientError as exc:
        if _is_conditional_failure(exc):
            if expected is None:
                item.pop("item_version", None)
            else:
                item["item_version"] = expected
            raise ConcurrentWriteError(f"Job '{item.get('job_id')}' was modified concurrently")
        raise
    return item


def get_job(tenant_id: str, job_id: str) -> Optional[dict]:
    resp = _table().get_item(Key={"tenant_id": tenant_id, "job_id": job_id})
    return resp.get("Item")


def list_jobs_for_tenant(tenant_id: str) -> List[dict]:
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


def list_jobs_all_tenants() -> List[dict]:
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


def list_jobs_by_status(status: str) -> List[dict]:
    """Used by the 30s background refresh loop to find all running jobs
    across every tenant without a Scan."""
    items = []
    resp = _table().query(
        IndexName="status-index",
        KeyConditionExpression=Key("status").eq(status),
    )
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = _table().query(
            IndexName="status-index",
            KeyConditionExpression=Key("status").eq(status),
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        items.extend(resp.get("Items", []))
    return items
