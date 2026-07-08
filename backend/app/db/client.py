"""
Boto3 DynamoDB resource/client factory.

Endpoint-url aware: when `DDB_ENDPOINT_URL` is set (local dev -> moto server),
boto3 is pointed at it. In prod, leave `DDB_ENDPOINT_URL` unset/empty and
boto3 will talk to real AWS DynamoDB using the ambient credentials/role.

`get_table` returns a thin wrapper that converts Python floats to Decimal on
write (boto3's serializer raises TypeError on raw floats -- and the mock
data-quality/monitoring paths produce plenty of them) and Decimals back to
int/float on read, so repositories and services never handle Decimal at all.
"""
from decimal import Decimal
from functools import lru_cache
from typing import List

import boto3
from boto3.dynamodb.types import TypeSerializer

from app.config import settings


def _to_ddb(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_ddb(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_ddb(v) for v in value]
    return value


def _from_ddb(value):
    if isinstance(value, Decimal):
        as_int = int(value)
        return as_int if value == as_int else float(value)
    if isinstance(value, dict):
        return {k: _from_ddb(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_from_ddb(v) for v in value]
    return value


class _TableWrapper:
    """Proxies the boto3 Table methods the repositories use, applying
    float<->Decimal conversion at the storage boundary."""

    def __init__(self, table):
        self._table = table

    def put_item(self, Item, **kwargs):
        return self._table.put_item(Item=_to_ddb(Item), **kwargs)

    def get_item(self, **kwargs):
        resp = self._table.get_item(**kwargs)
        if "Item" in resp:
            resp["Item"] = _from_ddb(resp["Item"])
        return resp

    def query(self, **kwargs):
        resp = self._table.query(**kwargs)
        resp["Items"] = [_from_ddb(i) for i in resp.get("Items", [])]
        return resp

    def scan(self, **kwargs):
        resp = self._table.scan(**kwargs)
        resp["Items"] = [_from_ddb(i) for i in resp.get("Items", [])]
        return resp

    def delete_item(self, **kwargs):
        return self._table.delete_item(**kwargs)

    def update_item(self, **kwargs):
        if "ExpressionAttributeValues" in kwargs:
            kwargs["ExpressionAttributeValues"] = _to_ddb(kwargs["ExpressionAttributeValues"])
        resp = self._table.update_item(**kwargs)
        if "Attributes" in resp:
            resp["Attributes"] = _from_ddb(resp["Attributes"])
        return resp


@lru_cache(maxsize=1)
def get_dynamodb_resource():
    kwargs = {"region_name": settings.AWS_REGION}
    if settings.DDB_ENDPOINT_URL:
        kwargs["endpoint_url"] = settings.DDB_ENDPOINT_URL
        # moto server ignores real credentials but boto3 requires *some* value
        kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID or "test"
        kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY or "test"
    return boto3.resource("dynamodb", **kwargs)


@lru_cache(maxsize=1)
def get_dynamodb_client():
    kwargs = {"region_name": settings.AWS_REGION}
    if settings.DDB_ENDPOINT_URL:
        kwargs["endpoint_url"] = settings.DDB_ENDPOINT_URL
        kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID or "test"
        kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY or "test"
    return boto3.client("dynamodb", **kwargs)


def get_table(table_name: str) -> _TableWrapper:
    return _TableWrapper(get_dynamodb_resource().Table(table_name))


_type_serializer = TypeSerializer()


def serialize_item(item: dict) -> dict:
    """High-level dict -> low-level DynamoDB wire format (per top-level key),
    with the same float->Decimal conversion the table wrapper applies. For
    building TransactWriteItems entries, which only the low-level client
    accepts."""
    return {k: _type_serializer.serialize(_to_ddb(v)) for k, v in item.items()}


def transact_write(actions: List[dict]) -> None:
    """Execute a TransactWriteItems call (already in wire format). Raises
    botocore's TransactionCanceledException on condition failures -- callers
    inspect CancellationReasons to tell which action failed."""
    get_dynamodb_client().transact_write_items(TransactItems=actions)
