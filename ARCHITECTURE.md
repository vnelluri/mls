# TMS Architecture

Truist Model Serving (TMS) is a multi-tenant platform for **batch ML scoring**:
tenants author pipelines that pull data out of Snowflake, score it on EMR
Serverless with a registered model, quality-check the output, and load results
back into Snowflake — with role-based access, promotion governance, monitoring
evidence, and a full audit trail. There is no realtime scoring in the MVP.

```
                        ┌──────────────────────────────────────────────────────┐
                        │                     Entra ID                          │
                        │   AD-synced groups: tms-<tenant>-<role> / tms-platform-<role>
                        └───────────────▲──────────────────────────────────────┘
                                        │ OIDC / JWT (groups claim)
 ┌──────────────┐   HTTPS   ┌───────────┴───────────┐        ┌────────────────┐
 │  React SPA   ├──────────►│  FastAPI backend      │───────►│  DynamoDB      │
 │  (Vite)      │   REST    │  (ECS Fargate, ALB)   │        │  7 tables      │
 └──────────────┘           │  + async refresh loop │        └────────────────┘
                            └───┬────────┬──────────┘
                                │        │
              start/poll/cancel │        │ COPY INTO (unload / load)
                                ▼        ▼
                      ┌──────────────┐  ┌──────────────────────┐
                      │ EMR          │  │ Snowflake            │
                      │ Serverless   │  │ (single SERVICE      │
                      │ (per tenant) │  │  ACCOUNT; storage    │
                      └──────┬───────┘  │  integration for S3) │
                             │          └──────────┬───────────┘
                             ▼                     ▼
                      ┌──────────────────────────────────────┐
                      │ S3: data / models / platform /       │
                      │     artifacts buckets                │
                      └──────────────────────────────────────┘
```

---

## 1. Overall system flow

### 1.1 Identity and access

- **Prod** (`AUTH_MODE=prod`): the SPA signs in via MSAL against Entra ID and
  sends a bearer token on every request. The backend validates the JWT (JWKS,
  issuer, audience — startup fails fast if any is unconfigured) and resolves
  role + tenant **by group-name convention**: membership in
  `tms-<tenant>-leaddatascientist` grants LeadDataScientist scoped to
  `<tenant>`; `tms-platform-*` groups grant the tenantless platform roles.
  Groups must be AD-synced with the optional claim emitting `sAMAccountName`
  so the claim carries names, not GUIDs. A DynamoDB group-mapping table exists
  as an escape hatch for non-convention groups.
- **Dev** (`AUTH_MODE=dev`): a synthetic identity from `DEV_USER_*` env vars;
  the SPA's demo login role picker is cosmetic — `/auth/me` is authoritative.

**Roles:** `LeadDataScientist` (tenant-scoped writes), `DataScientist`
(tenant-scoped read + limited job ops), `Operator` (cross-tenant job
operations only), `PlatformAdmin` (cross-tenant read + tenant/group admin).
Tenantless roles see all tenants via the `ALL` GSIs and pass `?tenantId=` on
detail routes.

### 1.2 Pipeline authoring and governance

Pipelines are authored (SPA wizard → `POST /pipelines`) as an ordered chain of
optional steps, validated server-side:

```
data_pipeline → execute_model → data_quality_check → approval → load_to_snowflake
```

- `execute_model` references must exist in the model registry at create time.
- Platform-managed EMR fields (`emrApplicationId`, `executionRoleArn`,
  `entryPointS3Uri`) are **rejected** if authored — they always come from the
  tenant's execution config at run time.
- Promotion to production (`POST /pipelines/{id}/promote`) requires a valid
  ServiceNow ticket and at least one successful run. Production jobs are
  operationally restricted: starting one takes Operator or LeadDataScientist;
  stop / retry / resume on a production run is **Operator-only**.

### 1.3 Job execution

`POST /jobs` snapshots the pipeline's version and steps into an immutable job
record (evidence trail); `POST /jobs/{id}/start` begins the cascade. Steps run
strictly in dependency order; each step type has an executor with a **mock and
a real implementation** selected by env switches (`EMR_MODE`,
`SNOWFLAKE_MODE`, `DQ_MODE`):

