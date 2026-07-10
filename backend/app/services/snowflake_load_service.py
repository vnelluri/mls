"""
Snowflake load step execution (S3 -> Snowflake) -- mock/real split selected
by SNOWFLAKE_MODE (the same switch that governs the extract/unload step in
data_pipeline_service; both are "how does the platform talk to Snowflake"
and share one fail-fast startup validation, data_pipeline_service.
validate_real_config).

Interface mirrors data_pipeline_service / emr_execution_service (start /
get_status / cancel): a real load can run for minutes, so the step is
poll-driven -- start() kicks the query off and returns its id; every
refresh pass polls get_status() until a terminal state.

States surfaced by get_status use the same vocabulary as the other
executors: RUNNING (any non-terminal Snowflake status) / SUCCESS / FAILED /
CANCELLED. On SUCCESS the result carries an `output` dict for the step
({"table": "DB.SCHEMA.TABLE", "rowsLoaded": ...}).

MockSnowflakeLoadService is a PURE in-process simulation (no moto, no
Snowflake, no pyarrow): elapsed wall-clock time since the step started
drives the state machine, mirroring MockDataPipelineService exactly.

RealSnowflakeLoadService executes a data-load TRANSFORMATION -- a SELECT
against the run's staged output rather than a bare COPY INTO -- so it can
append two platform-owned columns to every row alongside the scored output:

    COPY INTO "DB"."SCHEMA"."TABLE" (col1, col2, ..., _TMS_RUN_ID, _TMS_LOAD_DATE)
    FROM ( SELECT $1['col1'], $1['col2'], ..., 'RUN-0007'::VARCHAR, '2026-07-08'::DATE
           FROM 's3://...' )
    STORAGE_INTEGRATION = <name> FILE_FORMAT = (TYPE = PARQUET)

`col1, col2, ...` are read from the run's OWN staged parquet output
(_read_source_columns, via pyarrow -- lazily imported and only required
when a load_to_snowflake step actually runs; SNOWFLAKE_MODE=real does not
blanket-require pyarrow for tenants that never use this step). Column names
are read once per load, not author-configured, so the SELECT list always
matches whatever the execute_model step actually produced.

_TMS_RUN_ID (VARCHAR) and _TMS_LOAD_DATE (DATE) are the platform's own
per-row lineage columns -- every loaded row carries the run that produced it
and the date it was loaded, on top of the existing query-level traceability
(the step's persisted `snowflakeQueryId` + the platform's audit log, job ->
step -> snowflakeQueryId, tying a load back to the human who triggered it).
**The destination table MUST already have both columns** (plain, unquoted
DDL: `_TMS_RUN_ID VARCHAR`, `_TMS_LOAD_DATE DATE`) -- COPY INTO's explicit
column list means a missing column fails the load loudly (a clear Snowflake
"invalid identifier" error surfaced as the step's errorMessage), never
silently.

Column-name quoting: the SELECT list's `$1['name']` bracket access is a
STRING LITERAL and must match the parquet file's field name EXACTLY
(case-sensitive) -- single quotes are escaped by doubling, never
interpolated raw, since scored-output column names come from the tenant's
own scoring script, not the platform. The destination column LIST is
emitted UNQUOTED whenever a name is a plain identifier (letters/digits/_/$),
so Snowflake's standard case-insensitive uppercase folding matches whatever
case the destination table was actually created with -- the same forgiving
behavior a plain `MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE` load would have
provided. A column name that isn't plain-identifier-safe falls back to a
double-quoted (escaped), case-SENSITIVE reference instead: the destination
table would then need that exact quoted name. Snowflake's own VARIANT ->
typed-column coercion rules apply when the load actually happens; an
incompatible destination column type fails the load with Snowflake's own
error text, not a platform-level check (the platform doesn't introspect the
destination table).

Every run APPENDS -- there is no OVERWRITE here, unlike the unload;
Snowflake also tracks COPY INTO <table> load history per staged file path
for 64 days and will not silently reload an already-loaded file, an extra
safety net on top of each run's source prefix already being unique.

database/schema/table/warehouse come from the step's `snowflakeParams` JSON
object (app.schemas.pipeline.LoadToSnowflakeConfig) and are validated
against the same strict identifier pattern as the unload before being
quoted into SQL.

This module only runs for load_to_snowflake steps -- always the pipeline's
LAST step (pipeline_service.CANONICAL_STEP_ORDER), so a run only ever
reaches it once the quality gate, and any approval gate, have already
passed.
"""
import abc
import hashlib
import logging
import re
import uuid
from datetime import datetime, timezone
from io import BytesIO
from typing import List, Optional, Tuple

