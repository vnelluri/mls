"""load_to_snowflake: the pipeline's terminal step, loading a run's scored
output back into Snowflake. Covers pipeline-order/schema validation, the
publish-only-after-quality-and-approval-gates behavior, run-time source
resolution, real-mode SQL construction, and stop/cancel routing."""
import pytest

from app.config import settings
from app.services.job_service import _resolve_load_to_snowflake_config
from app.services.snowflake_load_service import build_load_sql
from tests.conftest import (
    advance,
    approval_step,
    create_pipeline,
    dp_step,
    dq_step,
    em_step,
    load_step,
    submit_and_start,
)


# ---- pipeline shape / schema validation --------------------------------------

def test_load_step_must_be_last(client, identity):
    resp = client.post(
        "/pipelines",
        json={"name": "bad", "steps": [load_step(), dp_step()]},
    )
    assert resp.status_code == 400
    assert "order" in resp.json()["detail"]


def test_load_step_allowed_after_approval(client, identity):
    pipeline = create_pipeline(
        client, steps=[dp_step(), em_step(), dq_step(), approval_step(), load_step()]
    )
    assert [s["type"] for s in pipeline["steps"]] == [
        "data_pipeline", "execute_model", "data_quality_check", "approval", "load_to_snowflake",
    ]


def test_load_step_allowed_with_no_approval_step(client, identity):
    create_pipeline(client, steps=[dp_step(), em_step(), dq_step(), load_step()])


def test_load_step_snowflake_params_missing_keys_rejected(client, identity):
    step = load_step()
    del step["config"]["snowflakeParams"]["warehouse"]
    resp = client.post("/pipelines", json={"name": "bad", "steps": [step]})
    assert resp.status_code == 400
    assert "warehouse" in resp.json()["detail"]


def test_load_step_snowflake_params_invalid_identifier_rejected(client, identity):
    step = load_step()
    step["config"]["snowflakeParams"]["table"] = "T'); DROP TABLE X; --"
    resp = client.post("/pipelines", json={"name": "bad", "steps": [step]})
    assert resp.status_code == 400
    assert "identifier" in resp.json()["detail"]


# ---- publish-only-after-gates behavior, end to end (mock executors) ---------

def test_load_step_runs_immediately_after_dq_when_no_approval_gate(client, identity, fixed_dq):
    fixed_dq()
    pipeline = create_pipeline(client, steps=[dp_step(), em_step(), dq_step(), load_step()])
    job = submit_and_start(client, pipeline["pipelineId"])
    job = advance(client, job["jobId"])
    assert job["status"] == "success", job

    load = next(s for s in job["steps"] if s["type"] == "load_to_snowflake")
    assert load["status"] == "succeeded"
    assert load["output"]["table"] == "DB.SCH.RESULTS"
    assert load["output"]["rowsLoaded"] > 0
    # Sourced from the run's own execute_model output, resolved at start —
    # never author-configurable (LoadToSnowflakeConfig has no source field).
    em = next(s for s in job["steps"] if s["type"] == "execute_model")
    assert load["resolved"]["sourceS3Uri"] == em["output"]["resultsS3Prefix"]


def test_load_step_waits_for_human_approval(client, identity, fixed_dq):
    fixed_dq()
    pipeline = create_pipeline(
        client, steps=[dp_step(), em_step(), dq_step(), approval_step(), load_step()]
    )
    job = submit_and_start(client, pipeline["pipelineId"])
    job = advance(client, job["jobId"])
    assert job["status"] == "awaiting_approval", job

    load = next(s for s in job["steps"] if s["type"] == "load_to_snowflake")
    assert load["status"] == "idle"  # never touches Snowflake before a human approves

    gate = next(s for s in job["steps"] if s["type"] == "approval")
    resp = client.post(f"/jobs/{job['jobId']}/steps/{gate['stepId']}/approve")
    assert resp.status_code == 200, resp.text
    # Approving starts the load (poll-driven) rather than completing inline.
    assert resp.json()["status"] == "running"

    job = advance(client, job["jobId"])
    assert job["status"] == "success", job
    load = next(s for s in job["steps"] if s["type"] == "load_to_snowflake")
    assert load["status"] == "succeeded"


def test_failed_dq_never_reaches_load_step(client, identity, fixed_dq):
    fixed_dq(dataQualityPassed=False)
    pipeline = create_pipeline(client, steps=[dp_step(), em_step(), dq_step(), load_step()])
    job = submit_and_start(client, pipeline["pipelineId"])
    job = advance(client, job["jobId"])
    assert job["status"] == "failed", job

    load = next(s for s in job["steps"] if s["type"] == "load_to_snowflake")
    assert load["status"] == "idle"  # the cascade never reached it


