"""Business logic for Pipeline CRUD."""
import random
import re
import string
from datetime import datetime, timezone
from typing import List, Optional

from pydantic import ValidationError

from app.core.exceptions import bad_request, conflict, not_found, tenant_mismatch
from app.repositories import job_repo, model_repo, pipeline_repo, tenant_repo
from app.schemas.common import CurrentUser
from app.schemas.pipeline import ALLOWED_STEP_TYPES, CONFIG_MODEL_BY_TYPE, PipelineCreate, PipelineUpdate
from app.services import audit_service

# ServiceNow record numbers: a known task-type prefix followed by the numeric
# id (e.g. CHG0031245, RITM0012003). Promotion is a change-management action,
# so the ticket is required and validated up front — it is the audit anchor.
SERVICENOW_TICKET_RE = re.compile(r"^(CHG|RITM|INC|REQ|TASK)\d{6,10}$", re.IGNORECASE)


def _gen_pipeline_id() -> str:
    return "pl-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))


# The execution engine (job_service._run_cascade) runs steps strictly in list
# order, one of each type, with approval as the terminal human gate. Enforce
# that shape at save time so a pipeline can never be stored that the engine
# would silently truncate or mis-order.
CANONICAL_STEP_ORDER = ["data_pipeline", "execute_model", "data_quality_check", "approval"]


def _validate_step_shape(normalized: List[dict]) -> None:
    seen_types = [s["type"] for s in normalized]
    duplicates = {t for t in seen_types if seen_types.count(t) > 1}
    if duplicates:
        raise bad_request(
            f"Pipeline may contain at most one step of each type — duplicated: {sorted(duplicates)}"
        )

    order_indices = [CANONICAL_STEP_ORDER.index(t) for t in seen_types]
    if order_indices != sorted(order_indices):
        raise bad_request(
            "Pipeline steps must follow the order "
            f"{' -> '.join(CANONICAL_STEP_ORDER)} (each step optional, approval always last)"
        )

    seen_ids = [s["step_id"] for s in normalized]
    dup_ids = {i for i in seen_ids if seen_ids.count(i) > 1}
    if dup_ids:
        raise bad_request(f"Step ids must be unique — duplicated: {sorted(dup_ids)}")

    # dependsOn is declarative today (execution is sequential), but a stored
    # reference must at least point at an EARLIER step so the declared graph
    # never contradicts the engine's actual order.
    earlier: set = set()
    for step in normalized:
        unknown = [d for d in step["dependsOn"] if d not in earlier]
        if unknown:
            raise bad_request(
                f"Step '{step['step_id']}': dependsOn must reference earlier steps "
                f"(invalid: {unknown})"
            )
        earlier.add(step["step_id"])


# execute_model fields the platform resolves at run time (tenant execution
# config / EMR_ENTRYPOINT_S3_URI). Author-supplied values are rejected, not
# ignored: silently dropping them would let someone believe they chose the
# execution role.
_PLATFORM_MANAGED_EM_FIELDS = ("emrApplicationId", "executionRoleArn", "entryPointS3Uri")

# Which config fields must live under the tenant's dataS3Prefix, per step type.
_TENANT_URI_FIELDS = {
    "data_pipeline": ("destinationS3Uri",),
    "execute_model": ("inputS3Uri", "outputS3Uri"),
    "data_quality_check": ("inputS3Uri",),
}


def _validate_execute_model_step(idx: int, config: dict, tenant_id: str) -> None:
    supplied = [f for f in _PLATFORM_MANAGED_EM_FIELDS if (config.get(f) or "").strip()]
    if supplied:
        raise bad_request(
            f"Step {idx} ('execute_model'): {', '.join(supplied)} are platform-managed — "
            "they are resolved from the tenant's execution config when the step runs "
            "and cannot be set by pipeline authors"
        )
    model = model_repo.get_model(tenant_id, config["modelName"], config["modelVersion"])
    if not model:
        raise bad_request(
            f"Step {idx} ('execute_model'): model '{config['modelName']}' "
            f"v{config['modelVersion']} is not registered in this tenant — "
            "register it via POST /models first"
        )


def _validate_tenant_uris(idx: int, step_type: str, config: dict, data_prefix: str) -> None:
    for field in _TENANT_URI_FIELDS.get(step_type, ()):
        value = config.get(field) or ""
        if not value.startswith(data_prefix):
            raise bad_request(
                f"Step {idx} ('{step_type}'): {field} '{value}' is outside the tenant's "
                f"data area — every pipeline S3 URI must start with '{data_prefix}'"
            )


