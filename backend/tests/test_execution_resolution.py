"""Phase-1 execution contract: platform-managed EMR fields, model-registry
validation, tenant data-prefix enforcement, per-tenant execution config, and
run-scoped S3 URI resolution through the step cascade."""
import pytest

from app.config import settings
from app.repositories import model_repo, tenant_repo
from app.services.job_service import _resolve_execute_model_config
from tests.conftest import (
    advance,
    create_pipeline,
    dp_step,
    dq_step,
    em_step,
    register_model,
    submit_and_start,
)


# ---- pipeline validation gates ----------------------------------------------

def test_platform_managed_fields_rejected(client, identity):
    register_model(client)
    step = em_step()
    step["config"]["executionRoleArn"] = "arn:aws:iam::1:role/evil"
    resp = client.post("/pipelines", json={"name": "p", "steps": [step]})
    assert resp.status_code == 400
    assert "platform-managed" in resp.json()["detail"]
    assert "executionRoleArn" in resp.json()["detail"]


def test_empty_platform_managed_fields_tolerated(client, identity):
    # The frontend historically initialized these to '' — blank is absent.
    register_model(client)
    step = em_step()
    step["config"]["emrApplicationId"] = ""
    resp = client.post("/pipelines", json={"name": "p", "steps": [step]})
    assert resp.status_code == 201


def test_unregistered_model_rejected(client, identity):
    resp = client.post("/pipelines", json={"name": "p", "steps": [em_step("ghost", "9")]})
    assert resp.status_code == 400
    assert "not registered" in resp.json()["detail"]


def test_uris_must_live_under_tenant_data_prefix(client, identity):
    identity(role="PlatformAdmin", tenant=None)
    resp = client.post(
        "/tenants",
        json={
            "tenantId": "acme",
            "name": "Acme",
            "execution": {"dataS3Prefix": "s3://mlserv-data/acme/"},
        },
    )
    assert resp.status_code == 201, resp.text

    identity(role="LeadDataScientist", tenant="acme")
    register_model(client)
    # Default builder URIs (s3://bucket/...) sit outside the tenant prefix.
    resp = client.post("/pipelines", json={"name": "p", "steps": [em_step()]})
    assert resp.status_code == 400
    assert "outside the tenant's data area" in resp.json()["detail"]

    inside = em_step()
    inside["config"]["inputS3Uri"] = "s3://mlserv-data/acme/staging"
    inside["config"]["outputS3Uri"] = "s3://mlserv-data/acme/scored"
    resp = client.post("/pipelines", json={"name": "p2", "steps": [inside]})
    assert resp.status_code == 201, resp.text


# ---- tenant execution config endpoint ---------------------------------------

