"""Pipeline CRUD, shape validation, and the promotion gates."""
from tests.conftest import (
    approval_step,
    create_pipeline,
    dp_step,
    dq_step,
    em_step,
    promote_pipeline,
    run_pipeline_to_success,
)


def test_create_pipeline_defaults(client, identity):
    p = create_pipeline(client, steps=[dp_step(), em_step(), dq_step(), approval_step()])
    assert p["status"] == "draft"
    assert p["environment"] == "staging"
    assert p["version"] == 1
    assert [s["type"] for s in p["steps"]] == [
        "data_pipeline", "execute_model", "data_quality_check", "approval",
    ]
    assert [s["stepId"] for s in p["steps"]] == ["step-1", "step-2", "step-3", "step-4"]


def test_step_shape_approval_must_be_last(client, identity):
    resp = client.post(
        "/pipelines",
        json={"name": "bad", "steps": [dp_step(), approval_step(), dq_step()]},
    )
    assert resp.status_code == 400
    assert "order" in resp.json()["detail"]


def test_step_shape_no_duplicate_types(client, identity):
    resp = client.post("/pipelines", json={"name": "bad", "steps": [dp_step(), dp_step()]})
    assert resp.status_code == 400
    assert "at most one" in resp.json()["detail"]


def test_step_shape_depends_on_must_reference_earlier_step(client, identity):
    step = dp_step()
    step["dependsOn"] = ["step-99"]
    resp = client.post("/pipelines", json={"name": "bad", "steps": [step]})
    assert resp.status_code == 400
    assert "dependsOn" in resp.json()["detail"]


def test_step_shape_unique_step_ids(client, identity):
    s1, s2 = dp_step(), em_step()
    s1["step_id"] = s2["step_id"] = "dup"
    resp = client.post("/pipelines", json={"name": "bad", "steps": [s1, s2]})
    assert resp.status_code == 400
    assert "unique" in resp.json()["detail"]


def test_blank_dq_check_name_rejected(client, identity):
    bad_dq = dq_step()
    bad_dq["config"]["checks"][0]["name"] = "  "
    resp = client.post("/pipelines", json={"name": "bad", "steps": [bad_dq]})
    assert resp.status_code == 400


def test_update_bumps_version(client, identity):
    p = create_pipeline(client)
    resp = client.patch(f"/pipelines/{p['pipelineId']}", json={"name": "renamed"})
    assert resp.status_code == 200
    assert resp.json()["version"] == 2
    assert resp.json()["name"] == "renamed"


def test_archived_pipeline_rejects_new_jobs(client, identity):
    p = create_pipeline(client)
    assert client.patch(f"/pipelines/{p['pipelineId']}/archive").status_code == 200
    resp = client.post("/jobs", json={"pipeline_id": p["pipelineId"]})
    assert resp.status_code == 409
    assert "archived" in resp.json()["detail"]


def test_promote_requires_valid_servicenow_ticket(client, identity):
    p = create_pipeline(client)
    resp = client.post(
        f"/pipelines/{p['pipelineId']}/promote", json={"service_now_ticket": "not-a-ticket"}
    )
    assert resp.status_code == 400


def test_promote_requires_a_successful_run(client, identity):
    p = create_pipeline(client)
    resp = client.post(
        f"/pipelines/{p['pipelineId']}/promote", json={"service_now_ticket": "CHG0031245"}
    )
    assert resp.status_code == 409
    assert "successful" in resp.json()["detail"]


def test_promote_happy_path_activates_draft_and_stamps(client, identity):
    pipeline, _job = run_pipeline_to_success(client)
    # The success run stamped the pipeline (promotion reads the stamp).
    assert client.get(f"/pipelines/{pipeline['pipelineId']}").json()["lastSuccessfulRunAt"]

    promoted = promote_pipeline(client, pipeline["pipelineId"])
    assert promoted["environment"] == "production"
    assert promoted["status"] == "active"  # promotion is the go-live decision
    assert promoted["serviceNowTicket"] == "CHG0031245"

    # Idempotence guard: already in production.
    resp = client.post(
        f"/pipelines/{pipeline['pipelineId']}/promote", json={"service_now_ticket": "CHG0031246"}
    )
    assert resp.status_code == 409


def test_archived_pipeline_cannot_be_promoted(client, identity):
    pipeline, _job = run_pipeline_to_success(client)
    client.patch(f"/pipelines/{pipeline['pipelineId']}/archive")
    resp = client.post(
        f"/pipelines/{pipeline['pipelineId']}/promote", json={"service_now_ticket": "CHG0031245"}
    )
    assert resp.status_code == 409
