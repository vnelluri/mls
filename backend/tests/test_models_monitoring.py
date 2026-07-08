"""Model registry (stages, gates, baselines) and monitoring (snapshots,
derived status, review closure, trend)."""
import pytest

from app.config import settings
from app.repositories import model_repo
from app.services import monitoring_service
from app.services.psi import compute_psi, psi_for_baseline
from tests.conftest import (
    advance,
    approval_step,
    create_pipeline,
    dp_step,
    dq_step,
    em_step,
    promote_model,
    register_model,
    submit_and_start,
)

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_register_model_defaults(client, identity):
    m = register_model(client, version="2.1.0")
    assert m["stage"] == "None"
    assert m["currentMonitoringStatus"] == "NotStarted"
    assert m["version"] == "2.1.0"


def test_duplicate_registration_conflicts(client, identity):
    register_model(client)
    resp = client.post("/models", json={
        "modelName": "scorer", "modelId": "MDL-SCORER", "version": "1",
        "framework": "xgboost", "artifactS3Uri": "s3://m/a",
    })
    assert resp.status_code == 409


def test_version_format_validated(client, identity):
    resp = client.post("/models", json={
        "modelName": "bad", "modelId": "MDL-BAD", "version": "1#2",
        "framework": "xgboost", "artifactS3Uri": "s3://m/a",
    })
    assert resp.status_code == 422


def test_drift_baseline_shape_validated(client, identity):
    resp = client.post("/models", json={
        "modelName": "bad", "modelId": "MDL-BAD", "version": "1",
        "framework": "xgboost", "artifactS3Uri": "s3://m/a",
        "driftBaseline": {"f1": {"bins": [0, 1, 2], "proportions": [0.9, 0.9]}},
    })
    assert resp.status_code == 422  # proportions must sum to ~1


def test_stage_transitions(client, identity):
    register_model(client)
    # Illegal: None -> Production.
    resp = client.patch("/models/scorer/1/promote", json={"targetStage": "Production"})
    assert resp.status_code == 409

    assert promote_model(client, "scorer", "1", "Staging")["stage"] == "Staging"
    prod = promote_model(client, "scorer", "1", "Production")
    assert prod["stage"] == "Production"
    assert prod["promotedBy"] == "test-user"
    assert promote_model(client, "scorer", "1", "Archived")["stage"] == "Archived"
    # Archived is terminal.
    resp = client.patch("/models/scorer/1/promote", json={"targetStage": "Staging"})
    assert resp.status_code == 409


def test_monitoring_gate_blocks_production_promotion(client, identity):
    register_model(client)
    promote_model(client, "scorer", "1", "Staging")
    model_repo.update_monitoring_status("acme", "scorer", "1", "Failed")

    resp = client.patch("/models/scorer/1/promote", json={"targetStage": "Production"})
    assert resp.status_code == 409
    assert "monitoring" in resp.json()["detail"]

    # Rework (acknowledged warning) does not block.
    model_repo.update_monitoring_status("acme", "scorer", "1", "Rework")
    assert promote_model(client, "scorer", "1", "Production")["stage"] == "Production"


# ---------------------------------------------------------------------------
# Monitoring pipeline integration
# ---------------------------------------------------------------------------

def _run_monitored_job(client, steps=None):
    p = create_pipeline(client, steps=steps or [dp_step(), em_step(), dq_step()])
    job = submit_and_start(client, p["pipelineId"])
    return advance(client, job["jobId"])


def test_snapshot_recorded_once_per_run_and_updates_model(client, identity, fixed_dq):
    fixed_dq(errorRate=0.01)
    register_model(client)
    job = _run_monitored_job(client)
    assert job["status"] == "success"

    snaps = client.get("/monitoring/snapshots?modelName=scorer").json()
    assert snaps["total"] == 1
    snap = snaps["items"][0]
    assert snap["jobId"] == job["jobId"]
    assert snap["derivedStatus"] == "Passed"

    model = client.get("/models/scorer/1").json()
    assert model["currentMonitoringStatus"] == "Passed"
    assert model["lastSnapshotAt"] == snap["recordedAt"]

    trend = client.get("/monitoring/models/scorer/1/trend").json()
    assert trend["total"] == 1


