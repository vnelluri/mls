"""RealDataPipelineService unit tests.

The snowflake connector is faked at the module level (sys.modules) — no
network, no dependency on snowflake-connector-python being installed. What's
under test is OUR side of the contract: SQL construction and identifier
validation, status mapping to the shared RUNNING/SUCCESS/FAILED/CANCELLED
vocabulary, cancellation, and the fail-fast config validation.

Also covers the job-service integration of the poll-driven data_pipeline
step: the query id is persisted on the step, and stopping a job cancels the
in-flight query.
"""
import sys
import types
from typing import Optional

import pytest

from tests.conftest import create_pipeline, dp_step, submit_and_start

from app.config import settings
from app.services import data_pipeline_service as dps


# ---------------------------------------------------------------------------
# Fake snowflake connector
# ---------------------------------------------------------------------------

class FakeProgrammingError(Exception):
    pass


class FakeStatus:
    def __init__(self, name):
        self.name = name


class FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self.sfqid = "sf-query-001"

    def execute_async(self, sql):
        self._conn.executed_async.append(sql)

    def execute(self, sql, params=None):
        self._conn.executed.append((sql, params))

    def get_results_from_sfqid(self, query_id):
        self._conn.fetched_results_for = query_id

    def fetchone(self):
        return self._conn.copy_result_row


class FakeConnection:
    def __init__(self, **kwargs):
        self.connect_kwargs = kwargs
        self.executed_async = []
        self.executed = []
        self.copy_result_row = (12345, 999, 888)  # rows_unloaded, in/out bytes
        self.status: FakeStatus = FakeStatus("SUCCESS")
        self.status_error: Optional[Exception] = None
        self.fetched_results_for = None
        self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def get_query_status_throw_if_error(self, query_id):
        if self.status_error:
            raise self.status_error
        return self.status

    def is_still_running(self, status):
        return status.name in ("RUNNING", "QUEUED", "RESUMING_WAREHOUSE", "NO_DATA", "BLOCKED")

    def close(self):
        self.closed = True


@pytest.fixture()
def fake_snowflake(monkeypatch):
    """Install a fake snowflake.connector into sys.modules and configure the
    settings real mode needs. Returns the singleton FakeConnection every
    connect() hands out, so tests can inspect/steer it."""
    conn = FakeConnection()

    connector_mod = types.ModuleType("snowflake.connector")
    connector_mod.connect = lambda **kwargs: conn.__dict__.update(connect_kwargs=kwargs) or conn
    errors_mod = types.ModuleType("snowflake.connector.errors")
    errors_mod.ProgrammingError = FakeProgrammingError
    connector_mod.errors = errors_mod
    snowflake_mod = types.ModuleType("snowflake")
    snowflake_mod.connector = connector_mod

    monkeypatch.setitem(sys.modules, "snowflake", snowflake_mod)
    monkeypatch.setitem(sys.modules, "snowflake.connector", connector_mod)
    monkeypatch.setitem(sys.modules, "snowflake.connector.errors", errors_mod)

    monkeypatch.setattr(settings, "SNOWFLAKE_ACCOUNT", "myorg-myacct")
    monkeypatch.setattr(settings, "SNOWFLAKE_USER", "MLSERV_SVC")
    monkeypatch.setattr(settings, "SNOWFLAKE_PASSWORD", "hunter2")
    monkeypatch.setattr(settings, "SNOWFLAKE_STORAGE_INTEGRATION", "S3_UNLOAD_INT")
    return conn


CONFIG = {
    "sourceType": "snowflake",
    "snowflakeParams": {
        "database": "ANALYTICS",
        "schema": "SCORING",
        "table": "FEATURES_DAILY",
        "warehouse": "WH_BATCH",
    },
    "destinationS3Uri": "s3://scoring-in/features",
}


def _with_param(field: str, value) -> dict:
    """CONFIG with one snowflakeParams key overridden, for the invalid-
    identifier test matrix below."""
    return {**CONFIG, "snowflakeParams": {**CONFIG["snowflakeParams"], field: value}}


# ---------------------------------------------------------------------------
# SQL construction / validation
# ---------------------------------------------------------------------------

class TestBuildUnloadSql:
    def test_builds_copy_into_with_storage_integration(self, fake_snowflake):
        sql = dps.build_unload_sql(CONFIG)
        assert "COPY INTO 's3://scoring-in/features/'" in sql
        assert 'FROM "ANALYTICS"."SCORING"."FEATURES_DAILY"' in sql
        assert "STORAGE_INTEGRATION = S3_UNLOAD_INT" in sql
        assert "TYPE = PARQUET" in sql
        # No credentials may ever appear in the statement.
        assert "CREDENTIALS" not in sql.upper()

    @pytest.mark.parametrize("field, value", [
        ("database", 'ANALYTICS"; DROP TABLE X; --'),
        ("schema", "SCH EMA"),
        ("table", "T'); SELECT 1"),
        ("table", ""),
    ])
    def test_rejects_invalid_identifiers(self, fake_snowflake, field, value):
        config = _with_param(field, value)
        with pytest.raises(ValueError, match="not a valid Snowflake identifier"):
            dps.build_unload_sql(config)

    def test_rejects_non_s3_destination(self, fake_snowflake):
        config = {**CONFIG, "destinationS3Uri": "s3://bucket/bad'quote"}
        with pytest.raises(ValueError, match="not a plain s3:// URI"):
            dps.build_unload_sql(config)