def test_stop_cancels_inflight_load_query_not_unload(client, identity, monkeypatch, fixed_dq):
    from app.services import data_pipeline_service as dps
    from app.services import snowflake_load_service as sls

    fixed_dq()
    unload_cancelled = []
    load_cancelled = []
    monkeypatch.setattr(
        dps.MockDataPipelineService, "cancel",
        lambda self, query_id, step_config=None: unload_cancelled.append(query_id),
    )
    monkeypatch.setattr(
        sls.MockSnowflakeLoadService, "cancel",
        lambda self, query_id, step_config=None: load_cancelled.append(query_id),
    )
    pipeline = create_pipeline(client, steps=[dp_step(), em_step(), dq_step(), load_step()])
    job = submit_and_start(client, pipeline["pipelineId"])

    # Poll one GET at a time: a step the cascade starts mid-pass isn't
    # eligible to complete until the NEXT refresh (job_service's livelock
    # guard), so the very GET that flips load_to_snowflake to "running" is
    # guaranteed to still show it running -- stop right there, before
    # issuing another GET that would complete it.
    load = None
    for _ in range(25):
        job = client.get(f"/jobs/{job['jobId']}").json()
        load = next(s for s in job["steps"] if s["type"] == "load_to_snowflake")
        if load["status"] == "running" or job["status"] in ("success", "failed", "cancelled"):
            break
    assert load["status"] == "running", job
    query_id = load["snowflakeQueryId"]

    resp = client.post(f"/jobs/{job['jobId']}/stop")
    assert resp.status_code == 200, resp.text
    assert load_cancelled == [query_id]
    assert unload_cancelled == []


# ---- run-time resolution ------------------------------------------------------

def _job_item(steps, run_id="RUN-0001"):
    return {"tenant_id": "acme", "job_id": "job-1", "run_id": run_id, "steps": steps}


def test_resolution_requires_upstream_execute_model_output():
    step = {"step_id": "step-1", "type": "load_to_snowflake", "config": load_step()["config"]}
    with pytest.raises(RuntimeError) as exc:
        _resolve_load_to_snowflake_config(_job_item([step]), step)
    assert "execute_model" in str(exc.value)


def test_resolution_uses_execute_model_results_prefix():
    exec_step = {
        "step_id": "step-1", "type": "execute_model", "config": {},
        "output": {"resultsS3Prefix": "s3://bucket/out/2026-01-01/RUN-0001/"},
    }
    load = {"step_id": "step-2", "type": "load_to_snowflake", "config": load_step()["config"]}
    resolved = _resolve_load_to_snowflake_config(_job_item([exec_step, load]), load)
    assert resolved == {"sourceS3Uri": "s3://bucket/out/2026-01-01/RUN-0001/"}


# ---- real-mode SQL construction ------------------------------------------------

CONFIG = {
    "snowflakeParams": {"database": "ANALYTICS", "schema": "SCORING", "table": "PREDICTIONS", "warehouse": "WH_BATCH"},
    "sourceS3Uri": "s3://scoring-out/features/2026-01-01/RUN-0001/",
}


def test_build_load_sql(monkeypatch):
    monkeypatch.setattr(settings, "SNOWFLAKE_STORAGE_INTEGRATION", "S3_UNLOAD_INT")
    sql = build_load_sql(CONFIG)
    assert 'COPY INTO "ANALYTICS"."SCORING"."PREDICTIONS"' in sql
    assert "FROM 's3://scoring-out/features/2026-01-01/RUN-0001/'" in sql
    assert "STORAGE_INTEGRATION = S3_UNLOAD_INT" in sql
    assert "MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE" in sql
    # Loads always append -- never the unload's OVERWRITE semantics.
    assert "OVERWRITE" not in sql


@pytest.mark.parametrize("field, value", [
    ("database", 'ANALYTICS"; DROP TABLE X; --'),
    ("table", "T'); SELECT 1"),
    ("table", ""),
])
def test_build_load_sql_rejects_invalid_identifiers(monkeypatch, field, value):
    monkeypatch.setattr(settings, "SNOWFLAKE_STORAGE_INTEGRATION", "S3_UNLOAD_INT")
    config = {**CONFIG, "snowflakeParams": {**CONFIG["snowflakeParams"], field: value}}
    with pytest.raises(ValueError, match="not a valid Snowflake identifier"):
        build_load_sql(config)


def test_build_load_sql_rejects_non_s3_source(monkeypatch):
    monkeypatch.setattr(settings, "SNOWFLAKE_STORAGE_INTEGRATION", "S3_UNLOAD_INT")
    config = {**CONFIG, "sourceS3Uri": "s3://bucket/bad'quote"}
    with pytest.raises(ValueError, match="not a plain s3:// URI"):
        build_load_sql(config)
