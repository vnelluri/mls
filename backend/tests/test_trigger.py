"""ESP trigger endpoint: gates, happy path, and idempotency."""
from tests.conftest import (
    create_pipeline,
    dp_step,
    dq_step,
    em_step,
    promote_model,
    promote_pipeline,
    register_model,
    run_pipeline_to_success,
)


def make_production_pipeline(client, fixed_dq, model_name="scorer", name="prod-pl"):
    """Register+promote a model to Production, run its pipeline to success in
    staging, then promote the pipeline to production."""
    fixed_dq()
    register_model(client, name=model_name)
    promote_model(client, model_name, "1", "Staging")
    promote_model(client, model_name, "1", "Production")
    pipeline, _ = run_pipeline_to_success(
        client, steps=[dp_step(), em_step(model_name=model_name), dq_step()], name=name
    )
    return promote_pipeline(client, pipeline["pipelineId"])


def trigger(client, pipeline_id, key=None, tenant=None, body=None):
    params = {"tenantId": tenant} if tenant else {}
    headers = {"Idempotency-Key": key} if key else {}
    return client.post(
        f"/pipelines/{pipeline_id}/trigger", params=params, headers=headers, json=body or {}
    )


def test_trigger_rejects_staging_pipeline(client, identity, fixed_dq):
    fixed_dq()
    pipeline, _ = run_pipeline_to_success(client)
    # Activate but do NOT promote: still staging.
    client.patch(f"/pipelines/{pipeline['pipelineId']}", json={"status": "active"})
    resp = trigger(client, pipeline["pipelineId"])
    assert resp.status_code == 409
    assert "staging" in resp.json()["detail"]


def test_trigger_rejects_non_production_model(client, identity, fixed_dq):
    fixed_dq()
    register_model(client, name="staged-model")
    promote_model(client, "staged-model", "1", "Staging")
    pipeline, _ = run_pipeline_to_success(
        client, steps=[dp_step(), em_step(model_name="staged-model"), dq_step()]
    )
    promote_pipeline(client, pipeline["pipelineId"])
    resp = trigger(client, pipeline["pipelineId"])
    assert resp.status_code == 409
    assert "Production" in resp.json()["detail"]


def test_trigger_happy_path_as_operator(client, identity, fixed_dq):
    promoted = make_production_pipeline(client, fixed_dq)

    identity(role="Operator", tenant=None)
    resp = trigger(
        client, promoted["pipelineId"], key="esp-1", tenant="acme",
        body={"externalRunId": "ESP-RUN-1"},
    )
    assert resp.status_code == 201, resp.text
    job = resp.json()
    assert job["status"] == "running"
    assert job["triggeredVia"] == "api"
    assert job["externalRunId"] == "ESP-RUN-1"
    assert job["runEnvironment"] == "production"


def test_trigger_operator_requires_tenant_param(client, identity, fixed_dq):
    promoted = make_production_pipeline(client, fixed_dq)
    identity(role="Operator", tenant=None)
    assert trigger(client, promoted["pipelineId"]).status_code == 400


def test_trigger_idempotency_key(client, identity, fixed_dq):
    promoted = make_production_pipeline(client, fixed_dq)

    first = trigger(client, promoted["pipelineId"], key="esp-42")
    again = trigger(client, promoted["pipelineId"], key="esp-42")
    other = trigger(client, promoted["pipelineId"], key="esp-43")
    assert first.status_code == 201 and again.status_code == 201
    assert first.json()["jobId"] == again.json()["jobId"]
    assert other.json()["jobId"] != first.json()["jobId"]


def test_trigger_key_reuse_across_pipelines_conflicts(client, identity, fixed_dq):
    promoted_a = make_production_pipeline(client, fixed_dq, model_name="model-a", name="pl-a")
    promoted_b = make_production_pipeline(client, fixed_dq, model_name="model-b", name="pl-b")

    assert trigger(client, promoted_a["pipelineId"], key="esp-9").status_code == 201
    resp = trigger(client, promoted_b["pipelineId"], key="esp-9")
    assert resp.status_code == 409
    assert "different pipeline" in resp.json()["detail"]


def test_trigger_forbidden_for_data_scientist(client, identity, fixed_dq):
    promoted = make_production_pipeline(client, fixed_dq)
    identity(role="DataScientist")
    assert trigger(client, promoted["pipelineId"]).status_code == 403