| Step | Real executor | What it does |
|---|---|---|
| `data_pipeline` | Snowflake connector | Async `COPY INTO <s3 stage>` unload of the source table into the run's input prefix; a `scriptS3Uri` variant runs the author's own Spark script on EMR instead |
| `execute_model` | EMR Serverless | `start_job_run` with the platform scoring entrypoint, the registered model's `artifactS3Uri`, and run-scoped input/output URIs; polled to a terminal state |
| `data_quality_check` | pyarrow over S3 | Reads the run's parquet scoring output (byte-budgeted by `DQ_MAX_BYTES`), computes row counts, error rate, and **real PSI** against the model's registered drift baseline |
| `approval` | — | Parks the job `awaiting_approval`; LeadDataScientist approves/rejects |
| `load_to_snowflake` | Snowflake connector | Always the last step; loads the run's own scoring output via `COPY INTO <table>` (storage integration; no AWS creds in SQL), stamping per-row `run_id`/date lineage columns |

**Progression** is driven two ways, both idempotent:

- a **background refresh loop** — a plain asyncio task inside each API
  process (no worker fleet) that polls non-terminal jobs every
  `JOB_REFRESH_INTERVAL_SECONDS`, bounded by `JOB_REFRESH_MAX_CONCURRENCY` so
  one slow EMR/Snowflake call can't stall the pass;
- a **synchronous refresh on `GET /jobs/{id}`**, so a user watching a job
  never waits for the loop.

Safety rails: optimistic locking / conditional writes make the refresh safe
with multiple API tasks; `STEP_TIMEOUT_SECONDS` (default 6 h) hard-fails any
stuck step and best-effort-cancels its EMR run; failed steps support retry,
resume (keep completed steps), and an audited manual override.

### 1.4 Data flow and tenant isolation

Every run reads and writes under **run-scoped S3 prefixes**
(`.../<date>/<runId>/...`) inside the tenant's `dataS3Prefix`
(`s3://<data bucket>/<tenant_id>/…`). The API rejects pipeline URIs outside
the tenant's prefix; on the compute side, each tenant's EMR **job execution
role** can only read/write that tenant's prefixes — API-level and IAM-level
isolation are enforced independently.

Snowflake is reached **only** by the platform's single service account
(key-pair auth via SSM SecureString); no user identity or credential is ever
forwarded. The role granted to that account bounds what any tenant pipeline
can export or load.

### 1.5 Model registry, monitoring, and governance

- `POST /models` registers `name` + free-form `version` with framework,
  enterprise model id (MRM record), an `artifactS3Uri`, optional threshold
  overrides, and an optional per-feature **drift baseline** (bin edges +
  proportions). Artifacts can be uploaded through the platform
  (`POST /models/artifacts` → tenant-prefixed key in the artifacts bucket →
  returned URI), or referenced in place in the models bucket.
- Every completed DQ step writes a **monitoring snapshot** and, in one
  DynamoDB transaction, denormalizes the model's `currentMonitoringStatus`:
  PSI and error-rate against warn/fail thresholds → `Passed` / `InReview`
  (warning zone awaiting review) / `Rework` (acknowledged) / `Failed`.
- Stage transitions are a strict machine
  (`None → Staging → Production → Archived`) and **promotion to Production is
  blocked** while monitoring status is `Failed` or `InReview` — the
  governance loop closes here.

### 1.6 Audit

Every mutating service call writes an audit event as its last step —
**best-effort by design**: a failed audit write never rolls back the
operation, but it is never silent either (ERROR log + in-process counter
surfaced on `GET /health` as `auditWriteFailures`). Events are queryable per
tenant and cross-tenant by date.

---

## 2. Production layout (for developers)

### 2.1 Runtime topology

```
Internet ──► ALB (target group, port 8000) ──► ECS Fargate service
                                               <prefix>-backend, desired_count=2
                                               awsvpc ENIs in private subnets
```

- **Container**: `backend/Dockerfile` `prod` stage — python:3.12-slim,
  non-root, uvicorn on **8000**, `HEALTHCHECK` against `/health`. moto is
  never installed in prod (only the `dev` stage, for CI integration tests).
- **Frontend**: static Vite build, hosted separately (any static host/CDN);
  its origin must appear in `CORS_ALLOWED_ORIGINS`. `VITE_*` values are baked
  in at **build** time — a per-environment `npm run build`, not runtime env.
- The API is safe at `desired_count > 1`: per-task refresh loops coordinate
  through optimistic locking and conditional writes. The ECS service deploys
  with circuit-breaker rollback.
- Networking (VPC, subnets, security groups, the ALB itself) is deliberately
  **out of IaC scope** — the landing zone provides it and the module takes
  IDs/ARNs as inputs.

