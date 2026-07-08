"""Pure DynamoDB CRUD for `mlserv-pipelines`."""
from typing import List, Optional

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from app.config import settings
from app.db.client import get_table

ALL_PARTITION = "ALL"


def _table():
    return get_table(settings.TABLE_PIPELINES)


def put_pipeline(item: dict) -> dict:
    _table().put_item(Item=item)
    return item


def record_successful_run(tenant_id: str, pipeline_id: str, at: str) -> None:
    """Field-level stamp written whenever one of the pipeline's jobs persists
    a `success` run. Lets promotion eligibility be a single-attribute read
    instead of a scan over the tenant's job history. No-ops if the pipeline
    row is gone."""
    try:
        _table().update_item(
            Key={"tenant_id": tenant_id, "pipeline_id": pipeline_id},
            UpdateExpression="SET lastSuccessfulRunAt = :t",
            ConditionExpression="attribute_exists(pipeline_id)",
            ExpressionAttributeValues={":t": at},
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise


def get_pipeline(tenant_id: str, pipeline_id: str) -> Optional[dict]:
    resp = _table().get_item(Key={"tenant_id": tenant_id, "pipeline_id": pipeline_id})
    return resp.get("Item")


def list_pipelines_for_tenant(tenant_id: str) -> List[dict]:
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


def list_pipelines_all_tenants() -> List[dict]:
    """PlatformAdmin cross-tenant list -- uses the `all-index` GSI (constant
    partition "ALL") so this is a Query, never a table Scan."""
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