def test_monitoring_failure_fails_the_job(client, identity, fixed_dq):
    fixed_dq(errorRate=0.5)  # >= errorRateFail (0.15)
    register_model(client)
    job = _run_monitored_job(client)

    assert job["status"] == "failed"
    dq = next(s for s in job["steps"] if s["type"] == "data_quality_check")
    assert "error rate" in dq["errorMessage"]
    assert client.get("/models/scorer/1").json()["currentMonitoringStatus"] == "Failed"


def test_rework_review_closure_approve_means_passed(client, identity, fixed_dq):
    fixed_dq(errorRate=0.06)  # warn zone: Rework
    register_model(client)
    job = _run_monitored_job(client, steps=[dp_step(), em_step(), dq_step(), approval_step()])

    # The warning-zone run reached the approval gate: model is under review.
    assert job["status"] == "awaiting_approval"
    assert client.get("/models/scorer/1").json()["currentMonitoringStatus"] == "InReview"

    gate = next(s for s in job["steps"] if s["type"] == "approval")
    client.post(f"/jobs/{job['jobId']}/steps/{gate['stepId']}/approve")
    assert client.get("/models/scorer/1").json()["currentMonitoringStatus"] == "Passed"


def test_rework_review_closure_reject_means_rework(client, identity, fixed_dq):
    fixed_dq(errorRate=0.06)
    register_model(client)
    job = _run_monitored_job(client, steps=[dp_step(), em_step(), dq_step(), approval_step()])
    assert client.get("/models/scorer/1").json()["currentMonitoringStatus"] == "InReview"

    gate = next(s for s in job["steps"] if s["type"] == "approval")
    client.post(f"/jobs/{job['jobId']}/steps/{gate['stepId']}/reject")
    assert client.get("/models/scorer/1").json()["currentMonitoringStatus"] == "Rework"


def test_monitoring_dashboard_counts(client, identity, fixed_dq):
    fixed_dq()
    register_model(client)
    register_model(client, name="other")
    _run_monitored_job(client)

    counts = client.get("/monitoring/dashboard").json()["counts"]
    assert counts["Passed"] == 1
    assert counts["NotStarted"] == 1


# ---------------------------------------------------------------------------
# Pure logic units
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "max_psi,error_rate,dq_passed,expected",
    [
        (0.01, 0.01, True, "Passed"),
        (0.10, 0.01, True, "Rework"),   # psi warn boundary is inclusive
        (0.01, 0.05, True, "Rework"),   # error-rate warn boundary
        (0.25, 0.01, True, "Failed"),   # psi fail boundary
        (0.01, 0.15, True, "Failed"),   # error-rate fail boundary
        (0.01, 0.01, False, "Failed"),  # raw DQ failure always fails
    ],
)
def test_derive_status_matrix(max_psi, error_rate, dq_passed, expected):
    thresholds = {"psiWarn": 0.10, "psiFail": 0.25, "errorRateWarn": 0.05, "errorRateFail": 0.15}
    assert monitoring_service.derive_status(max_psi, error_rate, dq_passed, thresholds) == expected


def test_per_model_overrides_replace_only_fail_thresholds():
    t = monitoring_service.resolve_thresholds({"driftThresholdOverride": 0.5})
    assert t["psiFail"] == 0.5
    assert t["psiWarn"] == settings.PSI_WARN  # warn stays global
    assert t["errorRateFail"] == settings.ERROR_RATE_FAIL


def test_psi_zero_for_identical_distributions():
    assert compute_psi([0.25, 0.25, 0.25, 0.25], [0.25, 0.25, 0.25, 0.25]) == 0.0


def test_psi_positive_for_shifted_distribution_and_deterministic_seeding():
    assert compute_psi([0.5, 0.5], [0.9, 0.1]) > 0.2
    baseline = {"f": {"bins": [0, 1, 2, 3], "proportions": [0.3, 0.4, 0.3]}}
    assert psi_for_baseline(baseline, "seed-1") == psi_for_baseline(baseline, "seed-1")
    assert psi_for_baseline(baseline, "seed-1") != psi_for_baseline(baseline, "seed-2")