from app.config import settings

logger = logging.getLogger(__name__)

TERMINAL_STATES = {"SUCCESS", "FAILED", "CANCELLED"}

# Same pattern as data_pipeline_service._IDENTIFIER_RE -- unquoted-style
# Snowflake identifiers only. Anything else is rejected rather than escaped.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_S3_URI_RE = re.compile(r"^s3://[A-Za-z0-9._\-]+(/[A-Za-z0-9._\-/=]*)?$")

# Platform-owned per-row lineage columns -- must already exist on every
# load_to_snowflake destination table (see module docstring).
RUN_ID_COLUMN = "_TMS_RUN_ID"
LOAD_DATE_COLUMN = "_TMS_LOAD_DATE"


def _require_identifier(value: Optional[str], field: str) -> str:
    if not value or not _IDENTIFIER_RE.match(value):
        raise ValueError(
            f"{field} '{value}' is not a valid Snowflake identifier "
            "(letters, digits, _ and $ only, must not start with a digit)"
        )
    return value


def _qualified_table(step_config: dict) -> str:
    params = step_config.get("snowflakeParams") or {}
    return f"{params.get('database')}.{params.get('schema')}.{params.get('table')}"


def _quote_string_literal(value: str) -> str:
    """Standard SQL single-quote escaping (doubling). Used for both the
    VARIANT field-name literals in the SELECT list and the run id embedded
    as a column value."""
    return "'" + value.replace("'", "''") + "'"


def _destination_column_ref(name: str) -> str:
    """How one scored-output column name is referenced in the destination
    COPY INTO column list: UNQUOTED when it's a plain identifier (Snowflake
    folds it to uppercase the same way for both the DDL and this DML, so it
    matches the destination table regardless of the case the parquet file
    happened to use -- the same forgiving matching MATCH_BY_COLUMN_NAME
    would have given); a non-plain name falls back to a double-quoted,
    case-SENSITIVE reference (escaped) instead."""
    if _IDENTIFIER_RE.match(name):
        return name
    return '"' + name.replace('"', '""') + '"'


def _parse_s3_uri(uri: str) -> Tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ValueError(f"sourceS3Uri '{uri}' is not an s3:// URI")
    bucket, _, prefix = uri[len("s3://"):].partition("/")
    if not bucket:
        raise ValueError(f"sourceS3Uri '{uri}' has no bucket")
    return bucket, prefix


def _read_source_columns(source_s3_uri: str) -> List[str]:
    """The column names of the run's staged scoring output, read from ONE
    representative parquet file under the prefix (every file in a run's
    output shares the same schema -- partitioned output of the same Spark
    job) -- the smallest, to minimize the transfer. pyarrow is imported
    lazily here, not required for SNOWFLAKE_MODE=real in general: only a
    pipeline that actually uses load_to_snowflake pays for it.

    Raises ValueError with no parquet files under the prefix -- a load with
    nothing to introspect must fail loudly, the same philosophy as the real
    DQ engine's "no scoring output to check"."""
    import boto3
    import pyarrow.parquet as pq

    bucket, prefix = _parse_s3_uri(source_s3_uri)
    s3 = boto3.client("s3", region_name=settings.AWS_REGION)

    objects: List[dict] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        objects.extend(page.get("Contents", []))
    parquet_objects = [o for o in objects if o["Key"].endswith(".parquet")]
    if not parquet_objects:
        raise ValueError(
            f"No parquet files found under {source_s3_uri} — nothing to load"
        )

    smallest = min(parquet_objects, key=lambda o: o["Size"])
    body = s3.get_object(Bucket=bucket, Key=smallest["Key"])["Body"].read()
    schema = pq.read_schema(BytesIO(body))
    return list(schema.names)


