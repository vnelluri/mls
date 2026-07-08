#!/usr/bin/env python
"""Create all 7 DynamoDB tables + GSIs. Idempotent -- skips tables that
already exist. Targets whatever DDB_ENDPOINT_URL is configured (moto server
in local dev, real AWS when unset)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from botocore.exceptions import ClientError  # noqa: E402

from app.config import settings  # noqa: E402
from app.db.client import get_dynamodb_client  # noqa: E402


def _gsi(name, hash_attr, range_attr=None):
    schema = [{"AttributeName": hash_attr, "KeyType": "HASH"}]
    if range_attr:
        schema.append({"AttributeName": range_attr, "KeyType": "RANGE"})
    return {
        "IndexName": name,
        "KeySchema": schema,
        "Projection": {"ProjectionType": "ALL"},
    }


TABLES = [
    {
        "TableName": settings.TABLE_TENANTS,
        "KeySchema": [{"AttributeName": "tenant_id", "KeyType": "HASH"}],
        "AttributeDefinitions": [
            {"AttributeName": "tenant_id", "AttributeType": "S"},
            {"AttributeName": "status", "AttributeType": "S"},
        ],
        "GlobalSecondaryIndexes": [_gsi("status-index", "status", "tenant_id")],
    },
    {
        "TableName": settings.TABLE_GROUP_MAPPINGS,
        "KeySchema": [{"AttributeName": "group_id", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "group_id", "AttributeType": "S"}],
    },
    {
        "TableName": settings.TABLE_PIPELINES,
        "KeySchema": [
            {"AttributeName": "tenant_id", "KeyType": "HASH"},
            {"AttributeName": "pipeline_id", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "tenant_id", "AttributeType": "S"},
            {"AttributeName": "pipeline_id", "AttributeType": "S"},
            {"AttributeName": "all_pk", "AttributeType": "S"},
            {"AttributeName": "all_sk", "AttributeType": "S"},
            {"AttributeName": "status", "AttributeType": "S"},
            {"AttributeName": "updatedAt", "AttributeType": "S"},
        ],
        "GlobalSecondaryIndexes": [
            _gsi("status-index", "status", "updatedAt"),
            _gsi("all-index", "all_pk", "all_sk"),
        ],
    },
    {
        "TableName": settings.TABLE_JOBS,
        "KeySchema": [
            {"AttributeName": "tenant_id", "KeyType": "HASH"},
            {"AttributeName": "job_id", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "tenant_id", "AttributeType": "S"},
            {"AttributeName": "job_id", "AttributeType": "S"},
            {"AttributeName": "all_pk", "AttributeType": "S"},
            {"AttributeName": "all_sk", "AttributeType": "S"},
            {"AttributeName": "status", "AttributeType": "S"},
            {"AttributeName": "submittedAt", "AttributeType": "S"},
            {"AttributeName": "run_id", "AttributeType": "S"},
        ],
        "GlobalSecondaryIndexes": [
            _gsi("run-id-index", "run_id", "tenant_id"),
            _gsi("status-index", "status", "submittedAt"),
            _gsi("all-index", "all_pk", "all_sk"),
        ],
    },
    {
        "TableName": settings.TABLE_MODELS,
        "KeySchema": [
            {"AttributeName": "tenant_id", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "tenant_id", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
            {"AttributeName": "all_pk", "AttributeType": "S"},
            {"AttributeName": "all_sk", "AttributeType": "S"},
            {"AttributeName": "stage", "AttributeType": "S"},
            {"AttributeName": "stage_sk", "AttributeType": "S"},
        ],
        "GlobalSecondaryIndexes": [
            # name-index (model_name, version) was removed: never queried, and
            # keyed without a tenant so any consumer would leak across tenants.
            _gsi("stage-index", "stage", "stage_sk"),
            _gsi("all-index", "all_pk", "all_sk"),
        ],
    },
    {
        "TableName": settings.TABLE_MONITORING_SNAPSHOTS,
        "KeySchema": [
            {"AttributeName": "tenant_id", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "tenant_id", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
            {"AttributeName": "all_pk", "AttributeType": "S"},
            {"AttributeName": "recordedAt", "AttributeType": "S"},
            {"AttributeName": "model_trend_pk", "AttributeType": "S"},
            {"AttributeName": "derivedStatus", "AttributeType": "S"},
        ],
        "GlobalSecondaryIndexes": [
            _gsi("model-trend-index", "model_trend_pk", "recordedAt"),
            _gsi("status-index", "derivedStatus", "recordedAt"),
            _gsi("all-index", "all_pk", "recordedAt"),
        ],
    },
    {
        "TableName": settings.TABLE_AUDIT,
        "KeySchema": [
            {"AttributeName": "tenant_id", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "tenant_id", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
            {"AttributeName": "event_date", "AttributeType": "S"},
            {"AttributeName": "actor", "AttributeType": "S"},
            {"AttributeName": "entity_pk", "AttributeType": "S"},
        ],
        "GlobalSecondaryIndexes": [
            _gsi("all-index", "event_date", "sk"),
            _gsi("actor-index", "actor", "sk"),
            _gsi("entity-index", "entity_pk", "sk"),
        ],
    },
]


def main() -> None:
    client = get_dynamodb_client()
    endpoint = settings.DDB_ENDPOINT_URL or "(real AWS)"
    print(f"Creating tables against: {endpoint}")

    for spec in TABLES:
        name = spec["TableName"]
        try:
            client.create_table(BillingMode="PAY_PER_REQUEST", **spec)
            client.get_waiter("table_exists").wait(TableName=name)
            print(f"  created  {name}")
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ResourceInUseException":
                print(f"  exists   {name} (skipped)")
            else:
                raise

    print("All tables ready.")


if __name__ == "__main__":
    main()
