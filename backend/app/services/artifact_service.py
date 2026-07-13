"""Model-artifact uploads into the shared S3 artifacts bucket.

Registering a model requires an `artifactS3Uri`; this service gives users a
way to get one without out-of-band S3 access: the API streams the uploaded
file into `settings.S3_ARTIFACTS_BUCKET` and hands back the URI to register
with. Every tenant's uploads live under a "{tenant_id}/" key prefix -- the
same isolation convention the per-tenant EMR execution roles' S3 grants are
scoped to.
"""
import re
import uuid
from functools import lru_cache
from typing import BinaryIO

from botocore.exceptions import ClientError

from app.config import settings
from app.db.client import get_s3_client
from app.schemas.common import CurrentUser
from app.services import audit_service

_FILENAME_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")

# create_bucket races and re-runs resolve to "it exists now" -- fine.
_BUCKET_EXISTS_ERRORS = ("BucketAlreadyOwnedByYou", "BucketAlreadyExists", "OperationAborted")


def _sanitize_filename(filename: str) -> str:
    """Basename only, restricted to the same character set model versions
    allow -- the name becomes part of an S3 key and later of URIs pasted
    around, so spaces/parens/path separators are replaced, not preserved."""
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = _FILENAME_UNSAFE_RE.sub("_", name).strip("._")
    return name or "artifact"


@lru_cache(maxsize=1)
def _ensure_bucket_once() -> None:
    """Create the artifacts bucket if it doesn't exist yet -- once per
    process (lru_cache), not per upload. In dev the moto server starts empty
    every run, so the first upload creates it; in prod the bucket is
    provisioned out-of-band and head_bucket just succeeds (the task role has
    no s3:CreateBucket, so a missing prod bucket fails loudly here instead
    of half-working). Concurrent first uploads can race the create -- any
    "already exists" outcome is success."""
    s3 = get_s3_client()
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
    try:
        s3.create_bucket(**kwargs)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in _BUCKET_EXISTS_ERRORS:
            raise


def upload_artifact(current_user: CurrentUser, filename: str, fileobj: BinaryIO) -> dict:
    """Stream one uploaded file to S3 and return the artifactS3Uri to
    register the model with. A random key segment keeps repeat uploads of the
    same filename from ever overwriting each other."""
    safe_name = _sanitize_filename(filename)
    key = f"{current_user.tenant_id}/uploads/{uuid.uuid4().hex[:12]}/{safe_name}"
    bucket = settings.S3_ARTIFACTS_BUCKET

    # Size from the spooled upload itself -- no S3 round-trip needed.
    fileobj.seek(0, 2)
    size = fileobj.tell()
    fileobj.seek(0)

    _ensure_bucket_once()
    get_s3_client().upload_fileobj(fileobj, bucket, key)

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
