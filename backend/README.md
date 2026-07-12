# Truist Model Serving (TMS) — Backend

Multi-tenant batch model-serving platform for a financial organization.
FastAPI + DynamoDB. A **Pipeline** is a reusable template of typed steps
(`data_pipeline` → `execute_model` → `data_quality_check` → optional
`approval` → optional `load_to_snowflake`); a **Job** is one execution of a
pipeline with per-step run state. When a data-quality-check step completes,
a **MonitoringSnapshot** is recorded and the model's denormalized monitoring
status updates. `load_to_snowflake`, when present, is always the pipeline's
LAST step — it publishes a run's scored output back into Snowflake only
after the quality gate, and any approval gate, have already passed.

## Quickstart (no Docker — this is the primary local path)

Requires Python 3.11+.

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt -r requirements-dev.txt
python scripts/dev.py
```

`scripts/dev.py` does everything: copies `.env.example` → `.env` on first run,
starts a local **moto** server (pure-Python DynamoDB emulator, port 5000),
creates all 7 tables, seeds demo data, then runs uvicorn on port 8000 with
`--reload`. Ctrl+C stops both processes.

- API: http://localhost:8000
- Interactive docs: http://localhost:8000/docs
- moto (DynamoDB emulator): http://localhost:5000

> **There is no EMR or Snowflake emulator — by design.** `EMR_MODE=mock`,
> `SNOWFLAKE_MODE=mock`, and `DQ_MODE=mock` select *pure in-process*
> simulations inside the API process itself. They are **not** routed through
> moto (moto does not meaningfully emulate `emr-serverless`, and no local
> Snowflake emulator exists at all). Don't go looking for a mock endpoint for
> any of them — only the DynamoDB moto server runs locally. The mock EMR run
> takes ~10 seconds of wall-clock time to reach a terminal state (`<3s`
> PENDING, `3–10s` RUNNING, `≥10s` SUCCESS/FAILED), so polling
> `GET /jobs/{id}` shows visible progress. See "Real execution modes" below
> for what `real` does for each switch.

## Roles & local role switching

Auth in local dev is synthetic (`AUTH_MODE=dev`): a fake user is built from
the `DEV_USER_*` vars in `.env`. **Env vars are read once at startup — after
editing `.env`, restart `scripts/dev.py`.**

| Role              | Scope       | Can do                                                                 | `DEV_USER_TENANT_ID`    |
|-------------------|-------------|------------------------------------------------------------------------|--------------------------|
| PlatformAdmin     | all tenants | View everything across tenants; tenant + group-mapping CRUD. **Never** creates/mutates tenant-scoped resources (has no tenant to write into — writes return 403). | ignored (forced `null`) |
| Operator          | all tenants | Cross-tenant job operations: view dashboard/jobs/monitoring in every tenant, **start/stop/retry/resume any job** (target tenant passed as `tenantId` query param) and trigger production pipelines. The **only** role that may stop/retry/resume **production** runs. No submissions, approvals, pipeline/model writes, or admin CRUD. | ignored (forced `null`) |
| LeadDataScientist | own tenant  | Everything tenant-scoped: create/update/archive/promote pipelines, submit/start/stop/retry/resume **staging** jobs, approve/reject steps, override failed steps, register/promote models, plus all reads. For **production** runs: may trigger the pipeline and **start** a pending job, but stop/retry/resume is Operator-only (the production escape hatch is overriding a failed step). | `acme-capital` or `blue-harbor-bank` |
| DataScientist     | own tenant  | All reads in own tenant, plus start/stop/retry/resume of the tenant's **staging** jobs. No submissions, approvals, pipeline/model writes, or production job operations — those return 403. | `acme-capital` or `blue-harbor-bank` |

A **suspended** tenant is enforced, not cosmetic: its users are rejected at
the identity layer (403 on every request), and tenantless callers (Operator,
the ESP trigger) cannot launch new runs into it (409) — though **stop** still
works, since shutting work down is what suspension wants.

Seeded demo tenants: `acme-capital`, `blue-harbor-bank` (plus a suspended
`old-north-trust`). Default dev identity: **LeadDataScientist @ acme-capital**.

In prod (`AUTH_MODE=prod`), identity comes from an Entra ID JWT and the
role/tenant are resolved **fresh on every request** — never cached. The
primary path is the **group-name convention**: the org's `tms-*` security
groups are AD-synced, so the token's `groups` claim carries their
`sAMAccountName` names (set the app registration's optional claim to emit
sAMAccountName, and emit only "groups assigned to the application" to stay
clear of the 200-group overage limit). Names resolve by parsing alone:

| Group name | Resolves to |
|---|---|
| `tms-platform-admin` | PlatformAdmin (tenantless) |
| `tms-platform-operator` | Operator (tenantless) |
| `tms-<tenant>-leaddatascientist` | LeadDataScientist @ `<tenant>` |
| `tms-<tenant>-datascientist` | DataScientist @ `<tenant>` |

The tenant slug in the group name must equal the platform `tenant_id`
exactly — that equality is the tenant-onboarding contract (creating the Entra
group *is* the role grant; no mapping-table seeding, no bootstrap problem).
Matching is case-insensitive, `DOMAIN\` qualifiers are stripped, the prefix
is configurable via `GROUP_NAME_PREFIX`, and a user in several groups gets
the highest-privilege match. Because resolution reads the token's claims,
a group-membership change takes effect at the next token refresh (≤ ~90 min)
rather than instantly — the price of claim-based resolution.

The `mlserv-group-mappings` table remains as the fallback for anything that
doesn't parse (group object IDs, non-convention groups) and is **required for
service principals**: app-only tokens carry no groups claim, so the ESP
scheduler is mapped by client ID through it (see below).
The service **refuses to start** in prod mode unless `ENTRA_JWKS_URL`,
`ENTRA_ISSUER` and an audience (`ENTRA_AUDIENCE` or `ENTRA_CLIENT_ID`) are
set — a blank value would silently disable that verification. Entra signing-key
rotation is handled by re-fetching the JWKS on an unknown `kid`
(rate-limited to once a minute).

## API summary

Every list endpoint returns `{"items": [...], "total": n, "page": n, "pageSize": n}` — never a bare array.

| Method & path | Role required | Notes |
|---|---|---|
| `GET /health` | none | liveness + `auditWriteFailures` (audit writes are best-effort by policy; a non-zero count means the audit trail has gaps — alarm on it or on the ERROR log line) |
| `GET /auth/me` | any mapped role | current user `{user_id, email, name, role, tenant_id}` |
| `POST /tenants`, `PATCH /tenants/{id}/suspend`, `.../reactivate` | PlatformAdmin | audit rows written under partition `PLATFORM` |
| `PUT /tenants/{id}/execution` | PlatformAdmin | the tenant's platform-managed execution resources: EMR application id, job execution role, entrypoint override, and `dataS3Prefix` (every pipeline S3 URI must live under it) |
| `GET /tenants`, `GET /tenants/{id}` | PlatformAdmin | admin console |
| `POST/GET/DELETE /group-mappings` | PlatformAdmin | Entra group → role/tenant mappings (fallback only: convention-named `tms-*` groups resolve by name; the table covers service principals and exceptions) |
| `POST /pipelines` | LeadDataScientist (own tenant) | steps validated as a discriminated union on `type` |
| `GET /pipelines`, `GET /pipelines/{id}` | any role (admin sees all tenants) | admin detail lookups pass `?tenant_id=` |
| `PATCH /pipelines/{id}` | LeadDataScientist | bumps `version` |
| `PATCH /pipelines/{id}/archive` | LeadDataScientist | |
| `POST /pipelines/{id}/trigger` | Operator or LeadDataScientist | machine-callable launch for the external scheduler — see below |
| `POST /jobs` | LeadDataScientist | body `{"pipeline_id": "pl-..."}`; snapshots pipeline version and steps; created `pending` (not started); 409 for an archived pipeline |
| `GET /jobs`, `GET /jobs/{id}` | any role | single-job GET refreshes EMR state and advances the cascade; list does not (a 30s background loop keeps lists fresh); tenantless roles pass `?tenantId=` on detail |
| `POST /jobs/{id}/start` | scientist roles or Operator | starts a `pending` job; production jobs: Operator or LeadDataScientist only |
| `POST /jobs/{id}/stop` | scientist roles or Operator | 409 unless pending/running/awaiting_approval; cancels the in-flight EMR run; production runs Operator-only; Operator passes `?tenantId=` |
| `POST /jobs/{id}/retry` | scientist roles or Operator | 409 unless failed/cancelled/success (a successful job may be rerun); archives the old run's step states into `runHistory` (last 10 runs keep full detail), resets all steps, mints new `run_id`; production runs Operator-only |
| `POST /jobs/{id}/resume` | scientist roles or Operator | 409 unless failed/cancelled; keeps completed steps, reruns the rest; production runs Operator-only |
| `POST /jobs/{id}/steps/{step_id}/override` | LeadDataScientist | marks a **failed** step succeeded (audited) so the run can proceed — the production escape hatch |
| `POST /jobs/{id}/steps/{step_id}/approve` / `.../reject` | LeadDataScientist | 409 unless job **and** step are `awaiting_approval`; tenant re-verified after fetch; approve advances the cascade (steps after the gate still run) |
| `POST /pipelines/{id}/promote` | LeadDataScientist | staging → production; requires a valid ServiceNow ticket and ≥1 successful run; activates a draft |
| `POST /models` | LeadDataScientist | registers next version; stage `"None"`, monitoring `NotStarted` |
| `POST /models/artifacts` | LeadDataScientist | multipart file upload into `S3_ARTIFACTS_BUCKET` under the tenant's `{tenant_id}/` prefix; returns the `artifactS3Uri` to register with |
| `GET /models`, `GET /models/{name}/{version}` | any role | |
| `PATCH /models/{name}/{version}/promote` | LeadDataScientist | body `{"targetStage": "Staging"}`; illegal transitions → 409 |
| `GET /monitoring/snapshots` | any role | filters: `modelName`, `version`; **no write endpoint exists** — snapshots are only created internally on DQ-step completion (in one transaction with the model's denormalized status) |
| `GET /monitoring/models/{name}/{version}/trend` | any role | snapshot history for one model version, newest first (drift/error-rate trend data); tenantless roles pass `?tenantId=` |
| `GET /monitoring/dashboard` | any role | model counts per monitoring status |
| `GET /audit` | any role | filters: `action`, `entityType`; admin pages cross-tenant by `date=YYYY-MM-DD` |

Legal model stage transitions (anything else is a 409):
`None → Staging`, `Staging → Production`, `Staging → Archived`, `Production → Archived`.

## External scheduler (ESP) integration

Scheduling lives entirely in the enterprise scheduler — the platform only
exposes a trigger. The scheduler's Entra **service principal** authenticates
with a client-credentials token; app-only tokens carry no `groups` claim, so
the principal is resolved by mapping its **client ID** (`appid`/`azp` claim)
through `mlserv-group-mappings` — create a mapping whose `group_id` is the app
registration's client ID with `role=Operator`.

```bash
# Trigger (idempotent: a retry with the same key returns the original job)
curl -s -X POST "http://localhost:8000/pipelines/pl-acmefrd01/trigger?tenantId=acme-capital" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: esp-run-0042" \
  -d '{ "externalRunId": "ESP-RUN-0042" }'