### 2.2 Two Terraform modules

| Module | Owns | Key inputs |
|---|---|---|
| `infra/data-plane` | The storage/compute real modes run on: 3 S3 buckets, per-tenant EMR Serverless applications + job execution roles, the Snowflake storage-integration IAM role | `tenant_ids`, `data_retention_days`, `kms_key_arn`, `emr_maximum_capacity` |
| `backend/iac` | The control plane: DynamoDB tables, ECS cluster/service/task definition, ALB attachment, CloudWatch logs, ECR (optional), IAM execution/task roles, container env + SSM secrets | `container_image`, `subnet_ids`, `entra_parameter_arns`, mode switches, and the data-plane outputs (`emr_application_arns`, `emr_execution_role_arns`, `dq_s3_read_arns`, `artifacts_bucket_name`) |

The data-plane outputs feed the backend module — the backend deliberately
takes all data-plane ARNs as input so the two can be applied and evolved
independently.

**When `infra/data-plane` runs** (it is *not* a per-deploy step — routine
backend releases never touch it):

1. **Initial go-live, before `backend/iac`** — the backend module can't
   plan without its outputs (`emr_application_arns` /
   `emr_execution_role_arns` feed the task-role allowlists, which must be
   non-empty when `emr_mode = "real"`; `entrypoint_s3_uri` becomes
   `EMR_ENTRYPOINT_S3_URI`), and the Snowflake handshake points at the
   integration role it creates.
2. **Twice during the Snowflake storage-integration handshake** — first
   apply creates the role with a placeholder trust; after
   `CREATE STORAGE INTEGRATION` + `DESC INTEGRATION`, a second apply pins
   the trust to Snowflake's IAM user + external id.
3. **Every tenant onboarding/offboarding** — add/remove the slug in
   `tenant_ids`, apply, then **re-apply `backend/iac`** so the new
   application/role ARNs land in the task role's allowlists before that
   tenant's jobs run. Offboarding severs `iam:PassRole` immediately; the
   backend module's precondition fails the plan if the allowlists would go
   empty while `emr_mode = "real"`.

Otherwise it changes only with data-plane policy itself: retention
(`data_retention_days`), encryption (`kms_key_arn`), or EMR capacity
ceilings.

### 2.3 S3 buckets and prefix conventions

| Bucket | Contents | Notes |
|---|---|---|
| `<prefix>-data-<acct>` | Run data: Snowflake unload staging + scoring output, always `s3://…/<tenant_id>/…` | Lifecycle expiry (default 90 days) — run data is transient |
| `<prefix>-models-<acct>` | Registered model artifacts | **Versioned** — a registry-referenced artifact must never silently change |
| `<prefix>-platform-<acct>` | Platform assets: the scoring entrypoint under `entrypoints/` | Versioned; upload `backend/emr/scoring_entrypoint.py` per release |
| `S3_ARTIFACTS_BUCKET` (default `mlserv-artifacts`) | Artifacts uploaded through `POST /models/artifacts`, under `<tenant_id>/uploads/<random>/<file>` | Provisioned out-of-band; name must be passed as `artifacts_bucket_name` so the IAM grant and the app agree |

All buckets: TLS-only, public access blocked, SSE (CMK optional via
`kms_key_arn`).

### 2.4 IAM roles

| Role | Attached to | Grants |
|---|---|---|
| **Execution role** (`<prefix>-backend-execution-role`) | ECS agent | Image pull, logs, `ssm:GetParameters` for the injected Entra/Snowflake secrets |
| **Task role** (`<prefix>-backend-task-role`) | The app | Least-privilege DynamoDB on the 7 tables (+ GSIs); EMR Serverless start/get/cancel scoped to the per-tenant application ARNs + `iam:PassRole` **conditioned to emr-serverless.amazonaws.com**; S3 read on `dq_s3_read_arns` (real DQ); S3 put/get on the artifacts bucket (uploads) |
| **Per-tenant EMR job execution roles** | EMR Serverless job runs | Read model artifacts + run input, write scoring output — **only that tenant's prefixes**; this is the compute-side isolation boundary |
| **Snowflake integration role** | Assumed by Snowflake | The AWS half of the storage integration; trust pinned to Snowflake's IAM user + external id via the two-apply handshake (see `infra/data-plane/README.md`) |

### 2.5 DynamoDB tables

