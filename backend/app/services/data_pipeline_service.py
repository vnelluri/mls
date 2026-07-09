"""
Data pipeline step execution (Snowflake -> S3 unload) -- mock/real split
selected by SNOWFLAKE_MODE.

Interface mirrors emr_execution_service (start / get_status / cancel): a real
unload can run for minutes or hours, so the step is poll-driven — start()
kicks the query off and returns its id; every refresh pass polls get_status()
until a terminal state. No thread blocks while the query runs, and the query
id (like an EMR run id) is persisted on the job step, so polling survives
process restarts and works from any API task.

States surfaced by get_status use the same vocabulary as the EMR service so
job_service can drive both step types identically:
    RUNNING (any non-terminal Snowflake status) / SUCCESS / FAILED / CANCELLED
On SUCCESS the result carries an `output` dict for the step
({"rowsWritten": ..., "s3Uri": ...}).

MockDataPipelineService is a PURE in-process simulation (no moto, no
Snowflake): elapsed wall-clock time since the step started drives the state
machine — RUNNING until STEP_DURATION_SECONDS, then SUCCESS with a
deterministic row count derived from the query id.

RealDataPipelineService executes
    COPY INTO 's3://...' FROM "DB"."SCHEMA"."TABLE"
    STORAGE_INTEGRATION = <name> FILE_FORMAT = (TYPE = PARQUET) ...
asynchronously (execute_async -> sfqid) and polls get_query_status. S3 access
is via a Snowflake STORAGE INTEGRATION — no AWS credentials ever appear in
SQL. database/schema/table/warehouse come from the step's `snowflakeParams`
JSON object (app.schemas.pipeline.DataPipelineConfig) and are validated
against a strict identifier pattern before being quoted into the statement:
config is authored by authenticated Lead Data Scientists, but SQL injection
must be structurally impossible regardless.

This module only runs when the step's config has NO `scriptS3Uri` — a
data_pipeline step that sets one is EMR-backed instead (the script replaces
this unload entirely) and is driven by emr_execution_service via
job_service._resolve_data_pipeline_script_config, never by this module.
"""
import abc
import hashlib
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

TERMINAL_STATES = {"SUCCESS", "FAILED", "CANCELLED"}

# Unquoted-style Snowflake identifiers only (letters, digits, _, $; must not
# start with a digit). Anything else is rejected rather than escaped.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
# Destination is embedded in single quotes; allow the safe S3-URI alphabet.
_S3_URI_RE = re.compile(r"^s3://[A-Za-z0-9._\-]+(/[A-Za-z0-9._\-/=]*)?$")


def validate_real_config() -> None:
    """Fail fast at startup when SNOWFLAKE_MODE=real is misconfigured —
    a half-configured connector would otherwise surface as every
    data_pipeline step failing at runtime."""
    missing = []
    if not settings.SNOWFLAKE_ACCOUNT:
        missing.append("SNOWFLAKE_ACCOUNT")
    if not settings.SNOWFLAKE_USER:
        missing.append("SNOWFLAKE_USER")
    if not (settings.SNOWFLAKE_PRIVATE_KEY or settings.SNOWFLAKE_PASSWORD):
        missing.append("SNOWFLAKE_PRIVATE_KEY (or SNOWFLAKE_PASSWORD)")
    if not settings.SNOWFLAKE_STORAGE_INTEGRATION:
        missing.append("SNOWFLAKE_STORAGE_INTEGRATION")
    if missing:
        raise RuntimeError(
            f"SNOWFLAKE_MODE=real requires these settings: {', '.join(missing)}"
        )
    try:
        import snowflake.connector  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "SNOWFLAKE_MODE=real requires the snowflake-connector-python package"
        ) from exc


def _require_identifier(value: Optional[str], field: str) -> str:
    if not value or not _IDENTIFIER_RE.match(value):
        raise ValueError(
            f"{field} '{value}' is not a valid Snowflake identifier "
            "(letters, digits, _ and $ only, must not start with a digit)"
        )
    return value


def build_unload_sql(step_config: dict) -> str:
    """The COPY INTO statement for one data_pipeline step (no-script mode
    only — DataPipelineConfig requires database/schema/table/warehouse
    inside snowflakeParams whenever scriptS3Uri is unset). Raises ValueError
    on any identifier/URI that fails validation."""
    params = step_config.get("snowflakeParams") or {}
    database = _require_identifier(params.get("database"), "snowflakeParams.database")
    schema = _require_identifier(params.get("schema"), "snowflakeParams.schema")
    table = _require_identifier(params.get("table"), "snowflakeParams.table")
    integration = _require_identifier(
        settings.SNOWFLAKE_STORAGE_INTEGRATION, "SNOWFLAKE_STORAGE_INTEGRATION"
    )
    destination = step_config["destinationS3Uri"].rstrip("/") + "/"
    if not _S3_URI_RE.match(destination):
        raise ValueError(f"destinationS3Uri '{destination}' is not a plain s3:// URI")

    # OVERWRITE: the destination prefix is a staging area the downstream
    # execute_model step reads as its inputS3Uri; each run replaces it.
    return (
        f"COPY INTO '{destination}'\n"
        f'FROM "{database}"."{schema}"."{table}"\n'
        f"STORAGE_INTEGRATION = {integration}\n"
        f"FILE_FORMAT = (TYPE = PARQUET)\n"
        f"HEADER = TRUE\n"
        f"OVERWRITE = TRUE"
    )