# Poll until status is terminal (success / failed / cancelled)
curl -s "http://localhost:8000/jobs/<jobId>?tenantId=acme-capital"
```

Only **active** pipelines whose model is **in Production** can be triggered
(draft/archived pipeline, or a model in any other stage → 409) — the
scheduler runs production workloads only; non-Production models are exercised
manually by Lead Data Scientists, and those jobs are marked
`runEnvironment: "staging"` (vs `"production"` when the model was in
Production at submit). The returned job carries `triggeredVia: "api"` and the
scheduler's `externalRunId` for cross-system lineage; both appear in the
audit log (`job.trigger`). In local dev, test the flow by setting
`DEV_USER_ROLE=Operator`.

## Drift baselines & PSI

`POST /models` optionally accepts a **`driftBaseline`** — per-feature
training-time distributions captured when the model was trained:

```json
"driftBaseline": {
  "credit_score": { "bins": [300, 580, 670, 740, 850], "proportions": [0.15, 0.30, 0.35, 0.20] }
}
```

`bins` are the n+1 bucket edges, `proportions` the n bucket masses (must sum
to ~1; validated at registration). With a baseline registered, the
data-quality step computes **real PSI** (`services/psi.py`):

```
PSI = Σ (actualᵢ − expectedᵢ) · ln(actualᵢ / expectedᵢ)
```

Locally (`DQ_MODE=mock`) there is no real scoring output to bin, so the
"current" distribution is a **deterministic, seeded simulation** derived from
the baseline (seed = tenant + job + run id — reruns reproduce the same
numbers); without a baseline, drift numbers stay fully synthetic (v1
behavior). With **`DQ_MODE=real`** the current distribution is the run's
actual parquet scoring output binned into the baseline's bucket edges — see
"Real execution modes" below. The DQ step's output records which path ran in
`driftComputation` (`psi_vs_baseline` | `synthetic` | `none`). Either way,
the resulting max PSI feeds the same warn/fail thresholds and the monitoring
→ approval closure below.

## Run-scoped data layout

Every run reads and writes its **own** S3 prefixes, resolved once when each
step starts and recorded on the step as `resolved` (the evidence of exactly
what the compute was told):

```
data_pipeline   unloads to  <destinationS3Uri>/<date>/<runId>/
execute_model   reads       the unload's ACTUAL prefix (not static config)
                writes to   <outputS3Uri>/<date>/<runId>/   (its resultsS3Prefix)