def build_load_sql(step_config: dict) -> str:
    """The transformation-based COPY INTO <table> statement for one
    load_to_snowflake step -- reads the run's own scored-output columns
    (_read_source_columns) and appends RUN_ID_COLUMN / LOAD_DATE_COLUMN to
    every row. `sourceS3Uri`, `runId`, `loadDate` are job_service-resolved
    fields (never author-supplied). Raises ValueError on any
    identifier/URI/column-name collision that fails validation."""
    params = step_config.get("snowflakeParams") or {}
    database = _require_identifier(params.get("database"), "snowflakeParams.database")
    schema = _require_identifier(params.get("schema"), "snowflakeParams.schema")
    table = _require_identifier(params.get("table"), "snowflakeParams.table")
    integration = _require_identifier(
        settings.SNOWFLAKE_STORAGE_INTEGRATION, "SNOWFLAKE_STORAGE_INTEGRATION"
    )
    source = step_config["sourceS3Uri"].rstrip("/") + "/"
    if not _S3_URI_RE.match(source):
        raise ValueError(f"sourceS3Uri '{source}' is not a plain s3:// URI")
    run_id = step_config.get("runId")
    load_date = step_config.get("loadDate")
    if not run_id or not load_date:
        raise ValueError("runId and loadDate must be resolved before building the load SQL")

    columns = _read_source_columns(source)
    collisions = [c for c in columns if c.upper() in (RUN_ID_COLUMN, LOAD_DATE_COLUMN)]
    if collisions:
        raise ValueError(
            f"Scored output already has column(s) {collisions} that collide with the "
            f"platform's reserved {RUN_ID_COLUMN}/{LOAD_DATE_COLUMN} lineage columns"
        )

    dest_columns = [_destination_column_ref(c) for c in columns] + [RUN_ID_COLUMN, LOAD_DATE_COLUMN]
    select_list = [f"$1[{_quote_string_literal(c)}]" for c in columns] + [
        f"{_quote_string_literal(run_id)}::VARCHAR",
        f"{_quote_string_literal(load_date)}::DATE",
    ]

    return (
        f'COPY INTO "{database}"."{schema}"."{table}" ({", ".join(dest_columns)})\n'
        f"FROM (\n"
        f"    SELECT {', '.join(select_list)}\n"
        f"    FROM '{source}'\n"
        f")\n"
        f"STORAGE_INTEGRATION = {integration}\n"
        f"FILE_FORMAT = (TYPE = PARQUET)"
    )


class SnowflakeLoadService(abc.ABC):
    @abc.abstractmethod
    def start(self, step_config: dict) -> dict:
        """Kick off the load; returns {"queryId": str}."""
        ...

    @abc.abstractmethod
    def get_status(
        self, query_id: str, started_at_iso: Optional[str] = None, step_config: Optional[dict] = None
    ) -> dict:
        """{"state": ..., "stateDetail": ..., "output": {...} on SUCCESS}."""
        ...

    @abc.abstractmethod
    def cancel(self, query_id: str, step_config: Optional[dict] = None) -> None:
        """Best-effort cancellation of a running query (stop_job / timeout)."""
        ...


def _elapsed_seconds(started_at_iso: str) -> float:
    started_at = datetime.fromisoformat(started_at_iso)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - started_at).total_seconds()


class MockSnowflakeLoadService(SnowflakeLoadService):
    def start(self, step_config: dict) -> dict:
        return {"queryId": "mock-sfload-" + uuid.uuid4().hex[:12]}

    def get_status(
        self, query_id: str, started_at_iso: Optional[str] = None, step_config: Optional[dict] = None
    ) -> dict:
        if not started_at_iso:
            return {"state": "RUNNING", "stateDetail": "Not yet started"}
        if _elapsed_seconds(started_at_iso) < settings.STEP_DURATION_SECONDS:
            return {"state": "RUNNING", "stateDetail": "Loading into Snowflake (mock)"}
        # Deterministic per query id, so repeated polls agree on the output.
        digest = int(hashlib.md5(query_id.encode("utf-8")).hexdigest(), 16)
        rows_loaded = 1000 + digest % 49000
        config = step_config or {}
        return {
            "state": "SUCCESS",
            "stateDetail": "Mock load completed",
            "output": {
                "rowsLoaded": rows_loaded,
                "table": _qualified_table(config),
                "runId": config.get("runId"),
                "loadDate": config.get("loadDate"),
            },
        }

    def cancel(self, query_id: str, step_config: Optional[dict] = None) -> None:
        # Nothing to cancel — a cancelled step simply stops being polled.
        return None


