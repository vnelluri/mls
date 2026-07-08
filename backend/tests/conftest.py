"""
Test harness.

DynamoDB is moto's in-process mock_aws (no moto server, no network): the env
below blanks DDB_ENDPOINT_URL so boto3 targets "real AWS", which mock_aws
intercepts. Every test gets freshly created, empty tables.

Timing: STEP_DURATION_SECONDS=0 and the EMR mock's phase constants patched to
0 make each `GET /jobs/{id}` refresh advance exactly one step (a step started
mid-pass completes on the next refresh, by design), so full pipeline runs
take a handful of requests and zero sleeps.

Auth is the dev path: `identity(role, tenant)` repoints the synthetic user,
so RBAC tests just switch roles between requests.
"""
import os

# Must be set before any `app.*` import — app.config builds its Settings
# singleton at import time (env vars take precedence over backend/.env).
os.environ.update(
    {
        "AUTH_MODE": "dev",
        "DDB_ENDPOINT_URL": "",  # blank -> boto3 "real AWS" -> intercepted by mock_aws
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_REGION": "us-east-1",
        "AWS_DEFAULT_REGION": "us-east-1",
        "EMR_MODE": "mock",
        "SNOWFLAKE_MODE": "mock",
        "EMR_MOCK_FAILURE_RATE": "0.0",
        "STEP_DURATION_SECONDS": "0",
        "STEP_TIMEOUT_SECONDS": "21600",
        "JOB_REFRESH_INTERVAL_SECONDS": "3600",
        "DEV_USER_ID": "test-user",
        "DEV_USER_EMAIL": "test@example.com",
        "DEV_USER_NAME": "Test User",
        "DEV_USER_ROLE": "LeadDataScientist",
        "DEV_USER_TENANT_ID": "acme",
    }
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from moto import mock_aws  # noqa: E402

import scripts.create_tables as create_tables  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import client as db_client  # noqa: E402
from app.main import app  # noqa: E402
from app.services import emr_execution_service as emr  # noqa: E402

TERMINAL = {"success", "failed", "cancelled", "awaiting_approval"}


@pytest.fixture()
def aws():
    """Fresh in-process DynamoDB with all tables created, per test."""
    with mock_aws():
        db_client.get_dynamodb_resource.cache_clear()
        db_client.get_dynamodb_client.cache_clear()
        create_tables.main()
        yield
    db_client.get_dynamodb_resource.cache_clear()
    db_client.get_dynamodb_client.cache_clear()


@pytest.fixture()
def client(aws):
    # No context manager: the lifespan (background refresh loop) is not
    # needed — the per-GET refresh drives all progression in tests.
    return TestClient(app)


@pytest.fixture(autouse=True)
def instant_emr(monkeypatch):
    """Collapse the mock EMR state machine so runs are terminal immediately."""
    monkeypatch.setattr(emr, "PENDING_SECONDS", 0)
    monkeypatch.setattr(emr, "RUNNING_SECONDS", 0)


@pytest.fixture()
def identity(monkeypatch):
    """Switch the synthetic dev identity; defaults to LeadDataScientist@acme."""

    def _set(role="LeadDataScientist", tenant="acme"):
        monkeypatch.setattr(settings, "DEV_USER_ROLE", role)
        monkeypatch.setattr(settings, "DEV_USER_TENANT_ID", tenant)

    _set()
    return _set


@pytest.fixture()
def fixed_dq(monkeypatch):
    """Make the data-quality step deterministic. Call with overrides, e.g.
    fixed_dq(errorRate=0.06) for a Rework-zone run (warn 0.05 / fail 0.15)."""
    from app.services.data_quality_service import MockDataQualityService

    def _set(**overrides):
        result = {
            "requestCount": 100,
            "avgLatencyMs": 50.0,
            "errorRate": 0.01,
            "driftMetrics": {"feature_a": 0.01},
            "driftComputation": "synthetic",
            "dataQualityPassed": True,
            "dataQualityDetails": {},
        }
        result.update(overrides)
        monkeypatch.setattr(
            MockDataQualityService,
            "execute",
            lambda self, cfg, drift_baseline=None, drift_seed=None, previous_row_count=None: dict(result),
        )

    return _set


# ---------------------------------------------------------------------------
# Payload builders / API helpers
# ---------------------------------------------------------------------------

def dp_step():
    return {
        "type": "data_pipeline",
        "config": {
            "snowflakeDatabase": "DB",
            "snowflakeSchema": "SCH",
            "snowflakeTable": "T",
            "snowflakeWarehouse": "WH",
            "destinationS3Uri": "s3://bucket/in",
        },
    }


def em_step(model_name="scorer", model_version="1"):
    # emrApplicationId / executionRoleArn / entryPointS3Uri are platform-managed
    # (tenant execution config) — authoring them is rejected at pipeline create.
    return {
        "type": "execute_model",
        "config": {
            "modelName": model_name,
            "modelVersion": model_version,
            "inputS3Uri": "s3://bucket/in",
            "outputS3Uri": "s3://bucket/out",
        },
    }


def dq_step():
    return {
        "type": "data_quality_check",
        "config": {
            "checks": [{"name": "nulls", "type": "null_rate", "threshold": 0.99}],
            "inputS3Uri": "s3://bucket/out",
        },
    }


def approval_step():
    return {"type": "approval", "config": {}}


def create_pipeline(client, steps=None, name="test-pipeline"):
    # Pipeline creation validates execute_model refs against the model
    # registry, so make sure every referenced model exists (409 = already
    # registered by the test itself, which is fine).
    for step in steps or []:
        if step.get("type") == "execute_model":
            cfg = step["config"]
            resp = client.post(
                "/models",
                json={
                    "modelName": cfg["modelName"],
                    "modelId": f"MDL-{cfg['modelName'].upper()}",
                    "version": cfg["modelVersion"],
                    "framework": "xgboost",
                    "artifactS3Uri": f"s3://models/{cfg['modelName']}/{cfg['modelVersion']}.tar.gz",
                },
            )
            assert resp.status_code in (201, 409), resp.text
    resp = client.post("/pipelines", json={"name": name, "steps": steps or [dp_step()]})
    assert resp.status_code == 201, resp.text
    return resp.json()


def register_model(client, name="scorer", version="1", **extra):
    body = {
        "modelName": name,
        "modelId": f"MDL-{name.upper()}",
        "version": version,
        "framework": "xgboost",
        "artifactS3Uri": f"s3://models/{name}/{version}.tar.gz",
    }
    body.update(extra)
    resp = client.post("/models", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def promote_model(client, name, version, stage):
    resp = client.patch(f"/models/{name}/{version}/promote", json={"targetStage": stage})
    assert resp.status_code == 200, resp.text
    return resp.json()


def submit_and_start(client, pipeline_id):
    resp = client.post("/jobs", json={"pipeline_id": pipeline_id})
    assert resp.status_code == 201, resp.text
    job = resp.json()
    resp = client.post(f"/jobs/{job['jobId']}/start")
    assert resp.status_code == 200, resp.text
    return resp.json()


def advance(client, job_id, max_iters=25):
    """Poll GET /jobs/{id} (each call advances one step) until terminal."""
    job = None
    for _ in range(max_iters):
        resp = client.get(f"/jobs/{job_id}")
        assert resp.status_code == 200, resp.text
        job = resp.json()
        if job["status"] in TERMINAL:
            return job
    raise AssertionError(f"job {job_id} never reached a terminal status: {job and job['status']}")


def run_pipeline_to_success(client, steps=None, name="runnable"):
    """Create pipeline -> submit -> start -> advance; asserts success."""
    pipeline = create_pipeline(client, steps=steps, name=name)
    job = submit_and_start(client, pipeline["pipelineId"])
    job = advance(client, job["jobId"])
    assert job["status"] == "success", job
    return pipeline, job


def promote_pipeline(client, pipeline_id, ticket="CHG0031245"):
    resp = client.post(f"/pipelines/{pipeline_id}/promote", json={"service_now_ticket": ticket})
    assert resp.status_code == 200, resp.text
    return resp.json()
