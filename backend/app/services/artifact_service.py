"""Model-artifact uploads into the shared S3 artifacts bucket.

Registering a model requires an `artifactS3Uri`; this service gives users a
way to get one without out-of-band S3 access: the API streams the uploaded
file into `settings.S3_ARTIFACTS_BUCKET` and hands back the URI to register
with. Every tenant's uploads live under a "{tenant_id}/" key prefix -- the
same isolation convention the per-tenant EMR execution roles' S3 grants are
scoped to.

Endpoint-url aware like the DynamoDB client factory: with `S3_ENDPOINT_URL`
set (local dev -> the same moto server that emulates DynamoDB) boto3 is
pointed at it; in prod leave it unset/empty for real S3 via the task role.
"""
import re
import uuid
from functools import lru_cache
from typing import BinaryIO

import boto3
from botocore.exceptions import ClientError

from app.config import settings
from app.schemas.common import CurrentUser
from app.services import audit_service

_FILENAME_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


@lru_cache(maxsize=1)
def get_s3_client():
    kwargs = {"region_name": settings.AWS_REGION}
    if settings.S3_ENDPOINT_URL:
        kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL
        # moto ignores real credentials but boto3 requires *some* value
        kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID or "test"
        kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY or "test"
    return boto3.client("s3", **kwargs)


def _sanitize_filename(filename: str) -> str:
    """Basename only, restricted to the same character set model versions
    allow -- the name becomes part of an S3 key and later of URIs pasted
    around, so spaces/parens/path separators are replaced, not preserved."""
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = _FILENAME_UNSAFE_RE.sub("_", name).strip("._")
    return name or "artifact"


def _ensure_bucket(s3) -> None:
    """Create the artifacts bucket if it doesn't exist yet. In dev the moto
    server starts empty every run, so first upload creates it; in prod the
    bucket is provisioned out-of-band and head_bucket just succeeds (the task
    role has no s3:CreateBucket, so a missing prod bucket fails loudly here
    instead of half-working)."""
    bucket = settings.S3_ARTIFACTS_BUCKET
    try:
        s3.head_bucket(Bucket=bucket)
        return
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in ("404", "NoSuchBucket"):
            raise
    kwargs = {"Bucket": bucket}
    # us-east-1 is the one region create_bucket rejects a LocationConstraint for
    if settings.AWS_REGION != "us-east-1":
        kwargs["CreateBucketConfiguration"] = {"LocationConstraint": settings.AWS_REGION}
    s3.create_bucket(**kwargs)


def upload_artifact(current_user: CurrentUser, filename: str, fileobj: BinaryIO) -> dict:
    """Stream one uploaded file to S3 and return the artifactS3Uri to
    register the model with. A random key segment keeps repeat uploads of the
    same filename from ever overwriting each other."""
    safe_name = _sanitize_filename(filename)
    key = f"{current_user.tenant_id}/uploads/{uuid.uuid4().hex[:12]}/{safe_name}"
    bucket = settings.S3_ARTIFACTS_BUCKET

    s3 = get_s3_client()
    _ensure_bucket(s3)
    s3.upload_fileobj(fileobj, bucket, key)
    size = s3.head_object(Bucket=bucket, Key=key)["ContentLength"]

    uri = f"s3://{bucket}/{key}"
    audit_service.write_event(
        current_user.tenant_id,
        current_user.user_id,
        current_user.role,
        "model.artifact_upload",
        "artifact",
        key,
        f"Uploaded model artifact '{safe_name}' ({size} bytes) to {uri}",
    )
    return {"artifactS3Uri": uri, "fileName": safe_name, "sizeBytes": size}
