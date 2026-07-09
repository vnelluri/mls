"""load_to_snowflake: the pipeline's terminal step, loading a run's scored
output back into Snowflake. Covers pipeline-order/schema validation, the
publish-only-after-quality-and-approval-gates behavior, run-time source
resolution, real-mode SQL construction (including the per-row lineage
columns), and stop/cancel routing."""
import re
from io import BytesIO

import boto3
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from moto import mock_aws

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
    # runId/loadDate are what get stamped onto every loaded row in real mode
    # (RUN_ID_COLUMN / LOAD_DATE_COLUMN) — resolved once at step start.
    assert load["resolved"]["runId"] == job["runId"]
    assert load["output"]["runId"] == job["runId"]
    assert load["output"]["loadDate"] == load["resolved"]["loadDate"]


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
    assert resolved["sourceS3Uri"] == "s3://bucket/out/2026-01-01/RUN-0001/"
    # runId/loadDate are what build_load_sql stamps onto every loaded row
    # (RUN_ID_COLUMN / LOAD_DATE_COLUMN) -- resolved once here, at step
    # start, not re-derived per poll.
    assert resolved["runId"] == "RUN-0001"
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", resolved["loadDate"])


# ---- real-mode SQL construction (moto S3 + pyarrow schema read) ---------------

BUCKET = "scoring-out"
PREFIX = "features/2026-01-01/RUN-0001"
SOURCE_URI = f"s3://{BUCKET}/{PREFIX}"


def parquet_bytes(columns: dict) -> bytes:
    buf = BytesIO()
    pq.write_table(pa.table(columns), buf)
    return buf.getvalue()


@pytest.fixture()
def load_s3():
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


def put_scored_output(s3, columns: dict, key: str = f"{PREFIX}/part-000.parquet") -> None:
    s3.put_object(Bucket=BUCKET, Key=key, Body=parquet_bytes(columns))


def load_config(**overrides) -> dict:
    config = {
        "snowflakeParams": {
            "database": "ANALYTICS", "schema": "SCORING", "table": "PREDICTIONS", "warehouse": "WH_BATCH",
        },
        "sourceS3Uri": SOURCE_URI,
        "runId": "RUN-0007",
        "loadDate": "2026-07-08",
    }
    config.update(overrides)
    return config


def test_build_load_sql_reads_columns_and_stamps_lineage(monkeypatch, load_s3):
    monkeypatch.setattr(settings, "SNOWFLAKE_STORAGE_INTEGRATION", "S3_UNLOAD_INT")
    put_scored_output(load_s3, {"credit_score": [650], "prediction": [0.2]})

    sql = build_load_sql(load_config())
    assert (
        'COPY INTO "ANALYTICS"."SCORING"."PREDICTIONS" '
        "(credit_score, prediction, _TMS_RUN_ID, _TMS_LOAD_DATE)"
    ) in sql
    assert "$1['credit_score']" in sql
    assert "$1['prediction']" in sql
    assert "'RUN-0007'::VARCHAR" in sql
    assert "'2026-07-08'::DATE" in sql
    assert f"FROM '{SOURCE_URI}/'" in sql
    assert "STORAGE_INTEGRATION = S3_UNLOAD_INT" in sql
    # Loads always append -- never the unload's OVERWRITE semantics.
    assert "OVERWRITE" not in sql
    # Replaced by the explicit transformation + reserved lineage columns.
    assert "MATCH_BY_COLUMN_NAME" not in sql


def test_build_load_sql_quotes_non_identifier_column_names(monkeypatch, load_s3):
    monkeypatch.setattr(settings, "SNOWFLAKE_STORAGE_INTEGRATION", "S3_UNLOAD_INT")
    put_scored_output(load_s3, {"credit score": [650]})  # space -- not a plain identifier

    sql = build_load_sql(load_config())
    assert '"credit score"' in sql
    assert "$1['credit score']" in sql


def test_build_load_sql_reads_smallest_file_for_schema(monkeypatch, load_s3):
    # Multiple files in one run's output share the same schema (partitioned
    # output of the same Spark job); only the smallest needs downloading.
    monkeypatch.setattr(settings, "SNOWFLAKE_STORAGE_INTEGRATION", "S3_UNLOAD_INT")
    put_scored_output(load_s3, {"a": [1, 2, 3]}, key=f"{PREFIX}/part-000.parquet")
    put_scored_output(load_s3, {"a": [4]}, key=f"{PREFIX}/part-001.parquet")

    sql = build_load_sql(load_config())
    assert "$1['a']" in sql


def test_build_load_sql_no_parquet_files_raises(monkeypatch, load_s3):
    monkeypatch.setattr(settings, "SNOWFLAKE_STORAGE_INTEGRATION", "S3_UNLOAD_INT")
    load_s3.put_object(Bucket=BUCKET, Key=f"{PREFIX}/_SUCCESS", Body=b"")
    with pytest.raises(ValueError, match="No parquet files found"):
        build_load_sql(load_config())


def test_build_load_sql_rejects_reserved_column_collision(monkeypatch, load_s3):
    monkeypatch.setattr(settings, "SNOWFLAKE_STORAGE_INTEGRATION", "S3_UNLOAD_INT")
    put_scored_output(load_s3, {"_tms_run_id": [1]})
    with pytest.raises(ValueError, match="reserved"):
        build_load_sql(load_config())


def test_build_load_sql_requires_resolved_run_id_and_load_date(monkeypatch, load_s3):
    monkeypatch.setattr(settings, "SNOWFLAKE_STORAGE_INTEGRATION", "S3_UNLOAD_INT")
    with pytest.raises(ValueError, match="runId and loadDate"):
        build_load_sql(load_config(runId=None))


@pytest.mark.parametrize("field, value", [
    ("database", 'ANALYTICS"; DROP TABLE X; --'),
    ("table", "T'); SELECT 1"),
    ("table", ""),
])
def test_build_load_sql_rejects_invalid_identifiers(monkeypatch, field, value):
    monkeypatch.setattr(settings, "SNOWFLAKE_STORAGE_INTEGRATION", "S3_UNLOAD_INT")
    base = load_config()
    config = {**base, "snowflakeParams": {**base["snowflakeParams"], field: value}}
    with pytest.raises(ValueError, match="not a valid Snowflake identifier"):
        build_load_sql(config)


def test_build_load_sql_rejects_non_s3_source(monkeypatch):
    monkeypatch.setattr(settings, "SNOWFLAKE_STORAGE_INTEGRATION", "S3_UNLOAD_INT")
    config = load_config(sourceS3Uri="s3://bucket/bad'quote")
    with pytest.raises(ValueError, match="not a plain s3:// URI"):
        build_load_sql(config)
