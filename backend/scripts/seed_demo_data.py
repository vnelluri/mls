#!/usr/bin/env python
"""
Idempotent demo-data seeder.

Seeds (against whatever DDB_ENDPOINT_URL is configured):
  * 2 demo tenants (acme-capital, blue-harbor-bank) + 1 suspended tenant
  * group mappings: a PlatformAdmin group, a cross-tenant Operator group,
    plus a LeadDataScientist and a DataScientist group per tenant
  * pipelines (one with an approval gate, one without) per tenant
  * model registry entries across stages
  * jobs in various states, including at least one awaiting_approval
  * completed monitoring snapshots showing each of Passed / Rework / Failed
    across different models, with the models' denormalized
    currentMonitoringStatus updated to match

Idempotency: fixed IDs everywhere; re-running overwrites the same items
rather than duplicating them.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from app.config import settings  # noqa: E402
from app.db.client import get_table  # noqa: E402

NOW = datetime.now(timezone.utc)


def ts(minutes_ago: int = 0) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).isoformat()


SEED_USER = "seed-script"

# ---------------------------------------------------------------------------
# Tenants
# ---------------------------------------------------------------------------
TENANTS = [
    {"tenant_id": "acme-capital", "name": "Acme Capital", "status": "active",
     "createdAt": ts(60 * 24 * 30), "createdBy": SEED_USER},
    {"tenant_id": "blue-harbor-bank", "name": "Blue Harbor Bank", "status": "active",
     "createdAt": ts(60 * 24 * 21), "createdBy": SEED_USER},
    {"tenant_id": "old-north-trust", "name": "Old North Trust", "status": "suspended",
     "createdAt": ts(60 * 24 * 90), "createdBy": SEED_USER},
]

# ---------------------------------------------------------------------------
# Group mappings (synthetic Entra group object IDs)
# ---------------------------------------------------------------------------
GROUP_MAPPINGS = [
    {"group_id": "00000000-0000-4000-a000-000000000001", "role": "PlatformAdmin",
     "tenant_id": None, "displayName": "mlserv-platform-admins",
     "updatedAt": ts(60 * 24 * 30), "updatedBy": SEED_USER},
    {"group_id": "00000000-0000-4000-a000-000000000002", "role": "Operator",
     "tenant_id": None, "displayName": "mlserv-operators",
     "updatedAt": ts(60 * 24 * 30), "updatedBy": SEED_USER},
    {"group_id": "00000000-0000-4000-a000-000000000011", "role": "LeadDataScientist",
     "tenant_id": "acme-capital", "displayName": "mlserv-acme-capital-leads",
     "updatedAt": ts(60 * 24 * 30), "updatedBy": SEED_USER},
    {"group_id": "00000000-0000-4000-a000-000000000012", "role": "DataScientist",
     "tenant_id": "acme-capital", "displayName": "mlserv-acme-capital-ds",
     "updatedAt": ts(60 * 24 * 30), "updatedBy": SEED_USER},
    {"group_id": "00000000-0000-4000-a000-000000000021", "role": "LeadDataScientist",
     "tenant_id": "blue-harbor-bank", "displayName": "mlserv-blue-harbor-leads",
     "updatedAt": ts(60 * 24 * 21), "updatedBy": SEED_USER},
    {"group_id": "00000000-0000-4000-a000-000000000022", "role": "DataScientist",
     "tenant_id": "blue-harbor-bank", "displayName": "mlserv-blue-harbor-ds",
     "updatedAt": ts(60 * 24 * 21), "updatedBy": SEED_USER},
]

# ---------------------------------------------------------------------------
# Helpers to build steps
# ---------------------------------------------------------------------------

def dp_step(step_id, table, dest):
    return {
        "step_id": step_id, "type": "data_pipeline", "dependsOn": [],
        "config": {
            "sourceType": "snowflake",
            "snowflakeParams": {
                "database": "FIN_DW", "schema": "SCORING",
                "table": table, "warehouse": "SCORING_WH",
            },
            "destinationS3Uri": dest,
        },
    }


def em_step(step_id, depends, model_name, version, in_uri, out_uri):
    return {
        "step_id": step_id, "type": "execute_model", "dependsOn": depends,
        "config": {
            "modelName": model_name, "modelVersion": version,
            "emrApplicationId": "00fake1emrapp", "executionRoleArn":
                "arn:aws:iam::123456789012:role/mlserv-emr-exec",
            "entryPointS3Uri": "s3://mlserv-artifacts/entrypoints/score.py",
            "inputS3Uri": in_uri, "outputS3Uri": out_uri,
            "sparkSubmitParameters": None,
        },
    }


def dq_step(step_id, depends, in_uri, null_threshold=0.08):
    return {
        "step_id": step_id, "type": "data_quality_check", "dependsOn": depends,
        "config": {
            "checks": [
                {"name": "output_null_rate", "type": "null_rate", "threshold": null_threshold},
                {"name": "row_count_drift", "type": "row_count_delta", "threshold": 0.15},
            ],
            "inputS3Uri": in_uri,
        },
    }


def approval_step(step_id, depends, note=None):
    return {"step_id": step_id, "type": "approval", "dependsOn": depends,
            "config": {"approverNote": note}}


def pipeline_item(tenant_id, pipeline_id, name, description, requires_approval, steps,
                  status="active", minutes_ago=600):
    updated = ts(minutes_ago)
    return {
        "tenant_id": tenant_id, "pipeline_id": pipeline_id, "name": name,
        "description": description, "version": 1, "status": status,
        "requiresApproval": requires_approval, "steps": steps,
        "createdBy": SEED_USER, "createdAt": ts(minutes_ago + 60),
        "updatedBy": SEED_USER, "updatedAt": updated,
        "all_pk": "ALL", "all_sk": f"{tenant_id}#{updated}",
    }


PIPELINES = [
    pipeline_item(
        "acme-capital", "pl-acmecred1", "Credit Risk Batch Scoring",
        "Nightly credit-risk scoring: Snowflake extract -> EMR scoring -> DQ gate -> lead approval.",
        True,
        [
            dp_step("step-1", "CREDIT_APPLICATIONS", "s3://mlserv-acme/credit/in/"),
            em_step("step-2", ["step-1"], "credit-risk-scorer", "1",
                    "s3://mlserv-acme/credit/in/", "s3://mlserv-acme/credit/out/"),
            dq_step("step-3", ["step-2"], "s3://mlserv-acme/credit/out/"),
            approval_step("step-4", ["step-3"], "Lead sign-off before scores publish."),
        ],
        minutes_ago=60 * 48,
    ),
    pipeline_item(
        "acme-capital", "pl-acmefrd01", "Fraud Detection Scoring",
        "Hourly fraud scoring without an approval gate.",
        False,
        [
            dp_step("step-1", "CARD_TRANSACTIONS", "s3://mlserv-acme/fraud/in/"),
            em_step("step-2", ["step-1"], "fraud-detector", "2",
                    "s3://mlserv-acme/fraud/in/", "s3://mlserv-acme/fraud/out/"),
            dq_step("step-3", ["step-2"], "s3://mlserv-acme/fraud/out/"),
        ],
        minutes_ago=60 * 24,
    ),
    pipeline_item(
        "blue-harbor-bank", "pl-bhbchurn1", "Churn Propensity Scoring",
        "Weekly churn scoring with lead approval gate.",
        True,
        [
            dp_step("step-1", "CUSTOMER_360", "s3://mlserv-bhb/churn/in/"),
            em_step("step-2", ["step-1"], "churn-predictor", "1",
                    "s3://mlserv-bhb/churn/in/", "s3://mlserv-bhb/churn/out/"),
            dq_step("step-3", ["step-2"], "s3://mlserv-bhb/churn/out/"),
            approval_step("step-4", ["step-3"]),
        ],
        minutes_ago=60 * 12,
    ),
    pipeline_item(
        "blue-harbor-bank", "pl-bhbdraft1", "AML Alert Scoring (draft)",
        "Draft pipeline, not yet activated.",
        False,
        [
            dp_step("step-1", "AML_ALERTS", "s3://mlserv-bhb/aml/in/"),
            em_step("step-2", ["step-1"], "aml-alert-ranker", "1",
                    "s3://mlserv-bhb/aml/in/", "s3://mlserv-bhb/aml/out/"),
            dq_step("step-3", ["step-2"], "s3://mlserv-bhb/aml/out/"),
        ],
        status="draft",
        minutes_ago=60 * 2,
    ),
]

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

def model_item(tenant_id, name, model_id, version, stage, framework, monitoring_status,
               last_snapshot_minutes_ago=None, drift_override=None, err_override=None,
               promoted=False):
    return {
        "tenant_id": tenant_id, "model_name": name, "model_id": model_id,
        "version": version,
        "sk": f"{name}#{version}", "stage": stage, "framework": framework,
        "artifactS3Uri": f"s3://mlserv-artifacts/{tenant_id}/{name}/v{version}/model.tar.gz",
        "description": f"{name} v{version}",
        "driftThresholdOverride": drift_override,
        "errorRateThresholdOverride": err_override,
        "currentMonitoringStatus": monitoring_status,
        "lastSnapshotAt": ts(last_snapshot_minutes_ago) if last_snapshot_minutes_ago is not None else None,
        "registeredBy": SEED_USER, "registeredAt": ts(60 * 24 * 10),
        "promotedBy": SEED_USER if promoted else None,
        "promotedAt": ts(60 * 24 * 5) if promoted else None,
        "all_pk": "ALL", "all_sk": f"{tenant_id}#{name}#{version}",
        "stage_sk": f"{tenant_id}#{name}",
    }


MODELS = [
    model_item("acme-capital", "credit-risk-scorer", "MDL-ACME-0001", "1", "Production", "xgboost",
               "Passed", last_snapshot_minutes_ago=90, promoted=True),
    model_item("acme-capital", "fraud-detector", "MDL-ACME-0002", "1", "Archived", "lightgbm",
               "NotStarted", promoted=True),
    model_item("acme-capital", "fraud-detector", "MDL-ACME-0002", "2", "Staging", "lightgbm",
               "Rework", last_snapshot_minutes_ago=45, promoted=True,
               drift_override=0.30),
    model_item("blue-harbor-bank", "churn-predictor", "MDL-BHB-0001", "1", "Production", "sklearn",
               "Failed", last_snapshot_minutes_ago=30, promoted=True),
    model_item("blue-harbor-bank", "aml-alert-ranker", "MDL-BHB-0002", "1", "None", "pytorch",
               "NotStarted"),
]

# ---------------------------------------------------------------------------
# Jobs (steps snapshotted from the pipelines above)
# ---------------------------------------------------------------------------

def job_steps_from(pipeline, statuses, outputs=None, emr_run=None):
    steps = []
    for pstep, status in zip(pipeline["steps"], statuses):
        step = {
            "step_id": pstep["step_id"], "type": pstep["type"], "status": status,
            "startedAt": None, "completedAt": None, "emrJobRunId": None,
            "emrStateDetail": None, "errorMessage": None, "output": None,
            "config": pstep["config"],
        }
        if status in ("succeeded", "failed", "approved", "rejected"):
            step["startedAt"] = ts(50)
            step["completedAt"] = ts(45)
        if status == "running":
            step["startedAt"] = ts(1)
        if pstep["type"] == "execute_model" and status != "idle":
            step["emrJobRunId"] = emr_run or "mock-emr-seeded00001"
            step["emrStateDetail"] = "SUCCESS" if status == "succeeded" else "RUNNING"
        if outputs and pstep["step_id"] in outputs:
            step["output"] = outputs[pstep["step_id"]]
        steps.append(step)
    return steps


def job_item(tenant_id, job_id, pipeline, run_id, status, steps, minutes_ago,
             run_history=None):
    submitted = ts(minutes_ago)
    return {
        "tenant_id": tenant_id, "job_id": job_id,
        "pipeline_id": pipeline["pipeline_id"], "pipeline_version": pipeline["version"],
        "run_id": run_id, "status": status, "steps": steps,
        "runHistory": run_history or [], "submittedBy": SEED_USER,
        "submittedAt": submitted, "all_pk": "ALL",
        "all_sk": f"{tenant_id}#{submitted}",
    }


PL_ACME_CREDIT = PIPELINES[0]
PL_ACME_FRAUD = PIPELINES[1]
PL_BHB_CHURN = PIPELINES[2]

_dq_passed_output = {
    "requestCount": 2310, "avgLatencyMs": 84.2, "errorRate": 0.011,
    "driftMetrics": {"credit_score": 0.031, "annual_income": 0.044, "debt_to_income_ratio": 0.02},
    "dataQualityPassed": True,
    "dataQualityDetails": {
        "output_null_rate": {"passed": True, "observedValue": 0.012},
        "row_count_drift": {"passed": True, "observedValue": 0.05},
    },
}

_dq_rework_output = {
    "requestCount": 4100, "avgLatencyMs": 132.7, "errorRate": 0.021,
    "driftMetrics": {"transaction_velocity": 0.184, "avg_balance_30d": 0.066},
    "dataQualityPassed": True,
    "dataQualityDetails": {
        "output_null_rate": {"passed": True, "observedValue": 0.03},
        "row_count_drift": {"passed": True, "observedValue": 0.09},
    },
}

_dq_failed_output = {
    "requestCount": 980, "avgLatencyMs": 95.5, "errorRate": 0.186,
    "driftMetrics": {"account_age_days": 0.271, "num_open_lines": 0.093},
    "dataQualityPassed": False,
    "dataQualityDetails": {
        "output_null_rate": {"passed": False, "observedValue": 0.095},
        "row_count_drift": {"passed": True, "observedValue": 0.07},
    },
}

JOBS = [
    # Awaiting approval (Acme credit pipeline: dp/em/dq succeeded, approval pending)
    job_item(
        "acme-capital", "job-acmeappr1", PL_ACME_CREDIT, "RUN-0001",
        "awaiting_approval",
        job_steps_from(
            PL_ACME_CREDIT,
            ["succeeded", "succeeded", "succeeded", "awaiting_approval"],
            outputs={
                "step-1": {"rowsWritten": 18450, "s3Uri": "s3://mlserv-acme/credit/in/"},
                "step-3": _dq_passed_output,
            },
        ),
        minutes_ago=95,
    ),
    # Success without approval gate (Acme fraud) -- produced the Rework snapshot
    job_item(
        "acme-capital", "job-acmefrd01", PL_ACME_FRAUD, "RUN-0001", "success",
        job_steps_from(
            PL_ACME_FRAUD,
            ["succeeded", "succeeded", "succeeded"],
            outputs={
                "step-1": {"rowsWritten": 30211, "s3Uri": "s3://mlserv-acme/fraud/in/"},
                "step-3": _dq_rework_output,
            },
        ),
        minutes_ago=50,
    ),
    # Failed DQ (Blue Harbor churn) -- produced the Failed snapshot; retried once before
    job_item(
        "blue-harbor-bank", "job-bhbfail01", PL_BHB_CHURN, "RUN-0002", "failed",
        job_steps_from(
            PL_BHB_CHURN,
            ["succeeded", "succeeded", "failed", "idle"],
            outputs={
                "step-1": {"rowsWritten": 7211, "s3Uri": "s3://mlserv-bhb/churn/in/"},
                "step-3": _dq_failed_output,
            },
        ),
        minutes_ago=35,
        run_history=[{"run_id": "RUN-0001", "startedAt": ts(60 * 5), "endedAt": ts(60 * 4),
                      "finalStatus": "cancelled"}],
    ),
    # Cancelled job (Blue Harbor churn)
    job_item(
        "blue-harbor-bank", "job-bhbstop01", PL_BHB_CHURN, "RUN-0001", "cancelled",
        job_steps_from(PL_BHB_CHURN, ["succeeded", "running", "idle", "idle"],
                       outputs={"step-1": {"rowsWritten": 6650, "s3Uri": "s3://mlserv-bhb/churn/in/"}}),
        minutes_ago=60 * 26,
    ),
]

# Fix the failed DQ step's error message on the failed job.
for _s in JOBS[2]["steps"]:
    if _s["type"] == "data_quality_check":
        _s["errorMessage"] = "Data quality checks failed"

# ---------------------------------------------------------------------------
# Monitoring snapshots (one per completed DQ run above: Passed/Rework/Failed)
# ---------------------------------------------------------------------------
DEFAULT_THRESHOLDS = {
    "psiWarn": settings.PSI_WARN, "psiFail": settings.PSI_FAIL,
    "errorRateWarn": settings.ERROR_RATE_WARN, "errorRateFail": settings.ERROR_RATE_FAIL,
}


def snapshot_item(tenant_id, model_name, version, job_id, run_id, dq, status,
                  minutes_ago, thresholds=None):
    recorded = ts(minutes_ago)
    thr = thresholds or DEFAULT_THRESHOLDS
    return {
        "tenant_id": tenant_id, "sk": f"{model_name}#{version}#{recorded}",
        "model_name": model_name, "version": version,
        "job_id": job_id, "run_id": run_id, "recordedAt": recorded,
        "requestCount": dq["requestCount"], "avgLatencyMs": dq["avgLatencyMs"],
        "errorRate": dq["errorRate"], "driftMetrics": dq["driftMetrics"],
        "maxPsi": max(dq["driftMetrics"].values()),
        "dataQualityPassed": dq["dataQualityPassed"],
        "dataQualityDetails": dq["dataQualityDetails"],
        "derivedStatus": status, "thresholdsUsed": thr,
        "all_pk": "ALL", "model_trend_pk": f"{tenant_id}#{model_name}#{version}",
    }


SNAPSHOTS = [
    snapshot_item("acme-capital", "credit-risk-scorer", "1", "job-acmeappr1", "RUN-0001",
                  _dq_passed_output, "Passed", minutes_ago=90),
    snapshot_item("acme-capital", "fraud-detector", "2", "job-acmefrd01", "RUN-0001",
                  _dq_rework_output, "Rework", minutes_ago=45,
                  thresholds={**DEFAULT_THRESHOLDS, "psiFail": 0.30}),
    snapshot_item("blue-harbor-bank", "churn-predictor", "1", "job-bhbfail01", "RUN-0002",
                  _dq_failed_output, "Failed", minutes_ago=30),
]

# ---------------------------------------------------------------------------
# Audit events
# ---------------------------------------------------------------------------

def audit_item(tenant_id, minutes_ago, actor, actor_role, action, entity_type,
               entity_id, summary, suffix):
    when = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    timestamp = when.isoformat()
    event_id = f"seed{suffix:04d}"
    return {
        "tenant_id": tenant_id, "sk": f"{timestamp}#{event_id}",
        "event_id": event_id, "timestamp": timestamp,
        "actor": actor, "actorRole": actor_role, "action": action,
        "entityType": entity_type, "entityId": entity_id, "summary": summary,
        "entity_pk": f"{entity_type}#{entity_id}",
        "event_date": when.strftime("%Y-%m-%d"),
    }


AUDIT_EVENTS = [
    audit_item("PLATFORM", 60 * 24 * 30, SEED_USER, "PlatformAdmin", "tenant.create",
               "tenant", "acme-capital", "Created tenant 'Acme Capital' (acme-capital)", 1),
    audit_item("PLATFORM", 60 * 24 * 21, SEED_USER, "PlatformAdmin", "tenant.create",
               "tenant", "blue-harbor-bank", "Created tenant 'Blue Harbor Bank' (blue-harbor-bank)", 2),
    audit_item("PLATFORM", 60 * 24 * 7, SEED_USER, "PlatformAdmin", "tenant.suspend",
               "tenant", "old-north-trust", "Suspended tenant 'Old North Trust' (old-north-trust)", 3),
    audit_item("acme-capital", 60 * 48, SEED_USER, "LeadDataScientist", "pipeline.create",
               "pipeline", "pl-acmecred1", "Created pipeline 'Credit Risk Batch Scoring' (4 steps)", 4),
    audit_item("acme-capital", 60 * 24 * 5, SEED_USER, "LeadDataScientist", "model.promote",
               "model", "credit-risk-scorer#1", "stage: Staging -> Production", 5),
    audit_item("acme-capital", 95, SEED_USER, "LeadDataScientist", "job.create",
               "job", "job-acmeappr1", "Submitted job for pipeline 'Credit Risk Batch Scoring'", 6),
    audit_item("blue-harbor-bank", 60 * 12, SEED_USER, "LeadDataScientist", "pipeline.create",
               "pipeline", "pl-bhbchurn1", "Created pipeline 'Churn Propensity Scoring' (4 steps)", 7),
    audit_item("blue-harbor-bank", 35, SEED_USER, "LeadDataScientist", "job.create",
               "job", "job-bhbfail01", "Submitted job for pipeline 'Churn Propensity Scoring'", 8),
]


def main() -> None:
    endpoint = settings.DDB_ENDPOINT_URL or "(real AWS)"
    print(f"Seeding demo data against: {endpoint}")

    batches = [
        (settings.TABLE_TENANTS, TENANTS),
        (settings.TABLE_GROUP_MAPPINGS, GROUP_MAPPINGS),
        (settings.TABLE_PIPELINES, PIPELINES),
        (settings.TABLE_MODELS, MODELS),
        (settings.TABLE_JOBS, JOBS),
        (settings.TABLE_MONITORING_SNAPSHOTS, SNAPSHOTS),
        (settings.TABLE_AUDIT, AUDIT_EVENTS),
    ]
    for table_name, items in batches:
        table = get_table(table_name)
        for raw in items:
            table.put_item(Item=_to_ddb(raw))
        print(f"  seeded {len(items):3d} item(s) -> {table_name}")

    print("Demo data ready.")
    print("  Tenants: acme-capital, blue-harbor-bank (+ suspended old-north-trust)")
    print("  Jobs: 1 awaiting_approval, 1 success, 1 failed, 1 cancelled")
    print("  Snapshots: Passed / Rework / Failed across three models")


def _to_ddb(value):
    """Recursively convert floats to Decimal (DynamoDB requirement)."""
    from decimal import Decimal

    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_ddb(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_ddb(v) for v in value]
    return value


if __name__ == "__main__":
    main()
