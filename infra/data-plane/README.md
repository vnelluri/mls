# Data-plane IaC (Terraform module)

Provisions the storage and compute the platform's **real execution modes**
run on — everything `backend/iac` deliberately takes as input:

- **three S3 buckets** (TLS-only, public access blocked, SSE; CMK optional):
  - `<prefix>-data-<acct>` — per-tenant run data: Snowflake unload staging +
    scoring output, always under `s3://<bucket>/<tenant_id>/…` (the tenant's
    `dataS3Prefix`; the API rejects pipeline URIs outside it). Lifecycle
    expiry after `data_retention_days` (default 90) — run data is transient
    by design.
  - `<prefix>-models-<acct>` — registered model artifacts, **versioned** (an
    artifact referenced by the registry must never silently change).
  - `<prefix>-platform-<acct>` — platform assets: the scoring entrypoint
    under `entrypoints/`, versioned.
- **per tenant**: an EMR Serverless application (auto-stop, capacity ceiling)
  and a job execution role that can read/write **only that tenant's
  prefixes** — the compute-side tenant-isolation boundary.
- the **Snowflake storage-integration IAM role** (the AWS half of
  `SNOWFLAKE_STORAGE_INTEGRATION`).

## Usage

```hcl
module "mlserv_data_plane" {
  source = "./infra/data-plane"

  tenant_ids = ["acme-capital", "blue-harbor-bank"]
  tags       = { app = "mlserv", env = "prod" }
}

module "mlserv_backend" {
  source = "./backend/iac"

  # ... image, subnets, entra_parameter_arns, etc. (see backend/iac/README) ...

  emr_mode                = "real"
  snowflake_mode          = "real"
  dq_mode                 = "real"
  emr_application_arns    = module.mlserv_data_plane.emr_application_arns
  emr_execution_role_arns = module.mlserv_data_plane.emr_execution_role_arns
  dq_s3_read_arns         = module.mlserv_data_plane.dq_s3_read_arns

  extra_environment = {
    EMR_ENTRYPOINT_S3_URI = module.mlserv_data_plane.entrypoint_s3_uri
  }
}
```

After applying, upload the scoring entrypoint (repeat per release of it):

```bash
aws s3 cp backend/emr/scoring_entrypoint.py "$(terraform output -raw entrypoint_s3_uri)"
```

## Snowflake storage-integration handshake (one-time, two applies)

Snowflake assumes an IAM role to write unloads; the role must trust
Snowflake's IAM user + external id, which Snowflake only reveals **after**
the integration exists — hence two applies:

1. **Apply with `snowflake_iam_user_arn` / `snowflake_external_id` empty.**
   The role is created with a placeholder trust (this account only — nothing
   external can assume it yet).
2. In Snowflake, as ACCOUNTADMIN, using `snowflake_integration_role_arn`:

   ```sql
   CREATE STORAGE INTEGRATION MLSERV_S3
     TYPE = EXTERNAL_STAGE
     STORAGE_PROVIDER = 'S3'
     ENABLED = TRUE
     STORAGE_AWS_ROLE_ARN = '<snowflake_integration_role_arn output>'
     STORAGE_ALLOWED_LOCATIONS = ('s3://<data bucket>/');

   GRANT USAGE ON INTEGRATION MLSERV_S3 TO ROLE <the service account's role>;
   DESC INTEGRATION MLSERV_S3;  -- note STORAGE_AWS_IAM_USER_ARN and STORAGE_AWS_EXTERNAL_ID
   ```

3. **Set both variables from the DESC output and apply again** — the trust
   policy is now pinned to Snowflake's IAM user and external id.
4. Set the backend's `SNOWFLAKE_STORAGE_INTEGRATION` SSM parameter to
   `MLSERV_S3`. The platform connects as its single **service account** only
   (users never touch Snowflake), so the integration grant above is the only
   Snowflake-side permission the unloads need beyond the account's read role.

## Tenant onboarding runbook

Onboarding tenant `new-bank` end to end:

1. Add `"new-bank"` to `tenant_ids`, `terraform apply`. Read
   `tenant_execution["new-bank"]` from the outputs.
2. As PlatformAdmin: `POST /tenants` (id **must** be `new-bank`), then
   `PUT /tenants/new-bank/execution` with the output values
   (`emrApplicationId`, `emrExecutionRoleArn`, `dataS3Prefix`).
3. In Entra: create the AD-synced groups `tms-new-bank-leaddatascientist` /
   `tms-new-bank-datascientist` and add members — the group name **is** the
   role grant; no further mapping needed.
4. Upload the tenant's model artifacts under
   `s3://<models bucket>/new-bank/…` and register them via `POST /models`.
5. Grant the Snowflake service account's role read on the schemas this
   tenant's pipelines may export — that grant is the outer boundary of what
   the tenant can unload.

Offboarding is the reverse; the tenant's EMR application and execution role
are destroyed with its `tenant_ids` entry, which immediately severs the
backend's `iam:PassRole` allowlist for it (the backend module's precondition
fails the plan if the allowlists go empty while `emr_mode = "real"`).

## Notable variables

| Variable | Default | Purpose |
|---|---|---|
| `tenant_ids` | — | tenant slugs; must equal the platform `tenant_id`s (and the Entra group slugs) |
| `data_retention_days` | `90` | lifecycle expiry for run data; `0` disables |
| `kms_key_arn` | `""` (SSE-S3) | CMK for all three buckets (+ grants for EMR roles and the Snowflake role) |
| `emr_release_label` | `emr-7.5.0` | EMR Serverless release per tenant application |
| `emr_maximum_capacity` | 64 vCPU / 512 GB | per-application cost ceiling; `null` for EMR defaults |
| `snowflake_iam_user_arn` / `snowflake_external_id` | `""` | second apply of the handshake above |
