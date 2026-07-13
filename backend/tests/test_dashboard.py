"""GET /dashboard/summary aggregation."""
from tests.conftest import advance, create_pipeline, dp_step, em_step, submit_and_start


def test_summary_counts_emr_steps_by_status(client, identity):
    p = create_pipeline(client, steps=[dp_step(), em_step()])
    job = submit_and_start(client, p["pipelineId"])
    advance(client, job["jobId"])

    summary = client.get("/dashboard/summary").json()
    assert summary["emr"]["total"] == 1
    assert summary["emr"]["byStatus"]["succeeded"] == 1


def test_summary_includes_emr_application_stats(client, identity):
    apps = client.get("/dashboard/summary").json()["emr"]["applications"]
    assert len(apps) == 1
    app = apps[0]
    assert app["tenantId"] == "acme"
    assert app["applicationId"] == "mock-emr-acme"
    assert app["state"] == "STARTED"
    assert app["runningJobRuns"] == 0
    assert app["queuedJobRuns"] == 0
    assert app["maxVcpu"] == 400
    assert app["allocatedVcpuEstimate"] == 0
    assert app["utilizationPct"] == 0


def test_summary_emr_application_counts_running_and_queued(client, identity):
    # Job 1: its execute_model step starts immediately -> running.
    running = create_pipeline(client, steps=[em_step()], name="running-em")
    submit_and_start(client, running["pipelineId"])
    # Job 2: data_pipeline runs first, so its execute_model step is idle on
    # an active job -> queued.
    queued = create_pipeline(client, steps=[dp_step(), em_step()], name="queued-em")
    submit_and_start(client, queued["pipelineId"])

    app = client.get("/dashboard/summary").json()["emr"]["applications"][0]
    assert app["runningJobRuns"] == 1
    assert app["queuedJobRuns"] == 1
    assert app["allocatedVcpuEstimate"] == 4
    assert app["utilizationPct"] == 1  # 4 of 400 vCPU


def test_summary_survives_one_broken_emr_application(client, identity, monkeypatch):
    """A deleted/throttled EMR application degrades to a missing row, never
    a 500 for the whole dashboard."""
    from app.services.emr_execution_service import MockEmrExecutionService

    def _boom(self, application_id):
        raise RuntimeError("application not found")

    monkeypatch.setattr(MockEmrExecutionService, "get_application", _boom)
    resp = client.get("/dashboard/summary")
    assert resp.status_code == 200, resp.text
    assert resp.json()["emr"]["applications"] == []
