"""Role gates, cross-tenant isolation, production-run policy, suspension."""
from tests.conftest import (
    advance,
    create_pipeline,
    dp_step,
    promote_pipeline,
    run_pipeline_to_success,
    submit_and_start,
)


def test_platform_admin_cannot_write_tenant_resources(client, identity):
    identity(role="PlatformAdmin", tenant=None)
    resp = client.post("/pipelines", json={"name": "x", "steps": [dp_step()]})
    assert resp.status_code == 403
    resp = client.post("/jobs", json={"pipeline_id": "pl-x"})
    assert resp.status_code == 403


def test_platform_admin_tenant_crud(client, identity):
    identity(role="PlatformAdmin", tenant=None)
    resp = client.post("/tenants", json={"name": "New Bank"})
    assert resp.status_code == 201
    tenant = resp.json()
    assert tenant["status"] == "active"
    assert client.get("/tenants").json()["total"] == 1

    assert client.patch(f"/tenants/{tenant['tenantId']}/suspend").json()["status"] == "suspended"
    assert client.patch(f"/tenants/{tenant['tenantId']}/reactivate").json()["status"] == "active"


def test_tenant_roles_cannot_touch_admin_console(client, identity):
    assert client.post("/tenants", json={"name": "x"}).status_code == 403
    assert client.get("/tenants").status_code == 403


def test_data_scientist_is_read_only_except_staging_job_ops(client, identity, fixed_dq):
    fixed_dq()
    p = create_pipeline(client)  # as Lead
    job = client.post("/jobs", json={"pipeline_id": p["pipelineId"]}).json()

    identity(role="DataScientist")
    # Reads OK.
    assert client.get("/pipelines").status_code == 200
    assert client.get("/models").status_code == 200
    # Writes 403.
    assert client.post("/pipelines", json={"name": "x", "steps": [dp_step()]}).status_code == 403
    assert client.post("/jobs", json={"pipeline_id": p["pipelineId"]}).status_code == 403
    # But staging job operations are allowed.
    assert client.post(f"/jobs/{job['jobId']}/start").status_code == 200
    assert client.post(f"/jobs/{job['jobId']}/stop").status_code == 200


def test_cross_tenant_job_access_is_blocked(client, identity):
    p = create_pipeline(client)
    job = client.post("/jobs", json={"pipeline_id": p["pipelineId"]}).json()

    identity(tenant="other-bank")  # Lead of a different tenant
    # Lookups resolve within the caller's own tenant: the job is invisible.
    assert client.get(f"/jobs/{job['jobId']}").status_code == 404
    assert client.post(f"/jobs/{job['jobId']}/steps/step-1/approve").status_code == 404


def test_production_run_policy(client, identity, fixed_dq):
    fixed_dq()
    pipeline, _ = run_pipeline_to_success(client)
    promote_pipeline(client, pipeline["pipelineId"])

    # Lead may create AND start a pending production job (same authority as
    # the trigger endpoint)...
    job = submit_and_start(client, pipeline["pipelineId"])
    assert job["runEnvironment"] == "production"
    job = advance(client, job["jobId"])
    assert job["status"] == "success"

    # ...but stop/retry/resume of production runs is Operator-only.
    assert client.post(f"/jobs/{job['jobId']}/retry").status_code == 403
    identity(role="DataScientist")
    assert client.post(f"/jobs/{job['jobId']}/retry").status_code == 403
    identity(role="Operator", tenant=None)
    resp = client.post(f"/jobs/{job['jobId']}/retry", params={"tenantId": "acme"})
    assert resp.status_code == 200
    assert resp.json()["runId"] == "RUN-0002"


def test_suspended_tenant_users_are_locked_out(client, identity):
    identity(role="PlatformAdmin", tenant=None)
    client.post("/tenants", json={"name": "acme"})  # tenant_id slugifies to "acme"
    client.patch("/tenants/acme/suspend")

    identity(role="LeadDataScientist", tenant="acme")
    resp = client.get("/pipelines")
    assert resp.status_code == 403
    assert "suspended" in resp.json()["detail"]

    identity(role="PlatformAdmin", tenant=None)
    client.patch("/tenants/acme/reactivate")
    identity(role="LeadDataScientist", tenant="acme")
    assert client.get("/pipelines").status_code == 200


def test_no_launches_into_suspended_tenant_but_stop_allowed(client, identity, fixed_dq):
    fixed_dq()
    pipeline, _ = run_pipeline_to_success(client)
    promote_pipeline(client, pipeline["pipelineId"])
    job = submit_and_start(client, pipeline["pipelineId"])  # running production job

    identity(role="PlatformAdmin", tenant=None)
    client.post("/tenants", json={"name": "acme"})
    client.patch("/tenants/acme/suspend")

    identity(role="Operator", tenant=None)
    resp = client.post(f"/pipelines/{pipeline['pipelineId']}/trigger", params={"tenantId": "acme"})
    assert resp.status_code == 409
    assert "suspended" in resp.json()["detail"]
    # Stopping work in a suspended tenant stays allowed.
    resp = client.post(f"/jobs/{job['jobId']}/stop", params={"tenantId": "acme"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


def test_health_exposes_audit_signal(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["auditWriteFailures"] == 0
