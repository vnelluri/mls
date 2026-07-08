"""Job lifecycle: cascade, EMR outcomes, approval, stop/retry/resume, timeout."""
from app.config import settings
from tests.conftest import (
    advance,
    approval_step,
    create_pipeline,
    dp_step,
    dq_step,
    em_step,
    register_model,
    submit_and_start,
)


def test_created_job_is_pending_and_idle(client, identity):
    p = create_pipeline(client, steps=[dp_step(), em_step()])
    resp = client.post("/jobs", json={"pipeline_id": p["pipelineId"]})
    assert resp.status_code == 201
    job = resp.json()
    assert job["status"] == "pending"
    assert job["runId"] == "RUN-0001"
    assert all(s["status"] == "idle" for s in job["steps"])
    assert job["runEnvironment"] == "staging"


def test_start_runs_and_double_start_conflicts(client, identity):
    p = create_pipeline(client, steps=[dp_step()])
    job = submit_and_start(client, p["pipelineId"])
    assert job["status"] == "running"
    resp = client.post(f"/jobs/{job['jobId']}/start")
    assert resp.status_code == 409


def test_full_cascade_success(client, identity, fixed_dq):
    fixed_dq()
    register_model(client)
    p = create_pipeline(client, steps=[dp_step(), em_step(), dq_step()])
    job = submit_and_start(client, p["pipelineId"])
    job = advance(client, job["jobId"])

    assert job["status"] == "success"
    statuses = {s["type"]: s["status"] for s in job["steps"]}
    assert statuses == {
        "data_pipeline": "succeeded",
        "execute_model": "succeeded",
        "data_quality_check": "succeeded",
    }
    em = next(s for s in job["steps"] if s["type"] == "execute_model")
    assert em["output"]["emrState"] == "SUCCESS"
    # Results are partitioned per run under the configured output prefix.
    assert em["output"]["resultsS3Prefix"].startswith("s3://bucket/out/")
    assert em["output"]["resultsS3Prefix"].endswith("/RUN-0001/")
    assert em["emrJobRunId"].startswith("mock-emr-")


def test_emr_failure_fails_job_at_execute_model(client, identity, monkeypatch):
    monkeypatch.setattr(settings, "EMR_MOCK_FAILURE_RATE", 1.0)
    p = create_pipeline(client, steps=[dp_step(), em_step(), dq_step()])
    job = submit_and_start(client, p["pipelineId"])
    job = advance(client, job["jobId"])

    assert job["status"] == "failed"
    em = next(s for s in job["steps"] if s["type"] == "execute_model")
    assert em["status"] == "failed"
    assert "FAILED" in em["errorMessage"]
    # The failure stops the cascade: DQ never ran.
    dq = next(s for s in job["steps"] if s["type"] == "data_quality_check")
    assert dq["status"] == "idle"


def test_approval_gate_approve_completes_job(client, identity, fixed_dq):
    fixed_dq()
    register_model(client)
    p = create_pipeline(client, steps=[dp_step(), em_step(), dq_step(), approval_step()])
    job = submit_and_start(client, p["pipelineId"])
    job = advance(client, job["jobId"])
    assert job["status"] == "awaiting_approval"

    gate = next(s for s in job["steps"] if s["type"] == "approval")
    resp = client.post(f"/jobs/{job['jobId']}/steps/{gate['stepId']}/approve")
    assert resp.status_code == 200
    approved = resp.json()
    assert approved["status"] == "success"
    assert next(s for s in approved["steps"] if s["type"] == "approval")["status"] == "approved"

    # Approving twice (or approving a non-awaiting job) conflicts.
    resp = client.post(f"/jobs/{job['jobId']}/steps/{gate['stepId']}/approve")
    assert resp.status_code == 409


def test_reject_fails_job(client, identity, fixed_dq):
    fixed_dq()
    p = create_pipeline(client, steps=[dp_step(), approval_step()])
    job = submit_and_start(client, p["pipelineId"])
    job = advance(client, job["jobId"])
    assert job["status"] == "awaiting_approval"

    gate = next(s for s in job["steps"] if s["type"] == "approval")
    resp = client.post(f"/jobs/{job['jobId']}/steps/{gate['stepId']}/reject")
    assert resp.status_code == 200
    assert resp.json()["status"] == "failed"