data_quality    inspects    the execute_model step's ACTUAL resultsS3Prefix
```

Reruns and concurrent jobs of one pipeline therefore never overwrite each
other, and the DQ evidence can never come from a stale or foreign run.

## Real execution modes

Each switch is independent; the app **fails fast at startup** if a real mode
is enabled without its required settings.

**`EMR_MODE=real`** — the execute_model step submits a Spark job run to the
tenant's EMR Serverless application. Which application, which job execution
role, and which entrypoint are **platform-managed**: a PlatformAdmin sets
them per tenant (`PUT /tenants/{id}/execution`; the entrypoint falls back to
the platform-wide `EMR_ENTRYPOINT_S3_URI`), and pipeline authors supplying
`emrApplicationId`/`executionRoleArn`/`entryPointS3Uri` get a 400 — letting
authors choose what their code runs as would be privilege escalation. The
step also requires its `(modelName, modelVersion)` to be **registered** (with
an `artifactS3Uri`) in the tenant's registry — validated at pipeline
create/update and again at run time. The submit contract (positional
arguments `model-name model-version artifact-s3-uri input-s3-uri
output-s3-uri`) is implemented by the reference entrypoint
**`emr/scoring_entrypoint.py`** — upload it to S3 per release; its docstring
documents the output contract the DQ engine relies on (all input columns
preserved + a prediction column, unscorable rows kept with NULL predictions).
Terraform: set `emr_application_arns` and `emr_execution_role_arns` (the task
role gets `iam:PassRole` conditioned to `emr-serverless.amazonaws.com`).

When a tenant's execution config includes **`dataS3Prefix`**, every S3 URI in
that tenant's pipelines must live under it (validated at pipeline
create/update) — combined with per-tenant execution roles, this is the
tenant-isolation boundary for data and compute.

**`SNOWFLAKE_MODE=real`** — the data_pipeline step runs a live, asynchronous
`COPY INTO 's3://…'` unload (parquet) from the table named in its
**`snowflakeParams`** JSON object (`{"database", "schema", "table",
"warehouse"}` — required keys when the step has no `scriptS3Uri`; extra keys
are accepted and unused). The step is **poll-driven exactly like
execute_model**: `start()` returns the Snowflake query id (persisted on the
step as `snowflakeQueryId`), each refresh pass polls it, stop/timeout
cancels it via `SYSTEM$CANCEL_QUERY`, and the four identifiers are strictly
validated — at pipeline authoring time *and* again before being quoted into
SQL. S3 access is granted Snowflake-side
through a **storage integration** (`SNOWFLAKE_STORAGE_INTEGRATION`) — no AWS
credentials in SQL.

**data_pipeline step, script mode** — setting **`scriptS3Uri`** on a
data_pipeline step REPLACES the built-in COPY INTO unload entirely: the
script is submitted to the tenant's EMR Serverless application exactly like
an execute_model run (same `emrJobRunId`/EMR polling/cancellation), with the
step's own `scriptS3Uri` as the entryPoint — unlike execute_model's EMR
fields, the script is author-supplied (it *is* the pipeline author's code,
so there's no registry artifact standing in for it; only the EMR
application/execution role stay platform-managed, resolved from the
tenant's execution config the same way). Its `entryPointArguments` contract:

```
snowflake-params-json   the step's snowflakeParams, JSON-encoded — opaque to
                         the platform, entirely up to the script to interpret
                         (e.g. connect via Snowpark for Python with its own
                         credentials/secrets lookup)