`mlserv-tenants`, `mlserv-group-mappings`, `mlserv-pipelines`, `mlserv-jobs`,
`mlserv-models`, `mlserv-monitoring-snapshots`, `mlserv-audit` — all
tenant-partitioned, with `ALL`-partition GSIs for the cross-tenant roles. PITR
and deletion protection are on by default. Floats are converted to Decimal at
the storage boundary (`app/db/client.py`), and the snapshot+model-status write
is a `TransactWriteItems` so monitoring evidence and the denormalized status
can never diverge. `app/db/client.py` is also the single endpoint-aware
factory for every AWS client (DynamoDB + S3): endpoint URLs set → moto in
dev; empty → real AWS via the task role.

### 2.6 Configuration and secrets

- Plain env (set by `backend/iac/ecs.tf` `base_environment`): `AUTH_MODE=prod`,
  blank `DDB_ENDPOINT_URL`/`S3_ENDPOINT_URL` (the app defaults point at local
  moto — blanking them in prod is load-bearing), mode switches, table names,
  CORS, `S3_ARTIFACTS_BUCKET`.
- Secrets via **SSM parameters injected as container secrets**:
  `ENTRA_*` (JWKS/issuer/audience) and `SNOWFLAKE_*` (account, user,
  private-key PEM as SecureString, storage integration).
- **Fail-fast at startup** (lifespan): prod auth refuses to serve with
  incomplete Entra config; `SNOWFLAKE_MODE=real` / `DQ_MODE=real` refuse to
  start half-configured. Terraform mirrors this: `emr_mode = "real"` with an
  empty application/role allowlist fails the plan.

### 2.7 Snowflake service-account authentication (key-pair)

The platform's single service account authenticates with **key-pair auth**
(the Snowflake standard for non-interactive service users — no password, no
interactive/OAuth flow). Password auth exists only as a non-prod fallback.
Setup steps:

1. **Create the service user and role** (ACCOUNTADMIN, once):

   ```sql
   CREATE ROLE MLSERV_ROLE;
   CREATE USER MLSERV_SVC TYPE = SERVICE DEFAULT_ROLE = MLSERV_ROLE;
   GRANT ROLE MLSERV_ROLE TO USER MLSERV_SVC;
   -- The outer boundary of what any tenant pipeline can export/load:
   GRANT USAGE ON WAREHOUSE <wh> TO ROLE MLSERV_ROLE;
   GRANT SELECT ON <each exportable schema> TO ROLE MLSERV_ROLE;
   GRANT INSERT ON <each load target> TO ROLE MLSERV_ROLE;
   GRANT USAGE ON INTEGRATION MLSERV_S3 TO ROLE MLSERV_ROLE;
   ```

   `TYPE = SERVICE` disables password/UI login outright — the key pair is the
   only way in.

2. **Generate the RSA key pair** (2048-bit minimum, PKCS#8):

   ```bash
   openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out rsa_key.p8 -nocrypt
   openssl rsa -in rsa_key.p8 -pubout -out rsa_key.pub
   ```

   (Use `-v2 aes-256-cbc` instead of `-nocrypt` for an encrypted key, and set
   `SNOWFLAKE_PRIVATE_KEY_PASSPHRASE` accordingly.)

3. **Register the public key on the user** (the PEM body, no header/footer):

   ```sql
   ALTER USER MLSERV_SVC SET RSA_PUBLIC_KEY = 'MIIBIjANBgkq...';
   ```

4. **Store the private key in SSM** as a SecureString parameter and pass its
   ARN in `snowflake_parameter_arns` (key `SNOWFLAKE_PRIVATE_KEY`) — ECS
   injects it as a container secret; it never lands in Terraform state,
   images, or plain env. Set `SNOWFLAKE_USER`, `SNOWFLAKE_ACCOUNT`,
   `SNOWFLAKE_ROLE`, `SNOWFLAKE_STORAGE_INTEGRATION` the same way.
5. **Verify**: `app/services/snowflake_connection.py` converts the PEM to DER
   and connects on the next real-mode step; a quick check is one
   `data_pipeline` run, or `SELECT CURRENT_USER(), CURRENT_ROLE()` via the
   connector with the same env.
6. **Rotation** (zero-downtime): register the new key as `RSA_PUBLIC_KEY_2`,
   update the SSM parameter, force a new ECS deployment (env is read once at
   startup), then `UNSET RSA_PUBLIC_KEY` and promote — Snowflake accepts
   either registered key during the overlap.

### 2.8 Execution-mode switches

`EMR_MODE`, `SNOWFLAKE_MODE`, `DQ_MODE` are independent `mock|real` switches —
in-process mocks, not emulators, so flipping a deployment to real is a config
change, not a rebuild. Real-mode extras (`snowflake-connector-python`,
`pyarrow`) are installed in every image but imported lazily.

### 2.9 Go-live runbook (fresh environment)

Ordered so nothing has to be revisited; each phase ends with a verification
gate. Prerequisites from the landing zone: a VPC with private subnets, a
security group that lets the ALB reach port 8000, an ALB + TLS certificate,
an ECR repository (or set `create_ecr_repository = true`), a Snowflake
account + warehouse, and Entra ID admin access.

**Phase 1 — Entra ID (identity first: its values feed everything else)**

1. Create the **API app registration** (this is what the backend validates):
   set an Application ID URI (`api://<client-id>`), and configure the
   **groups claim** to emit group names — the token configuration's optional
   claim must be set to `sAMAccountName`, which only works for **AD-synced**
   groups. This is load-bearing: the group NAME is the role grant.
2. Create the **SPA app registration** for the frontend: platform
   Single-page application, redirect URI = the frontend origin, grant it the
   API app's scope. (One combined registration also works — the frontend's
   `VITE_ENTRA_API_SCOPE` defaults to `api://<client-id>/.default`.)