def test_stop_then_resume_keeps_completed_steps(client, identity, fixed_dq):
    fixed_dq()
    p = create_pipeline(client, steps=[dp_step(), em_step(), dq_step()])
    job = submit_and_start(client, p["pipelineId"])
    # One refresh: step 1 completes, step 2 starts.
    client.get(f"/jobs/{job['jobId']}")

    resp = client.post(f"/jobs/{job['jobId']}/stop")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"
    # Stopping again conflicts.
    assert client.post(f"/jobs/{job['jobId']}/stop").status_code == 409

    resp = client.post(f"/jobs/{job['jobId']}/resume")
    assert resp.status_code == 200
    resumed = resp.json()
    assert resumed["runId"] == "RUN-0002"
    # The completed step kept its result; the interrupted one was reset and re-runs.
    assert resumed["steps"][0]["status"] == "succeeded"

    job = advance(client, job["jobId"])
    assert job["status"] == "success"
    history = job["runHistory"]
    assert [h["runId"] for h in history] == ["RUN-0001"]
    assert history[0]["finalStatus"] == "cancelled"


def test_retry_archives_previous_run_evidence(client, identity, fixed_dq, monkeypatch):
    fixed_dq()
    monkeypatch.setattr(settings, "EMR_MOCK_FAILURE_RATE", 1.0)
    p = create_pipeline(client, steps=[dp_step(), em_step(), dq_step()])
    job = submit_and_start(client, p["pipelineId"])
    job = advance(client, job["jobId"])
    assert job["status"] == "failed"

    monkeypatch.setattr(settings, "EMR_MOCK_FAILURE_RATE", 0.0)
    resp = client.post(f"/jobs/{job['jobId']}/retry")
    assert resp.status_code == 200
    retried = resp.json()
    assert retried["runId"] == "RUN-0002"
    assert all(s["status"] in ("idle", "running") for s in retried["steps"])

    # The failed run's step-level evidence is archived in runHistory.
    archived = retried["runHistory"][0]
    assert archived["runId"] == "RUN-0001"
    assert archived["finalStatus"] == "failed"
    archived_em = next(s for s in archived["steps"] if s["type"] == "execute_model")
    assert archived_em["status"] == "failed"
    assert "FAILED" in archived_em["errorMessage"]

    job = advance(client, job["jobId"])
    assert job["status"] == "success"


def test_retry_of_successful_job_is_allowed_but_resume_is_not(client, identity, fixed_dq):
    fixed_dq()
    p = create_pipeline(client, steps=[dp_step()])
    job = submit_and_start(client, p["pipelineId"])
    job = advance(client, job["jobId"])
    assert job["status"] == "success"

    assert client.post(f"/jobs/{job['jobId']}/resume").status_code == 409
    resp = client.post(f"/jobs/{job['jobId']}/retry")
    assert resp.status_code == 200
    assert resp.json()["runId"] == "RUN-0002"


def test_step_timeout_fails_the_job(client, identity, monkeypatch):
    p = create_pipeline(client, steps=[dp_step(), em_step()])
    job = submit_and_start(client, p["pipelineId"])

    monkeypatch.setattr(settings, "STEP_TIMEOUT_SECONDS", 0)
    job = advance(client, job["jobId"])
    assert job["status"] == "failed"
    assert "timed out" in job["steps"][0]["errorMessage"]


def test_audit_trail_covers_job_lifecycle(client, identity, fixed_dq):
    fixed_dq()
    p = create_pipeline(client, steps=[dp_step()])
    job = submit_and_start(client, p["pipelineId"])
    advance(client, job["jobId"])

    actions = {e["action"] for e in client.get("/audit?pageSize=100").json()["items"]}
    assert {"pipeline.create", "job.create", "job.start"} <= actions