output-s3-uri            this run's own results prefix — the script MUST
                         write here; downstream steps read exactly this
                         step's `output.s3Uri`, the same key the built-in
                         unload path produces
```

`scriptS3Uri`, like `destinationS3Uri`, is validated under the tenant's
`dataS3Prefix` when one is set — put scripts under e.g.
`s3://<data-bucket>/<tenant_id>/scripts/…` so the tenant's EMR execution
role (already granted read/write across its own prefix) can read it with no
extra IAM changes.

**`load_to_snowflake` step** — the reverse of `data_pipeline`: loads a run's
scored output back into Snowflake via an asynchronous, transformation-based
`COPY INTO <table>` (poll-driven exactly like the unload —
`snowflakeQueryId`, stop/timeout cancellation, the works). Always the
pipeline's **last** step (`pipeline_service.CANONICAL_STEP_ORDER`) — a run
only reaches it once the quality gate, and any approval gate, have already
passed, so nothing unreviewed is ever published. Its `snowflakeParams` JSON
object requires the same `database`/`schema`/`table`/`warehouse` keys as the
unload (same identifier validation); there is **no author-supplied source
field and no script-override escape hatch** — the source is always resolved
at run time from the run's own execute_model output (the same
`resultsS3Prefix` the data_quality_check step inspects), so a load can never
be pointed at stale or foreign data. Every run **appends**, never
`OVERWRITE`.