def _validate_and_normalize_steps(steps_in: List[dict], tenant_id: str) -> List[dict]:
    if not steps_in:
        raise bad_request("Pipeline must have at least one step")

    tenant = tenant_repo.get_tenant(tenant_id) or {}
    data_prefix = (tenant.get("execution") or {}).get("dataS3Prefix")

    normalized = []
    for idx, step in enumerate(steps_in):
        step_type = step.get("type") if isinstance(step, dict) else step.type
        if step_type not in ALLOWED_STEP_TYPES:
            raise bad_request(
                f"Step {idx}: type '{step_type}' is not one of {sorted(ALLOWED_STEP_TYPES)}"
            )
        config = step.get("config") if isinstance(step, dict) else step.config
        model_cls = CONFIG_MODEL_BY_TYPE[step_type]
        try:
            validated_config = model_cls(**config)
        except ValidationError as exc:
            raise bad_request(f"Step {idx} ('{step_type}') config invalid: {exc}")

        # Check names become DynamoDB map keys in the job step's output
        # (dataQualityDetails) — empty keys are not storable.
        if step_type == "data_quality_check":
            for c_idx, check in enumerate(validated_config.checks):
                if not check.name.strip():
                    raise bad_request(
                        f"Step {idx} ('data_quality_check'): check {c_idx + 1} needs a non-empty name"
                    )

        step_id = (step.get("step_id") if isinstance(step, dict) else step.step_id) or f"step-{idx+1}"
        depends_on = (step.get("dependsOn") if isinstance(step, dict) else step.dependsOn) or []
        normalized.append(
            {
                "step_id": step_id,
                "type": step_type,
                "config": validated_config.model_dump(),
                "dependsOn": list(depends_on),
            }
        )

    _validate_step_shape(normalized)

    # Semantic gates after the structural ones (clearer errors: a malformed
    # pipeline complains about its shape, not about a model lookup).
    for idx, step in enumerate(normalized):
        if step["type"] == "execute_model":
            _validate_execute_model_step(idx, step["config"], tenant_id)
        if data_prefix:
            _validate_tenant_uris(idx, step["type"], step["config"], data_prefix)
    return normalized


def create_pipeline(current_user: CurrentUser, data: PipelineCreate) -> dict:
    steps = _validate_and_normalize_steps(
        [s.model_dump() for s in data.steps], current_user.tenant_id
    )
    now = datetime.now(timezone.utc).isoformat()
    pipeline_id = _gen_pipeline_id()

    item = {
        "tenant_id": current_user.tenant_id,
        "pipeline_id": pipeline_id,
        "name": data.name,
        "description": data.description,
        "version": 1,
        "status": "draft",
        # Born in staging: manual (reviewable) runs only until promoted to
        # production with a ServiceNow ticket — the ESP trigger rejects
        # staging pipelines.
        "environment": "staging",
        "promotedBy": None,
        "promotedAt": None,
        "serviceNowTicket": None,
        "requiresApproval": data.requiresApproval,
        "steps": steps,
        "createdBy": current_user.user_id,
        "createdAt": now,
        "updatedBy": current_user.user_id,
        "updatedAt": now,
        "all_pk": "ALL",
        "all_sk": f"{current_user.tenant_id}#{now}",
    }
    pipeline_repo.put_pipeline(item)
    audit_service.write_event(
        current_user.tenant_id,
        current_user.user_id,
        current_user.role,
        "pipeline.create",
        "pipeline",
        pipeline_id,
        f"Created pipeline '{data.name}' ({len(steps)} steps) in staging",
    )
    return item


def get_pipeline_scoped(current_user: CurrentUser, pipeline_id: str, tenant_id: Optional[str] = None) -> dict:
    """For admin, tenant_id must be provided (admin has no home tenant); for
    tenant-scoped roles, always use their own tenant regardless of any
    tenant_id argument."""
    lookup_tenant = current_user.tenant_id or tenant_id
    if not lookup_tenant:
        raise bad_request("tenant_id is required to look up a pipeline as PlatformAdmin")
    item = pipeline_repo.get_pipeline(lookup_tenant, pipeline_id)
    if not item:
        raise not_found("Pipeline", pipeline_id)
    return item


def list_pipelines(current_user: CurrentUser) -> List[dict]:
    if current_user.sees_all_tenants:
        return pipeline_repo.list_pipelines_all_tenants()
    return sorted(
        pipeline_repo.list_pipelines_for_tenant(current_user.tenant_id),
        key=lambda p: p.get("updatedAt", ""),
        reverse=True,
    )


