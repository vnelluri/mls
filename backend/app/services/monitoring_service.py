"""
Monitoring snapshot derivation and persistence.

`derive_status` implements the status rules EXACTLY as specified:

  Failed    if maxPsi >= psiFailThreshold OR errorRate >= errorRateFailThreshold OR dataQualityPassed == False
  Rework    if not Failed and (maxPsi >= psiWarnThreshold OR errorRate >= errorRateWarnThreshold)
  Passed    otherwise
  InReview  reserved -- never produced by this automatic deriver in v1
  NotStarted  never stored in a snapshot row -- it's the Model's default before any snapshot exists

Global default thresholds (config.py, env-var overridable): PSI_WARN=0.10,
PSI_FAIL=0.25, ERROR_RATE_WARN=0.05, ERROR_RATE_FAIL=0.15. Per-model
overrides (`driftThresholdOverride` / `errorRateThresholdOverride`) only
override the FAIL threshold when set -- warn thresholds always stay global,
by design (not scaled proportionally, kept simple for v1).
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.config import settings
from app.repositories import model_repo, monitoring_repo
from app.schemas.common import CurrentUser

DerivedStatus = str  # Literal["Passed", "Failed", "Rework", "InReview", "NotStarted"]


def resolve_thresholds(model: dict) -> Dict[str, float]:
    psi_fail = settings.PSI_FAIL
    error_rate_fail = settings.ERROR_RATE_FAIL

    override_psi = model.get("driftThresholdOverride")
    if override_psi is not None:
        psi_fail = float(override_psi)

    override_error_rate = model.get("errorRateThresholdOverride")
    if override_error_rate is not None:
        error_rate_fail = float(override_error_rate)

    return {
        "psiWarn": settings.PSI_WARN,
        "psiFail": psi_fail,
        "errorRateWarn": settings.ERROR_RATE_WARN,
        "errorRateFail": error_rate_fail,
    }


def derive_status(
    max_psi: float,
    error_rate: float,
    data_quality_passed: bool,
    thresholds: Dict[str, float],
) -> DerivedStatus:
    if (
        max_psi >= thresholds["psiFail"]
        or error_rate >= thresholds["errorRateFail"]
        or not data_quality_passed
    ):
        return "Failed"
    if max_psi >= thresholds["psiWarn"] or error_rate >= thresholds["errorRateWarn"]:
        return "Rework"
    return "Passed"


def record_snapshot(
    tenant_id: str,
    model_name: str,
    version: str,
    job_id: str,
    run_id: str,
    dq_result: dict,
) -> dict:
    """Builds and persists a MonitoringSnapshot from a completed
    data_quality_check step's result, then updates the Model's denormalized
    currentMonitoringStatus/lastSnapshotAt. Called only internally by
    job_service -- never exposed as a write endpoint."""

    model = model_repo.get_model(tenant_id, model_name, version)
    thresholds = resolve_thresholds(model) if model else resolve_thresholds({})

    drift_metrics = dq_result.get("driftMetrics", {})
    max_psi = max(drift_metrics.values()) if drift_metrics else 0.0
    error_rate = dq_result.get("errorRate", 0.0)
    data_quality_passed = dq_result.get("dataQualityPassed", True)

    status = derive_status(max_psi, error_rate, data_quality_passed, thresholds)
    recorded_at = datetime.now(timezone.utc).isoformat()

    snapshot = {
        "tenant_id": tenant_id,
        "model_name": model_name,
        "version": version,
        "job_id": job_id,
        "run_id": run_id,
        "recordedAt": recorded_at,
        "requestCount": dq_result.get("requestCount", 0),
        "avgLatencyMs": dq_result.get("avgLatencyMs", 0.0),
        "errorRate": error_rate,
        "driftMetrics": drift_metrics,
        "maxPsi": max_psi,
        "dataQualityPassed": data_quality_passed,
        "dataQualityDetails": dq_result.get("dataQualityDetails", {}),
        "derivedStatus": status,
        "thresholdsUsed": thresholds,
        "all_pk": "ALL",
        "model_trend_pk": f"{tenant_id}#{model_name}#{version}",
    }
    # One transaction: snapshot + the model's denormalized monitoring status
    # commit or fail together (and at most one snapshot per run — a racing
    # duplicate returns the row that won). The model update is field-level,
    # so it can't clobber a concurrent stage promotion.
    return monitoring_repo.record_snapshot_with_model_status(snapshot, update_model=bool(model))


def set_model_status(
    tenant_id: str,
    model_name: str,
    version: str,
    status: DerivedStatus,
    actor: str,
    actor_role: str,
    reason: str,
) -> Optional[dict]:
    """Explicit monitoring-status transition on the Model, with an audit row.

    Used by the review loop (job_service): `InReview` when a warning-zone
    (Rework) run reaches an approval gate, then `Passed`/`Rework` when the
    reviewer approves/rejects. Snapshot-driven updates keep going through
    record_snapshot — this never writes a snapshot.
    """
    from app.services import audit_service  # local import to avoid a cycle

    previous = (model_repo.get_model(tenant_id, model_name, version) or {}).get(
        "currentMonitoringStatus", "NotStarted"
    )
    # Conditional on the status actually changing: a racing duplicate call
    # (e.g. two refresh passes both reaching the approval gate) no-ops here
    # instead of writing a duplicate audit row.
    updated = model_repo.update_monitoring_status(
        tenant_id, model_name, version, status, expect_changed=True
    )
    if updated is None:
        return None  # model missing, or status already had this value
    audit_service.write_event(
        tenant_id, actor, actor_role,
        "model.monitoring_status", "model", f"{model_name}#{version}",
        f"Monitoring status: {previous} -> {status} ({reason})",
    )
    return updated


def list_snapshots(
    current_user: CurrentUser,
    model_name: Optional[str] = None,
    version: Optional[str] = None,
) -> List[dict]:
    """Tenant-scoped snapshot listing (all tenants for PlatformAdmin), with
    optional in-memory filtering by model name/version. Snapshot volume is
    one-per-run, so in-memory filtering is fine at this scale."""
    if current_user.sees_all_tenants:
        items = monitoring_repo.list_snapshots_all_tenants()
    else:
        items = monitoring_repo.list_snapshots_for_tenant(current_user.tenant_id)

    if model_name is not None:
        items = [s for s in items if s.get("model_name") == model_name]
    if version is not None:
        items = [s for s in items if str(s.get("version", "")) == version]
    # The main-table sk is no longer time-ordered (it's run-scoped for
    # idempotence), so order newest-first explicitly.
    return sorted(items, key=lambda s: s.get("recordedAt", ""), reverse=True)


def model_trend(
    current_user: CurrentUser,
    model_name: str,
    version: str,
    tenant_id: Optional[str] = None,
) -> List[dict]:
    """Snapshot history for one (model, version), newest first — served from
    the model-trend-index (range key recordedAt), so it stays a single Query
    however large the tenant's overall snapshot volume grows. Tenantless
    roles (PlatformAdmin/Operator) name the tenant via ?tenantId=."""
    from app.core.exceptions import bad_request  # local import: keep module deps minimal

    lookup_tenant = current_user.tenant_id or tenant_id
    if not lookup_tenant:
        raise bad_request("tenantId query param is required to view a model trend as PlatformAdmin/Operator")
    return monitoring_repo.list_trend_for_model(lookup_tenant, model_name, version)


def dashboard(current_user: CurrentUser) -> dict:
    """Counts of registered models per currentMonitoringStatus — the
    status-grid on the Monitoring Dashboard. Cross-tenant aggregate for
    PlatformAdmin, own-tenant otherwise."""
    if current_user.sees_all_tenants:
        models = model_repo.list_models_all_tenants()
    else:
        models = model_repo.list_models_for_tenant(current_user.tenant_id)

    counts = {"Passed": 0, "Failed": 0, "Rework": 0, "InReview": 0, "NotStarted": 0}
    for m in models:
        status = m.get("currentMonitoringStatus", "NotStarted")
        counts[status] = counts.get(status, 0) + 1
    return {"counts": counts, "totalModels": len(models)}