Every loaded row also carries the platform's own **per-row lineage
columns** — `_TMS_RUN_ID` (VARCHAR) and `_TMS_LOAD_DATE` (DATE) — on top of
the query-level traceability the unload already has (the step's persisted
`snowflakeQueryId` plus the platform's audit log). To stamp these, the step
reads the run's own scored-output **column names** from one representative
parquet file (`snowflake_load_service._read_source_columns`, via `pyarrow`
— lazily imported and only required by tenants that actually use this step,
not a blanket `SNOWFLAKE_MODE=real` requirement) and builds an explicit
`COPY INTO <table> (col1, col2, ..., _TMS_RUN_ID, _TMS_LOAD_DATE) FROM
(SELECT $1['col1'], $1['col2'], ..., '<run>'::VARCHAR, '<date>'::DATE FROM
's3://...')` rather than a plain `MATCH_BY_COLUMN_NAME` load. Consequences:

- **The destination table MUST already have `_TMS_RUN_ID VARCHAR` and
  `_TMS_LOAD_DATE DATE` columns**, plus one column per preserved
  scored-output feature (matched by name — Snowflake's standard
  case-insensitive folding for plain identifiers, same forgiving behavior a
  `MATCH_BY_COLUMN_NAME` load would have given). A missing column fails the
  load loudly (Snowflake's own "invalid identifier" error, surfaced as the
  step's `errorMessage`) — never silently.
- A scored-output column literally named `_tms_run_id`/`_tms_load_date`
  (any case) is rejected at build time as a reserved-name collision.
- VARIANT → destination-column-type coercion during the load follows
  Snowflake's own casting rules — the platform doesn't introspect or
  validate the destination table's column types ahead of time.

Requires the service account's Snowflake role to additionally have
**INSERT** on the destination table (unloads only ever needed read) and the
Snowflake storage-integration IAM role to have **`s3:GetObject`** on the
data bucket (the `infra/data-plane` module grants this — `LoadObjects` in
`snowflake.tf`).

The platform connects as a single **service account** (`SNOWFLAKE_USER` +
key-pair auth, PEM via SSM SecureString; password fallback for non-prod) —
**users never connect to Snowflake** and no user identity or credential is
ever forwarded to it. Two consequences: (1) the Snowflake role granted to
that service account is the outer boundary of what ANY tenant's pipeline can
export — grant it read on exactly the schemas the platform serves, nothing
broader; (2) Snowflake's query history attributes every unload to the
service account, so the platform's audit log (job → step → `snowflakeQueryId`)
is the record tying an unload back to the human who triggered it. Requires
`SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, an auth method, and the storage
integration.

**`DQ_MODE=real`** — the data_quality_check step computes every number from
the run's actual scoring output: parquet files under the step's
`inputS3Uri`, read up to a `DQ_MAX_BYTES` budget (results are marked
`sampled` if files were skipped). Semantics: `requestCount` = rows scored;
`errorRate` = null fraction of the step's optional `predictionColumn` (unset
→ 0); `null_rate` checks measure the column named by the check (a missing
column **fails** the check); `row_count_delta` compares against the previous
run's row count from the model's latest snapshot (first run passes);
`schema_match` measures baseline features missing from the output columns;
drift is **real PSI** — actual values binned into the baseline's bucket
edges vs its stored proportions. No baseline → no drift numbers
(`driftComputation: "none"`): the real engine never fabricates evidence.
Unreadable/absent output **fails the step** — a run whose output cannot be
inspected must not pass its quality gate. The task role needs S3 read on the
scoring-output locations (`dq_s3_read_arns` in the Terraform module).

## Monitoring → approval closure

The derived monitoring status is not just a dashboard color — it drives the
job cascade and the registry:

- **`Failed`** (drift ≥ fail threshold, error rate ≥ fail threshold, or DQ
  checks failed) **fails the job** at the data-quality step, with the breach
  spelled out in the step's `errorMessage`. (Previously only raw DQ-check
  failures failed the run — a drift breach sailed through.)
- **`Rework`** (warning zone) advances the run, but if the pipeline has an
  **approval step**, reaching that gate flips the model's
  `currentMonitoringStatus` to **`InReview`** — a human is now reviewing the
  warning. **Approving** the step accepts the warning-zone metrics (model
  returns to `Passed`); **rejecting** sends it back (`Rework`). Both
  transitions are audited as `model.monitoring_status`.
- **Promotion gate:** `PATCH /models/{name}/{version}/promote` to
  `Production` returns **409** while the model's monitoring status is
  `Failed` or `InReview`. (`Rework` — an acknowledged warning — and
  `NotStarted` — no evidence yet — do not block.)

Monitoring `derivedStatus`: `Failed` if `maxPsi ≥ psiFail` OR `errorRate ≥
errorRateFail` OR DQ failed; else `Rework` if past either warn threshold; else
`Passed`. (`InReview` is reserved; `NotStarted` only ever appears as a model's
default before its first snapshot.) Defaults: psiWarn 0.10, psiFail 0.25,
errorRateWarn 0.05, errorRateFail 0.15 — env-var overridable; per-model
overrides replace only the *fail* thresholds.

## curl examples

```bash
# Who am I?
curl -s http://localhost:8000/auth/me | jq

# Pipelines in my tenant
curl -s "http://localhost:8000/pipelines?page=1&pageSize=10" | jq

# Submit a job for a seeded pipeline, then watch it progress (~10s EMR mock)
JOB=$(curl -s -X POST http://localhost:8000/jobs \
  -H 'Content-Type: application/json' \
  -d '{"pipeline_id": "pl-acmefrd01"}' | jq -r .job_id)
sleep 4;  curl -s http://localhost:8000/jobs/$JOB | jq '.status, [.steps[].status]'
sleep 8;  curl -s http://localhost:8000/jobs/$JOB | jq '.status, [.steps[].status]'

# Approve the seeded awaiting-approval job (as LeadDataScientist @ acme-capital)
curl -s -X POST http://localhost:8000/jobs/job-acmeappr1/steps/step-4/approve | jq .status

# Promote a model (Staging -> Production)
curl -s -X PATCH http://localhost:8000/models/fraud-detector/2/promote \
  -H 'Content-Type: application/json' -d '{"targetStage": "Production"}' | jq

# Monitoring + audit
curl -s http://localhost:8000/monitoring/snapshots | jq '.items[].derivedStatus'
curl -s http://localhost:8000/monitoring/dashboard | jq
curl -s "http://localhost:8000/audit?page=1&pageSize=20" | jq '.items[].action'
```

Full smoke test: `bash scripts/test-api.sh` (needs bash, curl, jq).

## Tests

```bash
cd backend
pytest            # ~70 tests, ~20s, no server or emulator process needed
```

The suite (`tests/`) runs DynamoDB **in-process** via moto's `mock_aws` —
it does not use the moto *server* that `scripts/dev.py` starts, and needs no
network or Docker. Timing is collapsed (`STEP_DURATION_SECONDS=0`, EMR mock
phases 0) so each `GET /jobs/{id}` advances exactly one step and full
pipeline runs take milliseconds. Roles are switched per test through the
dev-auth identity, and the data-quality step is monkeypatched deterministic
where a test needs a specific monitoring outcome (Passed / Rework / Failed).

Coverage focuses on the behavior that encodes policy: the step cascade and
its terminal states, EMR failure/timeout handling, approval + monitoring
review closure, stage-transition and promotion gates, ESP trigger gates and
idempotency, RBAC and cross-tenant isolation, tenant suspension, and the
repository-level concurrency guarantees (optimistic locking, conditional
creates, idempotent snapshots).

## Environment variables

See `.env.example` for the complete annotated list. Highlights:

| Var | Default | Purpose |
|---|---|---|
| `AUTH_MODE` | `dev` | `dev` = synthetic user; `prod` = Entra JWT validation |
| `GROUP_NAME_PREFIX` | `tms` | prefix of the convention group names (`<prefix>-platform-<role>`, `<prefix>-<tenant>-<role>`) |
| `DEV_USER_ROLE` / `DEV_USER_TENANT_ID` | `LeadDataScientist` / `acme-capital` | local identity (restart to apply) |
| `DDB_ENDPOINT_URL` | `http://localhost:5000` | moto in dev; leave empty for real AWS |
| `EMR_MODE` / `SNOWFLAKE_MODE` / `DQ_MODE` | `mock` | in-process simulations; `real` = EMR Serverless / live Snowflake unloads / S3-parquet DQ engine (see "Real execution modes") |
| `EMR_ENTRYPOINT_S3_URI` | empty | platform-wide default scoring entrypoint (per-tenant override via execution config) |
| `SNOWFLAKE_ACCOUNT/USER/PRIVATE_KEY/STORAGE_INTEGRATION` | empty | required when `SNOWFLAKE_MODE=real` (startup-validated) |
| `DQ_MAX_BYTES` | `536870912` | byte budget for reading scoring output in real DQ mode |
| `EMR_MOCK_FAILURE_RATE` | `0.0` | fraction of mock EMR runs that fail (decided once at start) |
| `PSI_WARN/PSI_FAIL/ERROR_RATE_WARN/ERROR_RATE_FAIL` | `0.10/0.25/0.05/0.15` | monitoring thresholds |
| `JOB_REFRESH_INTERVAL_SECONDS` | `30` | background EMR poll cadence |
| `STEP_DURATION_SECONDS` | `30` | mock-mode step runtime (data_quality_check timer; mock data_pipeline query duration) |
| `STEP_TIMEOUT_SECONDS` | `21600` | per-step runtime ceiling — a step past it is failed and its EMR run cancelled |
| `CORS_ALLOWED_ORIGINS` | localhost:3000,localhost:5173 | comma-separated |

## Troubleshooting

- **`UnicodeEncodeError` on Windows** — run via `python scripts/dev.py` (it
  forces UTF-8 for itself and every child process). If running scripts
  manually, set `PYTHONIOENCODING=utf-8` first.
- **Changed `.env` but nothing happened** — env vars load once at startup;
  restart `scripts/dev.py`.
- **`ResourceNotFoundException` table not found** — moto state is in-memory
  and empty on every start; always launch through `dev.py` (which re-creates
  and re-seeds) rather than starting uvicorn directly.
- **All writes return 403** — check `DEV_USER_ROLE`. PlatformAdmin cannot
  write tenant-scoped resources; DataScientist can only operate staging jobs
  (start/stop/retry/resume). Everything else needs LeadDataScientist with a
  `DEV_USER_TENANT_ID`. Also check the tenant isn't suspended — suspended
  tenants 403 on every request.
- **Job stuck in `running`** — execute_model completes when the EMR service
  (mock: ~10s) reports a terminal state; the other steps run for
  `STEP_DURATION_SECONDS` (30s) each. Either poll `GET /jobs/{id}` (refreshes
  synchronously) or wait for the 30s background loop. List endpoints
  deliberately never refresh inline. A step running past
  `STEP_TIMEOUT_SECONDS` is failed automatically.
- **Port 5000 or 8000 already in use** — stop the other process; moto's port
  is fixed in `dev.py`, uvicorn's in its launch args.

## Deploying to ECS (Fargate)

Provisioning is Terraform, two modules:

- **`../infra/data-plane/`** — the storage/compute the real execution modes
  run on: the data/models/platform S3 buckets, one EMR Serverless
  application + tenant-scoped job execution role **per tenant**, and the
  Snowflake storage-integration role. Its outputs feed the backend module
  and the per-tenant `PUT /tenants/{id}/execution` calls; its README has the
  Snowflake handshake and the tenant onboarding runbook.
- **`iac/`** — the app plane: the 7 DynamoDB tables + GSIs, execution/task
  IAM roles (least-privilege on the tables; EMR Serverless job-run +
  `iam:PassRole` permissions scoped to the data plane's per-tenant ARNs when
  `emr_mode = "real"`), and the Fargate task definition + service. See
  `iac/README.md` for the usage example and variables.

1. `terraform apply` the data-plane module (`tenant_ids` = your tenants) and
   upload `emr/scoring_entrypoint.py` to its `entrypoint_s3_uri` output.
2. Build & push the image (prod stage): `docker build --target prod -t mlserv-backend .` then tag/push to ECR.
3. Create the SSM parameters for the Entra settings (`/mlserv/entra-*`) and,
   for `SNOWFLAKE_MODE=real`, the Snowflake service-account settings — with
   `AUTH_MODE=prod` the app refuses to start unless they're set.
4. `terraform apply` the `iac/` module with your image, subnets, security
   groups, ALB target group, and the data-plane outputs
   (`emr_application_arns`, `emr_execution_role_arns`, `dq_s3_read_arns`,
   `EMR_ENTRYPOINT_S3_URI`).
5. As PlatformAdmin, enter each tenant's execution config
   (`PUT /tenants/{id}/execution`) from the data plane's `tenant_execution`
   output.
6. Point the frontend at the ALB and set `cors_allowed_origins` accordingly.

The Dockerfile is **CI/deploy only** — local development never needs it.

## Layout

```
app/
  main.py            FastAPI app, CORS, routers, 30s background job-refresh loop
  config.py          pydantic-settings (all env vars)
  auth/              entra.py (JWT), dev_auth.py, dependencies.py (require_role /
                     require_tenant_scoped_role), group_mapping.py
  schemas/           Pydantic models incl. PageEnvelope[T] and the StepConfig union
  db/client.py       boto3 factory (endpoint-aware) + float/Decimal boundary
  repositories/      pure DynamoDB CRUD per table
  services/          business logic; emr/data-pipeline/snowflake-load/data-quality mock-real splits
  routers/           HTTP endpoints
  core/              pagination + shared HTTP exceptions
emr/                 scoring_entrypoint.py — the reference EMR Serverless batch-scoring
                     job and the execute_model submit/output contract (upload to S3)
scripts/             dev.py (local orchestrator), create_tables.py, seed_demo_data.py, test-api.sh
tests/               pytest suite (in-process moto; see "Tests")
iac/                 Terraform module: DynamoDB tables, IAM, ECS service
```