class RealSnowflakeLoadService(SnowflakeLoadService):
    """Live S3 -> Snowflake load via an asynchronous, transformation-based
    COPY INTO <table> (see module docstring for the RUN_ID_COLUMN /
    LOAD_DATE_COLUMN lineage columns)."""

    def _connect(self, step_config: Optional[dict] = None):
        import snowflake.connector

        kwargs = {
            "account": settings.SNOWFLAKE_ACCOUNT,
            "user": settings.SNOWFLAKE_USER,
            "client_session_keep_alive": False,
            # Bounds a hung connect/poll so it can't stall the shared refresh
            # loop (or a synchronous GET /jobs/{id} request) indefinitely.
            "login_timeout": settings.SNOWFLAKE_LOGIN_TIMEOUT_SECONDS,
            "network_timeout": settings.SNOWFLAKE_NETWORK_TIMEOUT_SECONDS,
        }
        if settings.SNOWFLAKE_ROLE:
            kwargs["role"] = settings.SNOWFLAKE_ROLE
        if step_config:
            params = step_config.get("snowflakeParams") or {}
            kwargs["warehouse"] = _require_identifier(
                params.get("warehouse"), "snowflakeParams.warehouse"
            )
        if settings.SNOWFLAKE_PRIVATE_KEY:
            kwargs["private_key"] = self._private_key_der()
        else:
            kwargs["password"] = settings.SNOWFLAKE_PASSWORD
        return snowflake.connector.connect(**kwargs)

    @staticmethod
    def _private_key_der() -> bytes:
        from cryptography.hazmat.primitives import serialization

        passphrase = settings.SNOWFLAKE_PRIVATE_KEY_PASSPHRASE or None
        key = serialization.load_pem_private_key(
            settings.SNOWFLAKE_PRIVATE_KEY.encode("utf-8"),
            password=passphrase.encode("utf-8") if passphrase else None,
        )
        return key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

    def start(self, step_config: dict) -> dict:
        sql = build_load_sql(step_config)
        conn = self._connect(step_config)
        try:
            cursor = conn.cursor()
            cursor.execute_async(sql)
            logger.info(
                "Started Snowflake load %s: %s -> %s (run %s)",
                cursor.sfqid, step_config["sourceS3Uri"], _qualified_table(step_config),
                step_config.get("runId"),
            )
            return {"queryId": cursor.sfqid}
        finally:
            conn.close()

    def get_status(
        self, query_id: str, started_at_iso: Optional[str] = None, step_config: Optional[dict] = None
    ) -> dict:
        from snowflake.connector.errors import ProgrammingError

        conn = self._connect()
        try:
            try:
                status = conn.get_query_status_throw_if_error(query_id)
            except ProgrammingError as exc:
                return {"state": "FAILED", "stateDetail": f"Snowflake query failed: {exc}"}

            if conn.is_still_running(status):
                return {"state": "RUNNING", "stateDetail": f"Snowflake query {status.name}"}
            if status.name in ("ABORTING", "ABORTED"):
                return {"state": "CANCELLED", "stateDetail": "Snowflake query was cancelled"}
            if status.name != "SUCCESS":
                return {"state": "FAILED", "stateDetail": f"Snowflake query ended in {status.name}"}

            config = step_config or {}
            output = {
                "table": _qualified_table(config),
                "runId": config.get("runId"),
                "loadDate": config.get("loadDate"),
            }
            try:
                # COPY INTO <table> returns ONE ROW PER LOADED FILE:
                # (file, status, rows_parsed, rows_loaded, ...) -- sum
                # rows_loaded (index 3) across every file for the run's
                # total. Best-effort: the load succeeded either way.
                cursor = conn.cursor()
                cursor.get_results_from_sfqid(query_id)
                rows = cursor.fetchall()
                if rows:
                    output["rowsLoaded"] = sum(
                        int(row[3]) for row in rows if len(row) > 3 and row[3] is not None
                    )
            except Exception:
                logger.warning("Could not fetch load row count for query %s", query_id)
            return {"state": "SUCCESS", "stateDetail": "Load completed", "output": output}
        finally:
            conn.close()

    def cancel(self, query_id: str, step_config: Optional[dict] = None) -> None:
        conn = self._connect()
        try:
            conn.cursor().execute("SELECT SYSTEM$CANCEL_QUERY(%s)", (query_id,))
        finally:
            conn.close()


def get_snowflake_load_service() -> SnowflakeLoadService:
    if settings.SNOWFLAKE_MODE == "real":
        return RealSnowflakeLoadService()
    return MockSnowflakeLoadService()