def update_pipeline(current_user: CurrentUser, pipeline_id: str, data: PipelineUpdate) -> dict:
    item = pipeline_repo.get_pipeline(current_user.tenant_id, pipeline_id)
    if not item:
        raise not_found("Pipeline", pipeline_id)
    if item["tenant_id"] != current_user.tenant_id:
        raise tenant_mismatch("pipeline")

    if data.name is not None:
        item["name"] = data.name
    if data.description is not None:
        item["description"] = data.description
    if data.requiresApproval is not None:
        item["requiresApproval"] = data.requiresApproval
    if data.steps is not None:
        item["steps"] = _validate_and_normalize_steps(
            [s.model_dump() for s in data.steps], current_user.tenant_id
        )
    if data.status is not None:
        if item["status"] == "draft" and data.status not in ("draft", "active"):
            raise bad_request("A draft pipeline may only move to 'active' (or stay 'draft')")
        item["status"] = data.status

    item["version"] = int(item.get("version", 1)) + 1
    now = datetime.now(timezone.utc).isoformat()
    item["updatedBy"] = current_user.user_id
    item["updatedAt"] = now
    item["all_sk"] = f"{current_user.tenant_id}#{now}"

    pipeline_repo.put_pipeline(item)
    audit_service.write_event(
        current_user.tenant_id,
        current_user.user_id,
        current_user.role,
        "pipeline.update",
        "pipeline",
        pipeline_id,
        f"Updated pipeline '{item['name']}' -> version {item['version']}",
    )
    return item


def promote_pipeline(current_user: CurrentUser, pipeline_id: str, service_now_ticket: str) -> dict:
    """Promote a reviewed staging pipeline to production.

    Gates:
      * a valid ServiceNow ticket is mandatory — it is stored on the pipeline
        and written to the audit log (change-management evidence);
      * the pipeline must have at least one successful job run — promotion is
        only allowed after a staging run has been reviewed end-to-end;
      * archived pipelines and pipelines already in production are rejected.

    Promotion also activates a draft pipeline: going to production *is* the
    go-live decision, so a separate draft->active update is not required.
    Only production pipelines can be triggered by the external scheduler
    (ESP) — see job_service.trigger_pipeline.
    """
    item = pipeline_repo.get_pipeline(current_user.tenant_id, pipeline_id)
    if not item:
        raise not_found("Pipeline", pipeline_id)
    if item["tenant_id"] != current_user.tenant_id:
        raise tenant_mismatch("pipeline")

    ticket = (service_now_ticket or "").strip().upper()
    if not SERVICENOW_TICKET_RE.match(ticket):
        raise bad_request(
            "A valid ServiceNow ticket is required to promote to production "
            "(e.g. CHG0031245, RITM0012003, INC0045678)"
        )

    if item.get("status") == "archived":
        raise conflict("An archived pipeline cannot be promoted to production")
    if item.get("environment", "staging") == "production":
        raise conflict(f"Pipeline '{pipeline_id}' is already in production")

    # New activity stamps lastSuccessfulRunAt on the pipeline (job_service),
    # so this is normally a field read; the job-history scan only remains as
    # a fallback for pipelines whose successful runs predate the stamp.
    has_reviewed_run = bool(item.get("lastSuccessfulRunAt")) or any(
        j.get("pipeline_id") == pipeline_id and j.get("status") == "success"
        for j in job_repo.list_jobs_for_tenant(current_user.tenant_id)
    )
    if not has_reviewed_run:
        raise conflict(
            "Pipeline has no successful staging run yet — run it and review the "
            "results before promoting to production"
        )

    now = datetime.now(timezone.utc).isoformat()
    item["environment"] = "production"
    item["promotedBy"] = current_user.user_id
    item["promotedAt"] = now
    item["serviceNowTicket"] = ticket
    if item.get("status") == "draft":
        item["status"] = "active"
    item["updatedBy"] = current_user.user_id
    item["updatedAt"] = now
    item["all_sk"] = f"{current_user.tenant_id}#{now}"
    pipeline_repo.put_pipeline(item)

    audit_service.write_event(
        current_user.tenant_id,
        current_user.user_id,
        current_user.role,
        "pipeline.promote",
        "pipeline",
        pipeline_id,
        f"Promoted pipeline '{item['name']}' to production (ServiceNow {ticket})",
    )
    return item


def archive_pipeline(current_user: CurrentUser, pipeline_id: str) -> dict:
    item = pipeline_repo.get_pipeline(current_user.tenant_id, pipeline_id)
    if not item:
        raise not_found("Pipeline", pipeline_id)
    if item["tenant_id"] != current_user.tenant_id:
        raise tenant_mismatch("pipeline")

    item["status"] = "archived"
    now = datetime.now(timezone.utc).isoformat()
    item["updatedBy"] = current_user.user_id
    item["updatedAt"] = now
    item["all_sk"] = f"{current_user.tenant_id}#{now}"
    pipeline_repo.put_pipeline(item)

    audit_service.write_event(
        current_user.tenant_id,
        current_user.user_id,
        current_user.role,
        "pipeline.archive",
        "pipeline",
        pipeline_id,
        f"Archived pipeline '{item['name']}'",
    )
    return item
