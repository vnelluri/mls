"""Model-artifact upload: POST /models/artifacts."""
import boto3

from app.config import settings


def _upload(client, filename="model.tar.gz", content=b"model-bytes"):
    return client.post("/models/artifacts", files={"file": (filename, content)})


def _get_object_bytes(uri: str) -> bytes:
    bucket, _, key = uri.removeprefix("s3://").partition("/")
    s3 = boto3.client("s3", region_name=settings.AWS_REGION)
    return s3.get_object(Bucket=bucket, Key=key)["Body"].read()


def test_upload_stores_object_under_tenant_prefix(client, identity):
    resp = _upload(client, content=b"weights")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["artifactS3Uri"].startswith(f"s3://{settings.S3_ARTIFACTS_BUCKET}/acme/uploads/")
    assert body["artifactS3Uri"].endswith("/model.tar.gz")
    assert body["fileName"] == "model.tar.gz"
    assert body["sizeBytes"] == len(b"weights")
    assert _get_object_bytes(body["artifactS3Uri"]) == b"weights"


def test_repeat_uploads_of_same_filename_never_collide(client, identity):
    first = _upload(client, content=b"v1").json()
    second = _upload(client, content=b"v2").json()
    assert first["artifactS3Uri"] != second["artifactS3Uri"]
    assert _get_object_bytes(first["artifactS3Uri"]) == b"v1"
    assert _get_object_bytes(second["artifactS3Uri"]) == b"v2"


def test_filename_is_sanitized(client, identity):
    resp = _upload(client, filename="my model (v2).tar.gz")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["fileName"] == "my_model_v2_.tar.gz"
    assert body["artifactS3Uri"].endswith("/my_model_v2_.tar.gz")


def test_upload_requires_tenant_scoped_write_role(client, identity):
    identity(role="DataScientist")
    assert _upload(client).status_code == 403

    # PlatformAdmin spans all tenants -- no tenant prefix to upload under.
    identity(role="PlatformAdmin", tenant=None)
    assert _upload(client).status_code == 403


def test_uploaded_uri_registers_a_model(client, identity):
    uri = _upload(client).json()["artifactS3Uri"]
    resp = client.post(
        "/models",
        json={
            "modelName": "uploaded-scorer",
            "modelId": "MDL-UPLOADED",
            "version": "1",
            "framework": "xgboost",
            "artifactS3Uri": uri,
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["artifactS3Uri"] == uri


def test_upload_writes_audit_event(client, identity):
    key = _upload(client).json()["artifactS3Uri"].removeprefix(
        f"s3://{settings.S3_ARTIFACTS_BUCKET}/"
    )
    resp = client.get("/audit")
    assert resp.status_code == 200, resp.text
    events = [e for e in resp.json()["items"] if e["action"] == "model.artifact_upload"]
    assert events and events[0]["entityId"] == key