3. Create the platform-level AD groups (`tms-platform-platformadmin`,
   `tms-platform-operator`) and add the go-live operators. Per-tenant groups
   come with each tenant in Phase 7.
4. Record: tenant id, API client id, JWKS URL
   (`https://login.microsoftonline.com/<tenant>/discovery/v2.0/keys`),
   issuer, audience.
   ✅ *Gate: token from a test sign-in carries the group **names** in the
   `groups` claim (decode it and look) — GUIDs mean the optional claim or
   AD-sync is wrong.*

**Phase 2 — Data plane (storage + per-tenant compute)**

1. `terraform apply` **infra/data-plane** with the initial `tenant_ids`
   (start with the pilot tenant only) and tags; set `kms_key_arn` if a CMK is
   mandated.
2. Upload the scoring entrypoint:
   `aws s3 cp backend/emr/scoring_entrypoint.py "$(terraform output -raw entrypoint_s3_uri)"`.
3. Record outputs: `tenant_execution` (per-tenant `emrApplicationId`,
   `emrExecutionRoleArn`, `dataS3Prefix`), `emr_application_arns`,
   `emr_execution_role_arns`, `dq_s3_read_arns`, `entrypoint_s3_uri`,
   `snowflake_integration_role_arn`.
   ✅ *Gate: the three buckets exist, the pilot tenant's EMR application is
   in `CREATED`/`STARTED`, the entrypoint object is present.*

**Phase 3 — Snowflake (service account + storage integration)**

1. Create the service user, role, and grants; generate and register the
   key pair — full steps in §2.7.
2. Complete the **storage-integration handshake** (two Terraform applies
   around `CREATE STORAGE INTEGRATION` — exact SQL and the
   `DESC INTEGRATION` round-trip in `infra/data-plane/README.md`).
3. Grant the service role `USAGE` on the integration and read on the pilot
   tenant's exportable schemas.
   ✅ *Gate: as the service user (key-pair, e.g. via SnowSQL),
   `COPY INTO 's3://<data bucket>/<pilot>/smoke/' FROM (SELECT 1)
   STORAGE_INTEGRATION = MLSERV_S3` writes an object.*

**Phase 4 — Secrets (SSM parameters)**

Create the parameters and note their ARNs. Entra (5, String):
`ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`, `ENTRA_JWKS_URL`, `ENTRA_ISSUER`,
`ENTRA_AUDIENCE`. Snowflake: `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`,
`SNOWFLAKE_ROLE`, `SNOWFLAKE_STORAGE_INTEGRATION` (String) and
`SNOWFLAKE_PRIVATE_KEY` (**SecureString**, the PEM content; plus
`SNOWFLAKE_PRIVATE_KEY_PASSPHRASE` if the key is encrypted). The app
fail-fasts at boot if any required one resolves blank — a typo'd ARN
surfaces as a crash-looping task, not silent misbehavior.

**Phase 5 — Backend image**

```bash
docker build --target prod -t mlserv-backend:v1.0.0 backend/
docker tag ... <acct>.dkr.ecr.<region>.amazonaws.com/mlserv-backend:v1.0.0
docker push ...
```
✅ *Gate: image in ECR; scan results reviewed (repo scans on push).*

