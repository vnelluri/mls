"""Business logic for the Model Registry."""
from datetime import datetime, timezone
from typing import List, Optional

from app.core.exceptions import ConcurrentWriteError, conflict, not_found, tenant_mismatch
from app.repositories import model_repo
from app.schemas.common import CurrentUser
from app.schemas.model_registry import ModelPromoteRequest, ModelRegisterRequest
from app.services import audit_service

LEGAL_TRANSITIONS = {
    "None": {"Staging"},
    "Staging": {"Production", "Archived"},
    "Production": {"Archived"},
    "Archived": set(),
}


def register_model(current_user: CurrentUser, data: ModelRegisterRequest) -> dict:
    version = data.version
    existing = model_repo.get_model(current_user.tenant_id, data.model_name, version)
    if existing:
        raise conflict(
            f"Model '{data.model_name}' version {version} already exists for this tenant"
        )

    now = datetime.now(timezone.utc).isoformat()
    item = {
        "tenant_id": current_user.tenant_id,
        "model_name": data.model_name,
        "model_id": data.model_id,
        "version": version,
        "stage": "None",
        "framework": data.framework,
        "artifactS3Uri": data.artifactS3Uri,
        "description": data.description,
        "driftThresholdOverride": data.driftThresholdOverride,
        "errorRateThresholdOverride": data.errorRateThresholdOverride,
        # Per-feature training-time distributions (validated by the schema);
        # scoring runs compute PSI against these when present.
        "driftBaseline": (
            {name: fb.model_dump() for name, fb in data.driftBaseline.items()}
            if data.driftBaseline
            else None
        ),
        "currentMonitoringStatus": "NotStarted",
        "lastSnapshotAt": None,
        "registeredBy": current_user.user_id,
        "registeredAt": now,
        "promotedBy": None,
        "promotedAt": None,
        "all_pk": "ALL",
        "all_sk": f"{current_user.tenant_id}#{data.model_name}#{version}",
        "stage_sk": f"{current_user.tenant_id}#{data.model_name}",
    }
    try:
        item = model_repo.create_model(item)
    except ConcurrentWriteError:
        # The get_model pre-check above raced a concurrent registration.
        raise conflict(
            f"Model '{data.model_name}' version {version} already exists for this tenant"
        )
    audit_service.write_event(
        current_user.tenant_id,
        current_user.user_id,
        current_user.role,
        "model.register",
        "model",
        f"{data.model_name}#{version}",
        f"Registered model '{data.model_name}' v{version}",
    )
    return item


def get_model_scoped(current_user: CurrentUser, model_name: str, version: str, tenant_id: Optional[str] = None) -> dict:
    lookup_tenant = current_user.tenant_id or tenant_id
    if not lookup_tenant:
        raise conflict("tenant_id is required to look up a model as PlatformAdmin")
    item = model_repo.get_model(lookup_tenant, model_name, version)
    if not item:
        raise not_found("Model", f"{model_name}#{version}")
    return item


def list_models(current_user: CurrentUser) -> List[dict]:
    if current_user.sees_all_tenants:
        return model_repo.list_models_all_tenants()
    return sorted(
        model_repo.list_models_for_tenant(current_user.tenant_id),
        key=lambda m: (m.get("model_name", ""), str(m.get("version", ""))),
    )


def promote_model(current_user: CurrentUser, model_name: str, version: str, data: ModelPromoteRequest) -> dict:
    item = model_repo.get_model(current_user.tenant_id, model_name, version)
    if not item:
        raise not_found("Model", f"{model_name}#{version}")
    if item["tenant_id"] != current_user.tenant_id:
        raise tenant_mismatch("model")

    current_stage = item.get("stage", "None")
    target_stage = data.targetStage
    if target_stage not in LEGAL_TRANSITIONS.get(current_stage, set()):
        raise conflict(f"Illegal stage transition: {current_stage} -> {target_stage}")

    # Governance gate: monitoring evidence blocks Production. `Failed` means
    # the latest run breached fail thresholds; `InReview` means a warning-zone
    # run is still awaiting a reviewer's decision. (`Rework` — acknowledged
    # warning zone — and `NotStarted` — no evidence yet — do not block.)
    if target_stage == "Production":
        monitoring_status = item.get("currentMonitoringStatus", "NotStarted")
        if monitoring_status in ("Failed", "InReview"):
            raise conflict(
                f"Cannot promote to Production while monitoring status is "
                f"'{monitoring_status}' — resolve monitoring first"
            )

    now = datetime.now(timezone.utc).isoformat()
    try:
        # Conditional on the stage still being the one we validated the
        # transition from -- a concurrent stage change loses cleanly as 409
        # instead of last-writer-wins, and the monitoring fields on the item
        # are never touched by this write.
        item = model_repo.update_stage(
            current_user.tenant_id, model_name, version,
            target_stage, expected_stage=current_stage,
            promoted_by=current_user.user_id, promoted_at=now,
        )
    except ConcurrentWriteError:
        raise conflict(
            f"Model '{model_name}' v{version} stage changed concurrently -- reload and retry"
        )

    audit_service.write_event(
        current_user.tenant_id,
        current_user.user_id,
        current_user.role,
        "model.promote",
        "model",
        f"{model_name}#{version}",
        f"stage: {current_stage} -> {target_stage}",
    )
    return item