# ---------------------------------------------------------------------------
# start / get_status / cancel
# ---------------------------------------------------------------------------

class TestRealService:
    def test_start_executes_async_and_returns_query_id(self, fake_snowflake):
        result = dps.RealDataPipelineService().start(CONFIG)
        assert result == {"queryId": "sf-query-001"}
        assert len(fake_snowflake.executed_async) == 1
        assert fake_snowflake.connect_kwargs["warehouse"] == "WH_BATCH"
        assert fake_snowflake.closed

    def test_start_uses_password_when_no_private_key(self, fake_snowflake):
        dps.RealDataPipelineService().start(CONFIG)
        assert fake_snowflake.connect_kwargs["password"] == "hunter2"
        assert "private_key" not in fake_snowflake.connect_kwargs

    def test_status_running(self, fake_snowflake):
        fake_snowflake.status = FakeStatus("RUNNING")
        status = dps.RealDataPipelineService().get_status("sf-query-001", None, CONFIG)
        assert status["state"] == "RUNNING"

    def test_status_success_carries_output_with_row_count(self, fake_snowflake):
        fake_snowflake.status = FakeStatus("SUCCESS")
        status = dps.RealDataPipelineService().get_status("sf-query-001", None, CONFIG)
        assert status["state"] == "SUCCESS"
        assert status["output"] == {"s3Uri": "s3://scoring-in/features", "rowsWritten": 12345}
        assert fake_snowflake.fetched_results_for == "sf-query-001"

    def test_status_success_without_result_row_still_succeeds(self, fake_snowflake):
        fake_snowflake.status = FakeStatus("SUCCESS")
        fake_snowflake.copy_result_row = None
        status = dps.RealDataPipelineService().get_status("sf-query-001", None, CONFIG)
        assert status["state"] == "SUCCESS"
        assert "rowsWritten" not in status["output"]

    def test_status_aborted_maps_to_cancelled(self, fake_snowflake):
        fake_snowflake.status = FakeStatus("ABORTED")
        status = dps.RealDataPipelineService().get_status("sf-query-001", None, CONFIG)
        assert status["state"] == "CANCELLED"

    def test_status_error_maps_to_failed_with_detail(self, fake_snowflake):
        fake_snowflake.status_error = FakeProgrammingError("Table FEATURES_DAILY does not exist")
        status = dps.RealDataPipelineService().get_status("sf-query-001", None, CONFIG)
        assert status["state"] == "FAILED"
        assert "does not exist" in status["stateDetail"]

    def test_cancel_issues_system_cancel_query_parameterized(self, fake_snowflake):
        dps.RealDataPipelineService().cancel("sf-query-001", CONFIG)
        (sql, params), = fake_snowflake.executed
        assert "SYSTEM$CANCEL_QUERY" in sql
        assert params == ("sf-query-001",)
        # The query id travels as a bind parameter, never spliced into SQL.
        assert "sf-query-001" not in sql


# ---------------------------------------------------------------------------
# Fail-fast config validation
# ---------------------------------------------------------------------------

class TestValidateRealConfig:
    def test_reports_every_missing_setting(self, monkeypatch):
        for var in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PRIVATE_KEY",
                    "SNOWFLAKE_PASSWORD", "SNOWFLAKE_STORAGE_INTEGRATION"):
            monkeypatch.setattr(settings, var, "")
        with pytest.raises(RuntimeError) as exc:
            dps.validate_real_config()
        message = str(exc.value)
        assert "SNOWFLAKE_ACCOUNT" in message
        assert "SNOWFLAKE_USER" in message
        assert "SNOWFLAKE_PRIVATE_KEY" in message
        assert "SNOWFLAKE_STORAGE_INTEGRATION" in message

    def test_passes_when_complete(self, fake_snowflake):
        dps.validate_real_config()  # must not raise


# ---------------------------------------------------------------------------
# Job-service integration (mock executor, poll-driven step)
# ---------------------------------------------------------------------------

class TestJobIntegration:
    def test_step_records_query_id_and_output(self, client, identity):
        pipeline = create_pipeline(client, steps=[dp_step()])
        job = submit_and_start(client, pipeline["pipelineId"])
        step = job["steps"][0]
        assert step["status"] == "running"
        assert step["snowflakeQueryId"].startswith("mock-sf-")

        job = client.get(f"/jobs/{job['jobId']}").json()
        step = job["steps"][0]
        assert job["status"] == "success"
        assert step["status"] == "succeeded"
        # The unload destination is run-scoped at step start:
        # <destinationS3Uri>/<date>/<runId>/ — reruns never overwrite.
        assert step["output"]["s3Uri"].startswith("s3://bucket/in/")
        assert step["output"]["s3Uri"].endswith(f"/{job['runId']}/")
        assert step["output"]["rowsWritten"] > 0

    def test_stop_cancels_inflight_query(self, client, identity, monkeypatch):
        cancelled = []
        monkeypatch.setattr(
            dps.MockDataPipelineService,
            "cancel",
            lambda self, query_id, step_config=None: cancelled.append(query_id),
        )
        pipeline = create_pipeline(client, steps=[dp_step()])
        job = submit_and_start(client, pipeline["pipelineId"])
        query_id = job["steps"][0]["snowflakeQueryId"]

        resp = client.post(f"/jobs/{job['jobId']}/stop")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"
        assert cancelled == [query_id]