def test_platform_admin_sets_execution_config(client, identity):
    identity(role="PlatformAdmin", tenant=None)
    assert client.post("/tenants", json={"tenantId": "acme", "name": "Acme"}).status_code == 201

    resp = client.put(
        "/tenants/acme/execution",
        json={
            "emrApplicationId": "00fabc",
            "emrExecutionRoleArn": "arn:aws:iam::1:role/acme-emr",
            "dataS3Prefix": "s3://mlserv-data/acme/",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["execution"]["emrApplicationId"] == "00fabc"
    assert client.get("/tenants/acme").json()["execution"]["dataS3Prefix"] == "s3://mlserv-data/acme/"

    audit = client.get("/audit?page=1&pageSize=50").json()
    assert any(e["action"] == "tenant.execution_config" for e in audit["items"])


def test_execution_config_is_admin_only(client, identity):
    identity(role="PlatformAdmin", tenant=None)
    assert client.post("/tenants", json={"tenantId": "acme", "name": "Acme"}).status_code == 201
    identity(role="LeadDataScientist", tenant="acme")
    resp = client.put("/tenants/acme/execution", json={"emrApplicationId": "x"})
    assert resp.status_code == 403


def test_execution_config_validates_s3_uris(client, identity):
    identity(role="PlatformAdmin", tenant=None)
    assert client.post("/tenants", json={"tenantId": "acme", "name": "Acme"}).status_code == 201
    resp = client.put("/tenants/acme/execution", json={"dataS3Prefix": "https://not-s3"})
    assert resp.status_code == 422


# ---- run-scoped URI resolution through a full run ----------------------------

def test_run_scoped_uris_chain_through_the_cascade(client, identity, fixed_dq):
    fixed_dq()
    pipeline = create_pipeline(client, steps=[dp_step(), em_step(), dq_step()])
    job = submit_and_start(client, pipeline["pipelineId"])
    job = advance(client, job["jobId"])
    assert job["status"] == "success", job
    run_id = job["runId"]

    dp, em, dq = job["steps"]
    unload_uri = dp["output"]["s3Uri"]
    assert unload_uri.startswith("s3://bucket/in/") and unload_uri.endswith(f"/{run_id}/")

    # The model scored THIS run's extract...
    assert em["resolved"]["inputS3Uri"] == unload_uri
    # ...and wrote to its own run-scoped prefix, which DQ then inspected.
    results_prefix = em["output"]["resultsS3Prefix"]
    assert results_prefix.startswith("s3://bucket/out/") and results_prefix.endswith(f"/{run_id}/")
    assert em["resolved"]["outputS3Uri"] == results_prefix
    assert dq["resolved"]["inputS3Uri"] == results_prefix


def test_retry_resolves_fresh_prefixes(client, identity, fixed_dq):
    fixed_dq()
    pipeline = create_pipeline(client, steps=[dp_step(), em_step(), dq_step()])
    job = submit_and_start(client, pipeline["pipelineId"])
    job = advance(client, job["jobId"])
    first_prefix = job["steps"][1]["output"]["resultsS3Prefix"]

    resp = client.post(f"/jobs/{job['jobId']}/retry")
    assert resp.status_code == 200, resp.text
    job = advance(client, job["jobId"])
    assert job["status"] == "success", job
    second_prefix = job["steps"][1]["output"]["resultsS3Prefix"]
    assert second_prefix != first_prefix
    assert second_prefix.endswith(f"/{job['runId']}/")


# ---- real-mode resolution of tenant EMR resources ----------------------------

def _job_item(steps):
    return {"tenant_id": "acme", "job_id": "job-1", "run_id": "RUN-0001", "steps": steps}


def _em_job_step():
    return {
        "step_id": "step-1",
        "type": "execute_model",
        "config": {
            "modelName": "scorer",
            "modelVersion": "1",
            "inputS3Uri": "s3://mlserv-data/acme/staging",
            "outputS3Uri": "s3://mlserv-data/acme/scored",
        },
    }


def test_real_mode_requires_tenant_execution_config(aws, monkeypatch):
    monkeypatch.setattr(settings, "EMR_MODE", "real")
    tenant_repo.put_tenant({"tenant_id": "acme", "name": "Acme", "status": "active"})
    step = _em_job_step()
    with pytest.raises(RuntimeError) as exc:
        _resolve_execute_model_config(_job_item([step]), step)
    assert "emrApplicationId" in str(exc.value)
    assert "execution config" in str(exc.value)


def test_real_mode_resolves_tenant_resources_and_artifact(aws, monkeypatch):
    monkeypatch.setattr(settings, "EMR_MODE", "real")
    tenant_repo.put_tenant(
        {
            "tenant_id": "acme",
            "name": "Acme",
            "status": "active",
            "execution": {
                "emrApplicationId": "00fabc",
                "emrExecutionRoleArn": "arn:aws:iam::1:role/acme-emr",
                "entryPointS3Uri": "s3://mlserv-platform/entrypoints/scoring_entrypoint.py",
            },
        }
    )
    model_repo.create_model(
        {
            "tenant_id": "acme",
            "model_name": "scorer",
            "version": "1",
            "stage": "Staging",
            "artifactS3Uri": "s3://mlserv-models/acme/scorer/1.tar.gz",
        }
    )
    step = _em_job_step()
    # Legacy authored values must NOT win over the tenant's execution config.
    step["config"]["executionRoleArn"] = "arn:aws:iam::1:role/legacy"

    resolved = _resolve_execute_model_config(_job_item([step]), step)
    assert resolved["emrApplicationId"] == "00fabc"
    assert resolved["executionRoleArn"] == "arn:aws:iam::1:role/acme-emr"
    assert resolved["entryPointS3Uri"].endswith("scoring_entrypoint.py")
    assert resolved["artifactS3Uri"] == "s3://mlserv-models/acme/scorer/1.tar.gz"
    assert resolved["outputS3Uri"].startswith("s3://mlserv-data/acme/scored/")
    assert resolved["outputS3Uri"].endswith("/RUN-0001/")


def test_real_mode_requires_registered_artifact(aws, monkeypatch):
    monkeypatch.setattr(settings, "EMR_MODE", "real")
    tenant_repo.put_tenant(
        {
            "tenant_id": "acme",
            "name": "Acme",
            "status": "active",
            "execution": {
                "emrApplicationId": "00fabc",
                "emrExecutionRoleArn": "arn:aws:iam::1:role/acme-emr",
                "entryPointS3Uri": "s3://mlserv-platform/entrypoint.py",
            },
        }
    )
    step = _em_job_step()
    with pytest.raises(RuntimeError) as exc:
        _resolve_execute_model_config(_job_item([step]), step)
    assert "not registered" in str(exc.value)