**Phase 6 — Control plane (backend/iac)**

1. `terraform apply` **backend/iac** wiring everything recorded so far:
   `container_image`, `subnet_ids` / `security_group_ids` /
   `target_group_arn`, `cors_allowed_origins` (the frontend origin),
   `entra_parameter_arns`, `snowflake_parameter_arns`,
   `artifacts_bucket_name`, the mode switches
   (`emr_mode = snowflake_mode = dq_mode = "real"`), and the data-plane
   outputs (`emr_application_arns`, `emr_execution_role_arns`,
   `dq_s3_read_arns`, `extra_environment.EMR_ENTRYPOINT_S3_URI`).
2. Watch the service reach steady state (circuit breaker rolls back a
   failing deploy automatically).
   ✅ *Gate: `GET https://<alb>/health` → 200 with
   `auditWriteFailures: 0`; task logs show no startup validation errors;
   an unauthenticated `GET /pipelines` → 401.*

**Phase 7 — Frontend**

1. Build with the prod values **baked in**: `VITE_DEMO_MODE=false`,
   `VITE_API_BASE_URL=https://<api host>`, `VITE_ENTRA_TENANT_ID`,
   `VITE_ENTRA_CLIENT_ID` (SPA registration), `VITE_ENTRA_API_SCOPE` if the
   API is a separate registration → `npm run build`.
2. Deploy `dist/` to the static host; confirm its origin equals both the SPA
   redirect URI and `cors_allowed_origins`.
   ✅ *Gate: browser sign-in round-trip works and `/auth/me` shows the
   expected role from group membership.*

**Phase 8 — Pilot tenant onboarding + end-to-end proof**

1. As PlatformAdmin: `POST /tenants` (id must equal the Terraform tenant
   slug), `PUT /tenants/{id}/execution` with that tenant's
   `tenant_execution` output values.
2. Create the tenant's AD groups (`tms-<tenant>-leaddatascientist`,
   `tms-<tenant>-datascientist`) and add the pilot users.
3. As the tenant's LeadDataScientist: upload/register a model
   (`POST /models/artifacts` → `POST /models`, ideally with a drift
   baseline), author a full five-step pipeline, submit + start a job, and
   watch it run every real executor: Snowflake unload → EMR scoring → DQ →
   approval → load.
4. Verify the evidence chain: monitoring snapshot written, model's
   monitoring status updated, lineage columns present in the loaded Snowflake
   table, audit log complete for every action.
5. Promote the pipeline to production with a ServiceNow ticket; run it once
   via `POST /pipelines/{id}/trigger` (the scheduler path).
   ✅ *Gate: this is the go/no-go — a full production-path run with all
   three modes real.*

**Phase 9 — Day-2 guardrails (before announcing)**

- Alarms: ALB 5xx, ECS task restarts, and `auditWriteFailures > 0` scraped
  from `/health` — non-zero means the audit trail has gaps.
- Log-based alert on `AUDIT WRITE FAILED` and on the refresh loop's
  "Background job refresh pass failed".
- Calendar the Snowflake key rotation (§2.7 step 6) and confirm DynamoDB
  PITR + deletion protection are on (module defaults).
- Routine deploys from here: push a new image tag → `terraform apply` with
  the new `container_image`; config changes are env-only (no rebuild), but
  remember env is read once at startup — changes need a new deployment.

### 2.10 Local dev vs production

| | Local dev | Production |
|---|---|---|
| Entry point | `backend/scripts/dev.py` + `frontend/scripts/dev.mjs` (no Docker) | ECS Fargate task |
| Ports | API **8001**, moto **5001**, frontend **3001** (offset so TMS and TMT run side by side) | Container 8000 behind the ALB |
| AWS | One moto server emulates DynamoDB **and** S3 | Real AWS via task role |
| EMR / Snowflake / DQ | In-process mocks (no emulator exists for either) | `real` mode switches |
| Auth | `AUTH_MODE=dev` synthetic identity | Entra ID OIDC |
| Data | `scripts/seed_demo_data.py` demo tenants (`acme-capital`, `blue-harbor-bank`) | Tenant onboarding runbook |

Deeper dives: `backend/README.md` (API surface, RBAC matrix, run lifecycle),
`frontend/README.md` (SPA structure), `backend/iac/README.md` and
`infra/data-plane/README.md` (IaC inputs/outputs and runbooks).
