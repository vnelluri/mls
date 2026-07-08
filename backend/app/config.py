"""
Application configuration via pydantic-settings.

All values are overridable via environment variables (or a `.env` file loaded
by python-dotenv / pydantic-settings). See `.env.example` at the repo root for
the full list with local-dev defaults.
"""
from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- Auth -----------------------------------------------------------
    AUTH_MODE: str = "dev"  # "dev" | "prod"

    # Dev-mode synthetic user (only used when AUTH_MODE == "dev")
    DEV_USER_ID: str = "dev-user-1"
    DEV_USER_EMAIL: str = "lead.ds@acme-demo.com"
    DEV_USER_NAME: str = "Dev LeadDataScientist"
    DEV_USER_ROLE: str = "LeadDataScientist"  # PlatformAdmin | LeadDataScientist | DataScientist
    DEV_USER_TENANT_ID: Optional[str] = "acme-capital"

    # Convention-based group resolution (prod path): Entra groups named
    # "<prefix>-platform-<role>" / "<prefix>-<tenant>-<role>" resolve to a
    # role/tenant by name alone, no mapping-table entry needed. Requires the
    # groups claim to carry NAMES — i.e. AD-synced groups with the app
    # registration's optional claim set to emit sAMAccountName.
    GROUP_NAME_PREFIX: str = "tms"

    # Entra ID (prod path)
    ENTRA_TENANT_ID: str = ""
    ENTRA_CLIENT_ID: str = ""
    ENTRA_JWKS_URL: str = ""
    ENTRA_ISSUER: str = ""
    ENTRA_AUDIENCE: str = ""

    # ---- AWS / DynamoDB ---------------------------------------------------
    AWS_REGION: str = "us-east-1"
    # moto in dev; unset/None in prod. Use 127.0.0.1 (NOT "localhost") -- on
    # Windows, "localhost" resolves to ::1 first and moto only binds IPv4, so
    # every boto3 request eats a ~2s IPv6 connect stall before falling back.
    DDB_ENDPOINT_URL: Optional[str] = "http://127.0.0.1:5000"
    AWS_ACCESS_KEY_ID: str = "test"
    AWS_SECRET_ACCESS_KEY: str = "test"

    # DynamoDB table names
    TABLE_TENANTS: str = "mlserv-tenants"
    TABLE_GROUP_MAPPINGS: str = "mlserv-group-mappings"
    TABLE_PIPELINES: str = "mlserv-pipelines"
    TABLE_JOBS: str = "mlserv-jobs"
    TABLE_MODELS: str = "mlserv-models"
    TABLE_MONITORING_SNAPSHOTS: str = "mlserv-monitoring-snapshots"
    TABLE_AUDIT: str = "mlserv-audit"

    # ---- Execution mode switches -----------------------------------------
    EMR_MODE: str = "mock"  # "mock" | "real"
    # Platform-wide default Spark scoring entrypoint (see backend/emr/).
    # Resolution order for an execute_model step: tenant execution config ->
    # this default. Pipeline authors never choose the entrypoint.
    EMR_ENTRYPOINT_S3_URI: str = ""
    SNOWFLAKE_MODE: str = "mock"  # "mock" | "real"
    DQ_MODE: str = "mock"  # "mock" | "real"
    EMR_MOCK_FAILURE_RATE: float = 0.0

    # ---- Snowflake connection (SNOWFLAKE_MODE=real only) -------------------
    # The platform connects as a single SERVICE ACCOUNT — users never connect
    # to Snowflake and no user identity/credential is forwarded to it. The
    # role granted to this account bounds what any tenant pipeline can export.
    SNOWFLAKE_ACCOUNT: str = ""
    SNOWFLAKE_USER: str = ""
    # Key-pair auth: PEM content, arriving as an SSM SecureString -> env var.
    # Password is the non-prod fallback.
    SNOWFLAKE_PRIVATE_KEY: str = ""
    SNOWFLAKE_PRIVATE_KEY_PASSPHRASE: str = ""
    SNOWFLAKE_PASSWORD: str = ""
    SNOWFLAKE_ROLE: str = ""
    # STORAGE INTEGRATION used by COPY INTO unloads — S3 access is granted
    # Snowflake-side; no AWS credentials ever appear in SQL.
    SNOWFLAKE_STORAGE_INTEGRATION: str = ""

    # ---- Data-quality engine (DQ_MODE=real only) ---------------------------
    # Byte budget for reading a run's scoring output from S3: files beyond
    # this are skipped (the computed stats note they were sampled), bounding
    # both memory and how long a DQ step can hold a refresh pass.
    DQ_MAX_BYTES: int = 512 * 1024 * 1024

    # ---- Monitoring thresholds (global defaults) --------------------------
    PSI_WARN: float = 0.10
    PSI_FAIL: float = 0.25
    ERROR_RATE_WARN: float = 0.05
    ERROR_RATE_FAIL: float = 0.15

    # ---- Background job refresh loop --------------------------------------
    JOB_REFRESH_INTERVAL_SECONDS: int = 30
    # Dummy job runner: how long each timer-driven pipeline step
    # (data_pipeline, data_quality_check) "executes" before it completes and
    # the next step starts. execute_model steps are NOT timer-driven -- they
    # complete when the EMR execution service reports a terminal state.
    STEP_DURATION_SECONDS: int = 30
    # Hard ceiling on any single step's runtime. A step still running past
    # this is failed (and its EMR run cancelled, best-effort) so a stuck
    # executor can never leave a job "running" forever.
    STEP_TIMEOUT_SECONDS: int = 6 * 3600

    # ---- CORS --------------------------------------------------------------
    CORS_ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ALLOWED_ORIGINS.split(",") if o.strip()]


settings = Settings()