class DataPipelineService(abc.ABC):
    @abc.abstractmethod
    def start(self, step_config: dict) -> dict:
        """Kick off the unload; returns {"queryId": str}."""
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


class MockDataPipelineService(DataPipelineService):
    def start(self, step_config: dict) -> dict:
        return {"queryId": "mock-sf-" + uuid.uuid4().hex[:12]}

    def get_status(
        self, query_id: str, started_at_iso: Optional[str] = None, step_config: Optional[dict] = None
    ) -> dict:
        if not started_at_iso:
            return {"state": "RUNNING", "stateDetail": "Not yet started"}
        if _elapsed_seconds(started_at_iso) < settings.STEP_DURATION_SECONDS:
            return {"state": "RUNNING", "stateDetail": "Unloading Snowflake table (mock)"}
        # Deterministic per query id, so repeated polls agree on the output.
        digest = int(hashlib.md5(query_id.encode("utf-8")).hexdigest(), 16)
        rows_written = 1000 + digest % 49000
        return {
            "state": "SUCCESS",
            "stateDetail": "Mock unload completed",
            "output": {
                "rowsWritten": rows_written,
                "s3Uri": (step_config or {}).get("destinationS3Uri"),
            },
        }

    def cancel(self, query_id: str, step_config: Optional[dict] = None) -> None:
        # Nothing to cancel — a cancelled step simply stops being polled.
        return None


class RealDataPipelineService(DataPipelineService):
    """Live Snowflake -> S3 extraction via an asynchronous COPY INTO."""

    def _connect(self, step_config: Optional[dict] = None):
        import snowflake.connector

        kwargs = {
            "account": settings.SNOWFLAKE_ACCOUNT,
            "user": settings.SNOWFLAKE_USER,
            # The platform polls/cancels queries it started; nothing here
            # needs an interactive session.
            "client_session_keep_alive": False,
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
        """Key-pair auth (the standard for service accounts): the PEM arrives
        via SSM SecureString -> env var; the connector wants DER."""
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
        sql = build_unload_sql(step_config)
        conn = self._connect(step_config)
        try:
            cursor = conn.cursor()
            cursor.execute_async(sql)
            params = step_config.get("snowflakeParams") or {}
            logger.info("Started Snowflake unload %s: %s.%s.%s -> %s",
                        cursor.sfqid, params.get("database"),
                        params.get("schema"), params.get("table"),
                        step_config["destinationS3Uri"])
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
                # Raises ProgrammingError with the query's actual error text
                # on failure — far more actionable than a bare status name.
                status = conn.get_query_status_throw_if_error(query_id)
            except ProgrammingError as exc:
                return {"state": "FAILED", "stateDetail": f"Snowflake query failed: {exc}"}

            if conn.is_still_running(status):
                return {"state": "RUNNING", "stateDetail": f"Snowflake query {status.name}"}
            if status.name in ("ABORTING", "ABORTED"):
                return {"state": "CANCELLED", "stateDetail": "Snowflake query was cancelled"}
            if status.name != "SUCCESS":
                return {"state": "FAILED", "stateDetail": f"Snowflake query ended in {status.name}"}

            output = {"s3Uri": (step_config or {}).get("destinationS3Uri")}
            try:
                # COPY INTO <location> reports (rows_unloaded, input_bytes,
                # output_bytes). Best-effort: the unload succeeded either way.
                cursor = conn.cursor()
                cursor.get_results_from_sfqid(query_id)
                row = cursor.fetchone()
                if row:
                    output["rowsWritten"] = int(row[0])
            except Exception:
                logger.warning("Could not fetch unload row count for query %s", query_id)
            return {"state": "SUCCESS", "stateDetail": "Unload completed", "output": output}
        finally:
            conn.close()

    def cancel(self, query_id: str, step_config: Optional[dict] = None) -> None:
        conn = self._connect()
        try:
            conn.cursor().execute("SELECT SYSTEM$CANCEL_QUERY(%s)", (query_id,))
        finally:
            conn.close()


def get_data_pipeline_service() -> DataPipelineService:
    if settings.SNOWFLAKE_MODE == "real":
        return RealDataPipelineService()
    return MockDataPipelineService()
