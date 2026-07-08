"""
Job lifecycle: submit, refresh/poll, stop, retry, approve/reject step.

Step progression cascade (`_run_cascade`) walks the job's steps in the fixed
order snapshotted from the pipeline at submit time:

    data_pipeline -> execute_model -> data_quality_check -> [approval]

Steps execute one at a time. data_pipeline (Snowflake unload) and
execute_model (EMR run) start external compute and are completed by status
polls on each refresh pass (the detail-page GET or the background loop);
data_quality_check is timer-driven (STEP_DURATION_SECONDS in mock mode) and
produces its output at completion. No thread is ever held while a step
"runs" — long external work is polled, never awaited.
"""
import copy
import hashlib
import logging
import random
import string
from datetime import datetime, timezone
from typing import List, Optional

from app.config import settings
from app.core.exceptions import ConcurrentWriteError, bad_request, conflict, forbidden, not_found, tenant_mismatch
from app.repositories import job_repo, model_repo, monitoring_repo, pipeline_repo, tenant_repo
from app.schemas.common import CurrentUser
from app.schemas.job import JobCreate
from app.services import audit_service, job_runner, monitoring_service
from app.services.data_pipeline_service import get_data_pipeline_service
from app.services.data_quality_service import get_data_quality_service
from app.services.emr_execution_service import get_emr_execution_service

logger = logging.getLogger(__name__)

TERMINAL_JOB_STATUSES = {"success", "failed", "cancelled"}
STOPPABLE_JOB_STATUSES = {"running", "awaiting_approval", "pending"}
# A successful job can be run again (next sequential run id) — every run's
# results live under their own <date>/<runId>/ prefix, so reruns are safe.
RERUNNABLE_JOB_STATUSES = {"failed", "cancelled", "success"}
# Resume keeps completed steps, so it only applies to interrupted runs.
RESUMABLE_JOB_STATUSES = {"failed", "cancelled"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gen_job_id() -> str:
    return "job-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))


def _idempotent_job_id(tenant_id: str, idempotency_key: str) -> str:
    """Deterministic job id for an Idempotency-Key trigger: a scheduler retry
    derives the same id, so the conditional create in job_repo settles the
    race -- exactly one job can ever exist for a (tenant, key)."""
    digest = hashlib.sha256(f"{tenant_id}:{idempotency_key}".encode("utf-8")).hexdigest()
    return f"job-{digest[:12]}"


def _cancel_emr_runs_lost_to_race(item: dict) -> None:
    """Our job write lost the optimistic lock AFTER we may have started
    external compute (EMR runs, Snowflake unloads) for cascade-advanced
    steps. Any external run/query id present only in our (losing) in-memory
    copy is compute nobody's persisted state references — an orphan burning
    cost and, worse, a second writer into the same output prefix. Cancel it,
    best-effort."""
    try:
        fresh = job_repo.get_job(item["tenant_id"], item["job_id"])
    except Exception:
        logger.exception("Could not re-read job %s for orphan-run cleanup", item.get("job_id"))
        return
    fresh_steps = (fresh or {}).get("steps", [])
    persisted_run_ids = {s.get("emrJobRunId") for s in fresh_steps}
    persisted_query_ids = {s.get("snowflakeQueryId") for s in fresh_steps}
    for step in item["steps"]:
        run_id = step.get("emrJobRunId")
        if step["type"] == "execute_model" and run_id and run_id not in persisted_run_ids:
            logger.warning("Cancelling orphaned EMR run %s (job %s lost a write race)", run_id, item["job_id"])
            _cancel_emr_run(step)
        query_id = step.get("snowflakeQueryId")
        if step["type"] == "data_pipeline" and query_id and query_id not in persisted_query_ids:
            logger.warning("Cancelling orphaned Snowflake query %s (job %s lost a write race)", query_id, item["job_id"])
            _cancel_pipeline_query(step)


def _persist_job_action(item: dict) -> dict:
    """Persist a user/scheduler-initiated job mutation. Losing the optimistic
    lock means someone else changed the job between our read and write --
    surface that as 409 rather than silently clobbering their update."""
    try:
        result = job_repo.put_job(item)
    except ConcurrentWriteError:
        _cancel_emr_runs_lost_to_race(item)
        raise conflict("The job was modified concurrently — reload it and retry the action")
    _note_job_success(item)
    return result


def _persist_refresh(item: dict) -> bool:
    """Persist a refresh-pass mutation. Losing the lock just means another
    refresher (the per-GET path or the loop in another API task) already
    advanced the job -- drop our copy; theirs is the truth."""
    try:
        job_repo.put_job(item)
    except ConcurrentWriteError:
        logger.info("Refresh write for job %s lost to a concurrent writer — dropped", item.get("job_id"))
        _cancel_emr_runs_lost_to_race(item)
        return False
    _note_job_success(item)
    return True


def _note_job_success(item: dict) -> None:
    """A run just persisted as `success`: stamp its pipeline's
    lastSuccessfulRunAt so promotion eligibility is a field read, not a scan
    over the tenant's job history. Best-effort — the job result itself is the
    source of truth and promote_pipeline falls back to it."""
    if item.get("status") != "success":
        return
    try:
        pipeline_repo.record_successful_run(item["tenant_id"], item["pipeline_id"], _now())
    except Exception:
        logger.exception("Failed to stamp successful run on pipeline %s", item.get("pipeline_id"))


def _next_run_id(item: dict) -> str:
    """Sequential per-job run id: RUN-0001 for the first run, then one per
    restart/resume. Call AFTER the previous run was appended to runHistory."""
    return f"RUN-{len(item.get('runHistory', [])) + 1:04d}"


# How many archived runs keep full step detail (older entries keep only
# status/timestamps) so a much-retried job stays well under DynamoDB's 400KB
# item ceiling.
RUN_HISTORY_STEP_DETAIL_LIMIT = 10


def _archive_current_run(item: dict, now: str) -> None:
    """Snapshot the ending run into runHistory BEFORE its steps are reset.
    Step outputs, error messages and EMR run ids are the evidence an incident
    review (or a regulator) asks for — monitoring snapshots alone don't carry
    them, and retry/resume overwrite the live step array."""
    history = item.setdefault("runHistory", [])
    history.append(
        {
            "run_id": item["run_id"],
            "startedAt": item.get("submittedAt", now),
            "endedAt": now,
            "finalStatus": item["status"],
            "steps": copy.deepcopy(item["steps"]),
        }
    )
    for entry in history[:-RUN_HISTORY_STEP_DETAIL_LIMIT]:
        entry.pop("steps", None)


def _blank_step(pipeline_step: dict) -> dict:
    return {
        "step_id": pipeline_step["step_id"],
        "type": pipeline_step["type"],
        "status": "idle",
        "startedAt": None,
        "completedAt": None,
        "emrJobRunId": None,
        "emrStateDetail": None,
        "snowflakeQueryId": None,
        "errorMessage": None,
        "output": None,
        "config": pipeline_step.get("config"),
    }


# --------------------------------------------------------------------------
# Step execution helpers (dummy runner: every step runs STEP_DURATION_SECONDS)
# --------------------------------------------------------------------------

RUNNABLE_STEP_TYPES = ("data_pipeline", "execute_model", "data_quality_check")


def _elapsed_seconds(started_at_iso: str) -> float:
    started_at = datetime.fromisoformat(started_at_iso)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - started_at).total_seconds()


def _start_step(item: dict, step: dict) -> None:
    """Start a step. execute_model and data_pipeline kick off external
    compute (EMR run / Snowflake query) and are completed by status polls;
    data_quality_check is timer-driven (STEP_DURATION_SECONDS)."""
    step["status"] = "running"
    step["startedAt"] = _now()
    if step["type"] == "execute_model":
        result = get_emr_execution_service().start(step["config"])
        step["emrJobRunId"] = result["emrJobRunId"]
        step["emrStateDetail"] = "RUNNING"
    elif step["type"] == "data_pipeline":
        result = get_data_pipeline_service().start(step["config"])
        step["snowflakeQueryId"] = result["queryId"]
    job_runner.start_step(item, step)


def _complete_execute_model_step(item: dict, step: dict, state_detail: str) -> None:
    step["completedAt"] = _now()
    step["status"] = "succeeded"
    step["emrStateDetail"] = "SUCCESS"
    output = {"emrState": "SUCCESS", "emrStateDetail": state_detail}
    # Results are partitioned per run: <outputS3Uri>/<date>/<runId>/.
    out_uri = (step.get("config") or {}).get("outputS3Uri")
    if out_uri:
        output["resultsS3Prefix"] = f"{out_uri.rstrip('/')}/{_now()[:10]}/{item['run_id']}/"
    step["output"] = output


def _fail_step(item: dict, step: dict, message: str) -> None:
    step["status"] = "failed"
    step["completedAt"] = _now()
    step["errorMessage"] = message
    item["status"] = "failed"


def _poll_emr_status(step: dict) -> dict:
    """Poll the EMR executor for the step's job-run state. A poll failure is
    treated as still-running (the next refresh retries; the step timeout is
    the backstop), never as step failure."""
    try:
        return get_emr_execution_service().get_status(
            step.get("emrJobRunId") or "", step.get("startedAt"), step.get("config")
        )
    except Exception:
        logger.exception("EMR status poll failed for run %s -- retrying next pass", step.get("emrJobRunId"))
        return {"state": "RUNNING", "stateDetail": "Status poll failed; will retry"}


def _cancel_emr_run(step: dict) -> None:
    """Best-effort EMR cancellation (stop_job / step timeout)."""
    if not step.get("emrJobRunId"):
        return
    try:
        get_emr_execution_service().cancel(step["emrJobRunId"], step.get("config"))
        step["emrStateDetail"] = "CANCELLING"
    except Exception:
        logger.exception("Failed to cancel EMR job run %s", step.get("emrJobRunId"))


def _cancel_pipeline_query(step: dict) -> None:
    """Best-effort Snowflake query cancellation (stop_job / step timeout)."""
    if not step.get("snowflakeQueryId"):
        return
    try:
        get_data_pipeline_service().cancel(step["snowflakeQueryId"], step.get("config"))
    except Exception:
        logger.exception("Failed to cancel Snowflake query %s", step.get("snowflakeQueryId"))


def _poll_pipeline_status(step: dict) -> dict:
    """Poll the data-pipeline executor for the step's query state. A poll
    failure is treated as still-running (the next refresh retries; the step
    timeout is the backstop), never as step failure."""
    try:
        return get_data_pipeline_service().get_status(
            step.get("snowflakeQueryId") or "", step.get("startedAt"), step.get("config")
        )
    except Exception:
        logger.exception(
            "Snowflake status poll failed for query %s -- retrying next pass",
            step.get("snowflakeQueryId"),
        )
        return {"state": "RUNNING", "stateDetail": "Status poll failed; will retry"}


def _job_model_ref(item: dict) -> Optional[tuple]:
    """(model_name, version) this run scores with, from the execute_model
    step's snapshotted config — or None if the pipeline names no model."""
    exec_step = next((s for s in item["steps"] if s["type"] == "execute_model"), None)
    if not exec_step or not exec_step.get("config"):
        return None
    model_name = exec_step["config"].get("modelName")
    model_version = exec_step["config"].get("modelVersion")
    if model_name and model_version is not None:
        return model_name, model_version
    return None


def _monitoring_failure_reason(snapshot: dict) -> str:
    thresholds = snapshot.get("thresholdsUsed", {})
    reasons = []
    if not snapshot.get("dataQualityPassed", True):
        reasons.append("data quality checks failed")
    if snapshot.get("maxPsi", 0.0) >= thresholds.get("psiFail", float("inf")):
        reasons.append(f"max PSI {snapshot['maxPsi']} >= {thresholds['psiFail']}")
    if snapshot.get("errorRate", 0.0) >= thresholds.get("errorRateFail", float("inf")):
        reasons.append(f"error rate {snapshot['errorRate']} >= {thresholds['errorRateFail']}")
    return "Monitoring failed: " + "; ".join(reasons or ["thresholds breached"])


def _execute_data_quality_step(item: dict, step: dict) -> bool:
    """Returns True if the job should keep advancing, False if it just failed
    the job.

    The snapshot's *derived* monitoring status decides the outcome — not just
    the raw DQ-check booleans: `Failed` (drift past the fail threshold, error
    rate past the fail threshold, or DQ checks failed) fails the job;
    `Rework`/`Passed` advance it. A `Rework` outcome that reaches a downstream
    approval step puts the model `InReview` (see _run_cascade)."""
    # With a registered baseline, drift is real PSI against it (seeded by the
    # run so a given run's numbers are reproducible); without one, the DQ
    # service falls back to synthetic drift.
    model_ref = _job_model_ref(item)
    drift_baseline = None
    if model_ref:
        model = model_repo.get_model(item["tenant_id"], model_ref[0], model_ref[1])
        drift_baseline = (model or {}).get("driftBaseline")
    drift_seed = f"{item['tenant_id']}:{item['job_id']}:{item['run_id']}"

    # Real DQ's row_count_delta compares against the previous run's row count
    # (= requestCount on the model's latest snapshot). Only fetched in real
    # mode; the mock ignores it.
    previous_row_count = None
    if model_ref and settings.DQ_MODE == "real":
        try:
            trend = monitoring_repo.list_trend_for_model(item["tenant_id"], model_ref[0], model_ref[1])
            if trend:
                previous_row_count = int(trend[0].get("requestCount") or 0) or None
        except Exception:
            logger.exception("Could not fetch previous row count for job %s", item["job_id"])

    dq_result = get_data_quality_service().execute(
        step["config"],
        drift_baseline=drift_baseline,
        drift_seed=drift_seed,
        previous_row_count=previous_row_count,
    )
    step["completedAt"] = _now()
    step["output"] = dq_result

    # Record the monitoring snapshot first (a failed run is itself meaningful
    # monitoring data) — its derived status drives the step outcome below.
    snapshot = None
    if model_ref:
        try:
            snapshot = monitoring_service.record_snapshot(
                item["tenant_id"], model_ref[0], model_ref[1], item["job_id"], item["run_id"], dq_result
            )
        except Exception:
            logger.exception("Failed to record monitoring snapshot for job %s", item["job_id"])

    if snapshot:
        derived = snapshot["derivedStatus"]
        step["output"] = {**dq_result, "derivedStatus": derived}
        passed = derived != "Failed"
        failure_message = _monitoring_failure_reason(snapshot) if not passed else None
    else:
        # No model to monitor — fall back to the raw DQ-check outcome.
        passed = dq_result.get("dataQualityPassed", True)
        failure_message = "Data quality checks failed" if not passed else None

    if passed:
        step["status"] = "succeeded"
    else:
        step["status"] = "failed"
        step["errorMessage"] = failure_message
        item["status"] = "failed"
    return passed


def _maybe_mark_in_review(item: dict) -> None:
    """A warning-zone (Rework) run just reached an approval gate: the model is
    now actively under human review — surface that as `InReview`."""
    dq_step = next((s for s in item["steps"] if s["type"] == "data_quality_check"), None)
    if not dq_step or not dq_step.get("output"):
        return
    if dq_step["output"].get("derivedStatus") != "Rework":
        return
    model_ref = _job_model_ref(item)
    if not model_ref:
        return
    try:
        monitoring_service.set_model_status(
            item["tenant_id"], model_ref[0], model_ref[1], "InReview",
            "system", "system",
            f"Rework run {item['run_id']} awaiting approval (job {item['job_id']})",
        )
    except Exception:
        logger.exception("Failed to mark model InReview for job %s", item["job_id"])


def _run_cascade(item: dict) -> None:
    """Advance the job: start the next idle step (steps run one at a time,
    each for STEP_DURATION_SECONDS via the dummy runner) or settle the final
    job status when nothing is left to run."""
    steps: List[dict] = item["steps"]
    for step in steps:
        status = step["status"]
        if status == "idle":
            step_type = step["type"]
            if step_type in RUNNABLE_STEP_TYPES:
                _start_step(item, step)
                item["status"] = "running"
                return
            if step_type == "approval":
                step["status"] = "awaiting_approval"
                item["status"] = "awaiting_approval"
                _maybe_mark_in_review(item)
                return
            # Unknown step type -- treat as a no-op success so we don't hang.
            step["status"] = "succeeded"
            continue
        elif status == "running":
            # Mid-execution — a later refresh completes it. Nothing to do now.
            return
        elif status in ("succeeded", "approved"):
            continue
        else:  # failed / rejected / awaiting_approval already handled above
            return

    if item["status"] not in ("failed", "awaiting_approval", "cancelled"):
        item["status"] = "success"


def _still_running_in_db(item: dict, step_id: str) -> bool:
    """Guard against the GET-refresh path and the background loop racing
    each other on stale in-memory copies: immediately before completing a
    step (which produces its output / monitoring snapshot exactly once per
    run), re-read the persisted job and only proceed if the step is still
    `running` there. If another writer already advanced it, adopt the fresh
    state instead of re-executing downstream steps."""
    fresh = job_repo.get_job(item["tenant_id"], item["job_id"])
    if not fresh:
        return True  # nothing persisted to defer to; proceed
    fresh_step = next((s for s in fresh["steps"] if s["step_id"] == step_id), None)
    if fresh_step is None or (fresh_step["status"] == "running" and fresh["run_id"] == item["run_id"]):
        return True
    item.clear()
    item.update(fresh)
    return False


def _complete_step(item: dict, step: dict) -> None:
    """A timer-driven step's STEP_DURATION_SECONDS window has elapsed:
    produce its output (which for data_quality_check may fail the job) and
    print the runner's FINISH line. execute_model and data_pipeline steps
    never come through here -- they complete via their status polls in
    _refresh_running_steps."""
    step_type = step["type"]
    if step_type == "data_quality_check":
        # An executor exception must FAIL the step, never escape: an escaped
        # exception would leave the step `running` and the refresh loop
        # re-raising forever.
        try:
            _execute_data_quality_step(item, step)
        except Exception as exc:
            logger.exception("data_quality_check step %s failed", step["step_id"])
            _fail_step(item, step, f"Data quality execution failed: {exc}")
    else:
        step["status"] = "succeeded"
        step["completedAt"] = _now()
    job_runner.finish_step(item, step)


def _refresh_execute_model_step(item: dict, step: dict) -> Optional[bool]:
    """Advance a running execute_model step from the EMR executor's actual
    job-run state (SUCCESS completes it, FAILED/CANCELLED fails the job,
    anything else keeps it running). Returns True if the item was mutated,
    False if not, and None if another writer already advanced this run (the
    caller must stop -- `item` now holds the adopted fresh state)."""
    emr_status = _poll_emr_status(step)
    state = emr_status.get("state", "RUNNING")

    if state == "SUCCESS":
        if not _still_running_in_db(item, step["step_id"]):
            return None
        _complete_execute_model_step(item, step, emr_status.get("stateDetail") or "Job run completed")
        job_runner.finish_step(item, step)
        _run_cascade(item)
        return True

    if state in ("FAILED", "CANCELLED"):
        if not _still_running_in_db(item, step["step_id"]):
            return None
        _fail_step(
            item, step,
            f"EMR job run ended in {state}: {emr_status.get('stateDetail') or 'no detail provided'}",
        )
        step["emrStateDetail"] = state
        job_runner.finish_step(item, step)
        return True

    # Still in flight -- persist only when the surfaced state name changes.
    if step.get("emrStateDetail") != state:
        step["emrStateDetail"] = state
        return True
    return False


def _refresh_data_pipeline_step(item: dict, step: dict) -> Optional[bool]:
    """Advance a running data_pipeline step from the executor's actual query
    state (SUCCESS completes it, FAILED/CANCELLED fails the job, anything
    else keeps it running). Returns True if the item was mutated, False if
    not, and None if another writer already advanced this run (the caller
    must stop -- `item` now holds the adopted fresh state)."""
    pipeline_status = _poll_pipeline_status(step)
    state = pipeline_status.get("state", "RUNNING")

    if state == "SUCCESS":
        if not _still_running_in_db(item, step["step_id"]):
            return None
        step["completedAt"] = _now()
        step["status"] = "succeeded"
        step["output"] = pipeline_status.get("output") or {
            "s3Uri": (step.get("config") or {}).get("destinationS3Uri")
        }
        job_runner.finish_step(item, step)
        _run_cascade(item)
        return True

    if state in ("FAILED", "CANCELLED"):
        if not _still_running_in_db(item, step["step_id"]):
            return None
        _fail_step(
            item, step,
            f"Data pipeline query ended in {state}: {pipeline_status.get('stateDetail') or 'no detail provided'}",
        )
        job_runner.finish_step(item, step)
        return True

    return False


def _refresh_running_steps(item: dict) -> bool:
    """Advances every `running` step: execute_model and data_pipeline from
    their executors' reported state, the timer-driven data_quality_check once
    STEP_DURATION_SECONDS has elapsed. Any step past STEP_TIMEOUT_SECONDS is
    failed outright (with a best-effort cancel of its external compute) so a
    stuck executor can't strand the job in `running` forever. Returns True if
    the job item was mutated (caller should persist)."""
    changed = False
    # Only steps already running when this pass began are eligible to
    # complete here; a step the cascade starts mid-pass waits for the next
    # refresh ("a later refresh completes it"). Completing it in the same
    # pass would trip the persisted-state guard -- the DB doesn't know the
    # step started yet -- and, with a step duration shorter than a refresh
    # pass, livelock the refresh by repeatedly discarding its own work.
    eligible = {s["step_id"] for s in item["steps"] if s["status"] == "running"}
    for step in item["steps"]:
        if step["step_id"] not in eligible:
            continue
        if step["status"] != "running" or not step.get("startedAt"):
            continue
        elapsed = _elapsed_seconds(step["startedAt"])

        if elapsed >= settings.STEP_TIMEOUT_SECONDS:
            if not _still_running_in_db(item, step["step_id"]):
                return False  # another writer already advanced this run
            if step["type"] == "execute_model":
                _cancel_emr_run(step)
            elif step["type"] == "data_pipeline":
                _cancel_pipeline_query(step)
            _fail_step(
                item, step,
                f"Step timed out after {int(elapsed)}s (STEP_TIMEOUT_SECONDS={settings.STEP_TIMEOUT_SECONDS})",
            )
            job_runner.finish_step(item, step)
            changed = True
            continue

        if step["type"] == "execute_model":
            result = _refresh_execute_model_step(item, step)
            if result is None:
                return False  # another writer already advanced this run
            changed = changed or result
            continue

        if step["type"] == "data_pipeline":
            result = _refresh_data_pipeline_step(item, step)
            if result is None:
                return False  # another writer already advanced this run
            changed = changed or result
            continue

        if elapsed < settings.STEP_DURATION_SECONDS:
            continue
        if not _still_running_in_db(item, step["step_id"]):
            return False  # another writer already advanced this run
        _complete_step(item, step)
        changed = True
        if step["status"] == "succeeded":
            _run_cascade(item)
    return changed


# --------------------------------------------------------------------------
# Public service API
# --------------------------------------------------------------------------

def _pipeline_model_ref(pipeline: dict) -> Optional[tuple]:
    """(model_name, version) the pipeline's execute_model step references."""
    exec_step = next((s for s in pipeline.get("steps", []) if s["type"] == "execute_model"), None)
    if not exec_step or not exec_step.get("config"):
        return None
    model_name = exec_step["config"].get("modelName")
    model_version = exec_step["config"].get("modelVersion")
    if model_name and model_version is not None:
        return model_name, model_version
    return None


def _resolve_run_environment(pipeline: dict) -> str:
    """The environment this run executes in — the pipeline's environment at
    the time the run starts. Pipelines are born in staging and flip to
    production when promoted (ServiceNow-ticketed); the ESP trigger
    additionally requires the referenced model to be in Production stage,
    but that model gate does not affect how a run is labeled."""
    return pipeline.get("environment", "staging")


def _new_job_item(pipeline: dict, tenant_id: str, submitted_by: str) -> dict:
    now = _now()
    return {
        "tenant_id": tenant_id,
        "job_id": _gen_job_id(),
        "pipeline_id": pipeline["pipeline_id"],
        "pipeline_version": pipeline["version"],
        "run_id": "RUN-0001",
        "status": "pending",
        "steps": [_blank_step(s) for s in pipeline["steps"]],
        "runHistory": [],
        "submittedBy": submitted_by,
        "submittedAt": now,
        # Snapshot of the pipeline's environment at submit time (see schema
        # note); recomputed when the job is restarted or resumed.
        "runEnvironment": _resolve_run_environment(pipeline),
        "all_pk": "ALL",
        "all_sk": f"{tenant_id}#{now}",
    }


def _ensure_tenant_active_for_launch(tenant_id: str) -> None:
    """New runs must never be launched into a suspended tenant. Users OF a
    suspended tenant are already rejected at the identity boundary
    (auth/dependencies); this covers the tenantless callers — the ESP trigger
    and the Operator's start/retry/resume — which name a target tenant
    explicitly. Stopping a job in a suspended tenant stays allowed: shutting
    work down is exactly what suspension wants."""
    tenant = tenant_repo.get_tenant(tenant_id)
    if tenant and tenant.get("status") == "suspended":
        raise conflict(f"Tenant '{tenant_id}' is suspended — new runs cannot be launched")


def _prepare_new_run(item: dict) -> None:
    """Gates + re-snapshotting shared by every path that launches a new run
    of an existing job (start/retry/resume): the target tenant must be
    active, the pipeline must not be archived (archiving is its end of
    life), and the run executes in the pipeline's CURRENT environment — a
    staging job restarted after promotion is a production run."""
    _ensure_tenant_active_for_launch(item["tenant_id"])
    pipeline = pipeline_repo.get_pipeline(item["tenant_id"], item["pipeline_id"])
    if pipeline and pipeline.get("status") == "archived":
        raise conflict(
            f"Pipeline '{item['pipeline_id']}' is archived — its jobs can no longer be started or rerun"
        )
    if pipeline:
        item["runEnvironment"] = _resolve_run_environment(pipeline)


def create_job(current_user: CurrentUser, data: JobCreate) -> dict:
    """Create the job in `pending` with every step idle — it does NOT run
    yet. Execution starts only on an explicit trigger: start_job (UI Start
    button) or the ESP's trigger_pipeline path."""
    pipeline = pipeline_repo.get_pipeline(current_user.tenant_id, data.pipeline_id)
    if not pipeline:
        raise not_found("Pipeline", data.pipeline_id)
    if pipeline.get("status") == "archived":
        raise conflict(
            f"Pipeline '{data.pipeline_id}' is archived — new jobs cannot be submitted for it"
        )

    item = _new_job_item(pipeline, current_user.tenant_id, current_user.user_id)
    job_id = item["job_id"]
    try:
        job_repo.create_job(item)
    except ConcurrentWriteError:
        # Astronomically unlikely random-id collision; the conditional create
        # exists so it can never silently overwrite someone else's job.
        raise conflict("Job id collision — please retry the submission")

    audit_service.write_event(
        current_user.tenant_id, current_user.user_id, current_user.role,
        "job.create", "job", job_id, f"Submitted job for pipeline '{pipeline['name']}' (not started)",
    )
    return _with_pipeline_environment(item)


def start_job(current_user: CurrentUser, job_id: str, tenant_id: Optional[str] = None) -> dict:
    """Explicitly start a newly created (pending) job — the only way a
    UI-submitted job begins running."""
    item = _resolve_job_for_ops(current_user, job_id, tenant_id, action="start")
    if item["status"] != "pending":
        raise conflict(f"Cannot start a job in status '{item['status']}' — only pending jobs can be started")

    # The pipeline may have been promoted (or archived) between create and start.
    _prepare_new_run(item)
    _run_cascade(item)
    _persist_job_action(item)

    audit_service.write_event(
        item["tenant_id"], current_user.user_id, current_user.role,
        "job.start", "job", job_id, f"Job started (run {item['run_id']})",
    )
    return _with_pipeline_environment(item)


def trigger_pipeline(
    current_user: CurrentUser,
    pipeline_id: str,
    tenant_id: Optional[str] = None,
    external_run_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> dict:
    """Machine-callable pipeline launch (POST /pipelines/{id}/trigger).

    Built for the external enterprise scheduler (ESP): the scheduler's
    service principal maps to the Operator role and names the target tenant
    explicitly; LeadDataScientists can also trigger within their own tenant.

    Differences from the UI submit path (create_job):
      * the pipeline must be `active` — a scheduler must never silently run a
        draft or archived definition;
      * the pipeline must have been promoted to the **production** environment
        (a ServiceNow-ticketed, audited action) — newly created pipelines sit
        in staging and are only runnable manually until then;
      * the pipeline's model must be in **Production** — the scheduler only
        runs production workloads; staging/test runs of non-Production models
        are submitted manually by Lead Data Scientists via POST /jobs;
      * an Idempotency-Key makes retries safe: the job id is derived
        deterministically from (tenant, key) and created with a conditional
        write, so even two concurrent retries of the same key produce exactly
        one job -- the loser reads back and returns the winner's job
        (scheduler retries after a network timeout are the expected case);
      * the scheduler's own run id (externalRunId) is recorded on the job for
        cross-system lineage.
    """
    lookup_tenant = current_user.tenant_id or tenant_id
    if not lookup_tenant:
        raise bad_request("tenantId query param is required to trigger a pipeline as Operator")
    _ensure_tenant_active_for_launch(lookup_tenant)

    pipeline = pipeline_repo.get_pipeline(lookup_tenant, pipeline_id)
    if not pipeline:
        raise not_found("Pipeline", pipeline_id)
    if pipeline.get("status") != "active":
        raise conflict(
            f"Pipeline '{pipeline_id}' is not active (status: {pipeline.get('status')}) — "
            "only active pipelines can be triggered"
        )
    if pipeline.get("environment", "staging") != "production":
        raise conflict(
            f"Pipeline '{pipeline_id}' is in the staging environment — the scheduler can "
            "only trigger production pipelines. Review its staging runs and promote it to "
            "production (with a ServiceNow ticket) first."
        )

    model_ref = _pipeline_model_ref(pipeline)
    model = (
        model_repo.get_model(lookup_tenant, model_ref[0], model_ref[1]) if model_ref else None
    )
    if not model:
        raise conflict(
            f"Pipeline '{pipeline_id}' does not reference a registered model — "
            "the scheduler can only trigger pipelines with a Production model"
        )
    if model.get("stage") != "Production":
        raise conflict(
            f"Model '{model_ref[0]}' v{model_ref[1]} is in stage "
            f"'{model.get('stage')}' — the scheduler can only trigger pipelines whose "
            "model is in Production. Run non-Production models manually (staging runs)."
        )

    item = _new_job_item(pipeline, lookup_tenant, current_user.user_id)
    item["triggeredVia"] = "api"
    if external_run_id:
        item["externalRunId"] = external_run_id
    if idempotency_key:
        item["job_id"] = _idempotent_job_id(lookup_tenant, idempotency_key)
        item["externalTriggerKey"] = idempotency_key
    job_id = item["job_id"]

    # Create the job (still pending) BEFORE starting any execution: the
    # conditional create settles the idempotency race first, so a retried
    # trigger can never start compute twice.
    try:
        job_repo.create_job(item)
    except ConcurrentWriteError:
        existing = job_repo.get_job(lookup_tenant, job_id)
        if existing and idempotency_key and existing.get("externalTriggerKey") == idempotency_key:
            if existing.get("pipeline_id") != pipeline_id:
                raise conflict(
                    f"Idempotency-Key '{idempotency_key}' was already used to trigger a "
                    f"different pipeline ('{existing.get('pipeline_id')}') in this tenant"
                )
            return existing
        raise conflict("Job id collision — please retry the trigger")

    lineage = f" (external run {external_run_id})" if external_run_id else ""
    audit_service.write_event(
        lookup_tenant, current_user.user_id, current_user.role,
        "job.trigger", "job", job_id,
        f"Triggered pipeline '{pipeline['name']}' via API{lineage}",
    )

    _run_cascade(item)
    _persist_job_action(item)

    audit_service.write_event(
        lookup_tenant, current_user.user_id, current_user.role,
        "job.start", "job", job_id, f"Job started (run {item['run_id']})",
    )
    return item


def _with_pipeline_environment(item: dict) -> dict:
    """Returned (never stored) copy carrying the pipeline's CURRENT
    environment and display name: the environment so the UI can show a job
    as production immediately after its pipeline is promoted (runEnvironment
    stays a submit-time snapshot), the name so the UI never has to show a
    raw pipeline id."""
    pipeline = pipeline_repo.get_pipeline(item["tenant_id"], item["pipeline_id"])
    return {
        **item,
        "pipelineEnvironment": (pipeline or {}).get("environment"),
        "pipelineName": (pipeline or {}).get("name"),
    }


def get_job_and_refresh(current_user: CurrentUser, job_id: str, tenant_id: Optional[str] = None) -> dict:
    lookup_tenant = current_user.tenant_id or tenant_id
    if not lookup_tenant:
        raise bad_request("tenantId query param is required to look up a job as PlatformAdmin/Operator")

    item = job_repo.get_job(lookup_tenant, job_id)
    if not item:
        raise not_found("Job", job_id)

    if item["status"] == "running":
        changed = _refresh_running_steps(item)
        if changed and not _persist_refresh(item):
            # Another writer advanced the job first — serve their state.
            item = job_repo.get_job(lookup_tenant, job_id) or item
    return _with_pipeline_environment(item)


def list_jobs(current_user: CurrentUser) -> List[dict]:
    if current_user.sees_all_tenants:
        items = job_repo.list_jobs_all_tenants()
        pipelines = pipeline_repo.list_pipelines_all_tenants()
    else:
        items = sorted(
            job_repo.list_jobs_for_tenant(current_user.tenant_id),
            key=lambda j: j.get("submittedAt", ""),
            reverse=True,
        )
        pipelines = pipeline_repo.list_pipelines_for_tenant(current_user.tenant_id)
    by_pipeline = {(p["tenant_id"], p["pipeline_id"]): p for p in pipelines}
    def _joined(j: dict) -> dict:
        p = by_pipeline.get((j["tenant_id"], j["pipeline_id"]))
        return {
            **j,
            "pipelineEnvironment": (p or {}).get("environment"),
            "pipelineName": (p or {}).get("name"),
        }
    return [_joined(j) for j in items]


def _resolve_job_for_ops(current_user: CurrentUser, job_id: str, tenant_id: Optional[str], action: str) -> dict:
    """Fetch a job for a start/stop/retry/resume action.

    Tenant-scoped callers always operate on their own tenant (an explicit
    tenant_id from them is ignored — they must never reach another tenant's
    job by guessing an id). The tenantless Operator must instead name the
    target tenant explicitly via the tenantId query param."""
    lookup_tenant = current_user.tenant_id or tenant_id
    if not lookup_tenant:
        raise bad_request("tenantId query param is required to operate on a job as Operator")

    item = job_repo.get_job(lookup_tenant, job_id)
    if not item:
        raise not_found("Job", job_id)
    if current_user.tenant_id is not None and item["tenant_id"] != current_user.tenant_id:
        raise tenant_mismatch("job")
    _ensure_can_operate(current_user, item, action)
    return item


def _current_environment(item: dict) -> str:
    """The job's *current* environment: its pipeline's environment today,
    falling back to the run's submit-time snapshot if the pipeline is gone.
    Promotion takes effect immediately — including for jobs submitted while
    the pipeline was still in staging."""
    pipeline = pipeline_repo.get_pipeline(item["tenant_id"], item["pipeline_id"])
    if pipeline:
        return pipeline.get("environment", "staging")
    return item.get("runEnvironment") or "staging"


def _ensure_can_operate(current_user: CurrentUser, item: dict, action: str) -> None:
    """Environment gate on job operations.

    Staging jobs are operated by the tenant's own scientists (Lead or not) —
    plus the cross-tenant Operator. Once the pipeline is promoted, the job is
    production territory:

      * `start` (launching a pending job) takes the same authority as the
        production trigger endpoint: Operator or LeadDataScientist. Without
        this, a Lead who submitted a job just before promotion could never
        start it — while being fully allowed to launch the same pipeline via
        POST /pipelines/{id}/trigger.
      * `stop`/`retry`/`resume` of in-flight production runs stay
        Operator-only; a Lead Data Scientist's production lever is overriding
        a failed step, not stopping/rerunning the run."""
    if _current_environment(item) != "production":
        return
    if current_user.role == "Operator":
        return
    if action == "start" and current_user.role == "LeadDataScientist":
        return
    raise forbidden(
        "Production runs are operated by the Operator role (a LeadDataScientist may "
        "start a pending production job). Lead Data Scientists can override a failed "
        "step instead."
    )


def stop_job(current_user: CurrentUser, job_id: str, tenant_id: Optional[str] = None) -> dict:
    item = _resolve_job_for_ops(current_user, job_id, tenant_id, action="stop")
    if item["status"] not in STOPPABLE_JOB_STATUSES:
        raise conflict(f"Cannot stop a job in status '{item['status']}'")

    # Stopping the platform job must also stop the compute behind it --
    # otherwise a "cancelled" job would leave a real EMR run or Snowflake
    # unload burning.
    for step in item["steps"]:
        if step["status"] != "running":
            continue
        if step["type"] == "execute_model":
            _cancel_emr_run(step)
        elif step["type"] == "data_pipeline":
            _cancel_pipeline_query(step)

    item["status"] = "cancelled"
    _persist_job_action(item)

    audit_service.write_event(
        item["tenant_id"], current_user.user_id, current_user.role,
        "job.stop", "job", job_id, f"Stopped job (run {item['run_id']})",
    )
    return _with_pipeline_environment(item)


def retry_job(current_user: CurrentUser, job_id: str, tenant_id: Optional[str] = None) -> dict:
    item = _resolve_job_for_ops(current_user, job_id, tenant_id, action="retry")
    if item["status"] not in RERUNNABLE_JOB_STATUSES:
        raise conflict(f"Cannot rerun a job in status '{item['status']}'")

    _prepare_new_run(item)
    now = _now()
    old_run_id = item["run_id"]
    old_status = item["status"]
    _archive_current_run(item, now)

    item["run_id"] = _next_run_id(item)
    for step in item["steps"]:
        _reset_step(step)
    item["status"] = "pending"

    audit_service.write_event(
        item["tenant_id"], current_user.user_id, current_user.role,
        "job.retry", "job", job_id, f"Retrying job as run {item['run_id']} (previous: {old_run_id}/{old_status})",
    )

    _run_cascade(item)
    _persist_job_action(item)

    audit_service.write_event(
        item["tenant_id"], current_user.user_id, current_user.role,
        "job.start", "job", job_id, f"Job started (run {item['run_id']})",
    )
    return _with_pipeline_environment(item)


def _reset_step(step: dict) -> None:
    step["status"] = "idle"
    step["startedAt"] = None
    step["completedAt"] = None
    step["emrJobRunId"] = None
    step["emrStateDetail"] = None
    step["snowflakeQueryId"] = None
    step["errorMessage"] = None
    step["output"] = None


def resume_job(current_user: CurrentUser, job_id: str, tenant_id: Optional[str] = None) -> dict:
    """Continue a failed/cancelled job from where it stopped: completed
    (succeeded/approved) steps keep their results; every other step is reset
    and re-executed. Contrast with retry_job, which resets the whole run."""
    item = _resolve_job_for_ops(current_user, job_id, tenant_id, action="resume")
    if item["status"] not in RESUMABLE_JOB_STATUSES:
        raise conflict(f"Cannot resume a job in status '{item['status']}'")

    _prepare_new_run(item)
    now = _now()
    old_run_id = item["run_id"]
    old_status = item["status"]
    _archive_current_run(item, now)

    item["run_id"] = _next_run_id(item)
    for step in item["steps"]:
        if step["status"] not in ("succeeded", "approved"):
            _reset_step(step)
    item["status"] = "pending"

    audit_service.write_event(
        item["tenant_id"], current_user.user_id, current_user.role,
        "job.resume", "job", job_id,
        f"Resuming job as run {item['run_id']} (previous: {old_run_id}/{old_status}; completed steps kept)",
    )

    _run_cascade(item)
    _persist_job_action(item)

    audit_service.write_event(
        item["tenant_id"], current_user.user_id, current_user.role,
        "job.start", "job", job_id, f"Job started (run {item['run_id']})",
    )
    return _with_pipeline_environment(item)


def override_failed_step(current_user: CurrentUser, job_id: str, step_id: str) -> dict:
    """Lead Data Scientist marks a failed step as succeeded (with an audit
    trail) so the run can proceed — the production-run escape hatch, since
    production stop/rerun belongs to the Operator."""
    item = job_repo.get_job(current_user.tenant_id, job_id)
    if not item:
        raise not_found("Job", job_id)
    if item["tenant_id"] != current_user.tenant_id:
        raise tenant_mismatch("job")

    step = _find_step(item, step_id)
    if not step:
        raise not_found("Step", step_id)
    if step["status"] != "failed":
        raise conflict(f"Step '{step_id}' is not failed (status='{step['status']}') — only failed steps can be overridden")

    now = _now()
    overridden_error = step.get("errorMessage")
    step["status"] = "succeeded"
    step["completedAt"] = now
    step["errorMessage"] = None
    step["output"] = {
        **(step.get("output") or {}),
        "override": {"by": current_user.user_id, "at": now, "overriddenError": overridden_error},
    }

    # Let the cascade settle the real status: it advances any remaining idle
    # steps and marks the job success if nothing is left to run.
    item["status"] = "running"
    _run_cascade(item)
    _persist_job_action(item)

    audit_service.write_event(
        item["tenant_id"], current_user.user_id, current_user.role,
        "job.override_step", "job", job_id,
        f"Overrode failed step '{step_id}' (run {item['run_id']}): {overridden_error or 'no error message'}",
    )
    return _with_pipeline_environment(item)


def _find_step(item: dict, step_id: str) -> Optional[dict]:
    return next((s for s in item["steps"] if s["step_id"] == step_id), None)


def _resolve_review_outcome(item: dict, current_user: CurrentUser, approved: bool) -> None:
    """Close the monitoring review loop after an approval decision.

    Only applies when this run put the model `InReview` (a Rework-zone run
    that hit the approval gate): approving means the reviewer accepted the
    warning-zone metrics → `Passed`; rejecting sends the model back for
    rework → `Rework`. Runs whose monitoring derived `Passed` outright leave
    the model status untouched."""
    dq_step = next((s for s in item["steps"] if s["type"] == "data_quality_check"), None)
    if not dq_step or (dq_step.get("output") or {}).get("derivedStatus") != "Rework":
        return
    model_ref = _job_model_ref(item)
    if not model_ref:
        return
    model = None
    try:
        model = model_repo.get_model(item["tenant_id"], model_ref[0], model_ref[1])
    except Exception:
        logger.exception("Failed to load model for review outcome on job %s", item["job_id"])
    if not model or model.get("currentMonitoringStatus") != "InReview":
        return  # a later snapshot already superseded the review

    new_status = "Passed" if approved else "Rework"
    verdict = "accepted by reviewer" if approved else "rejected by reviewer — rework required"
    try:
        monitoring_service.set_model_status(
            item["tenant_id"], model_ref[0], model_ref[1], new_status,
            current_user.user_id, current_user.role,
            f"Rework run {item['run_id']} {verdict} (job {item['job_id']})",
        )
    except Exception:
        logger.exception("Failed to resolve review outcome for job %s", item["job_id"])


def approve_step(current_user: CurrentUser, job_id: str, step_id: str) -> dict:
    item = job_repo.get_job(current_user.tenant_id, job_id)
    if not item:
        raise not_found("Job", job_id)
    # Explicit re-verification even though the route dependency already implies
    # the caller has *a* tenant -- a LeadDataScientist in tenant A must never
    # be able to approve a step in tenant B by guessing/knowing a job id.
    if item["tenant_id"] != current_user.tenant_id:
        raise tenant_mismatch("job")

    if item["status"] != "awaiting_approval":
        raise conflict(f"Job is not awaiting approval (status='{item['status']}')")
    step = _find_step(item, step_id)
    if not step:
        raise not_found("Step", step_id)
    if step["status"] != "awaiting_approval":
        raise conflict(f"Step '{step_id}' is not awaiting approval (status='{step['status']}')")

    step["status"] = "approved"
    step["completedAt"] = _now()
    # Let the cascade settle the job: any steps after the approval gate now
    # run; only when nothing is left does the job become success. (Setting
    # success directly would silently skip post-approval steps.)
    item["status"] = "running"
    _run_cascade(item)
    _persist_job_action(item)
    _resolve_review_outcome(item, current_user, approved=True)

    audit_service.write_event(
        current_user.tenant_id, current_user.user_id, current_user.role,
        "job.approve_step", "job", job_id, f"Approved step '{step_id}' (run {item['run_id']})",
    )
    return _with_pipeline_environment(item)


def reject_step(current_user: CurrentUser, job_id: str, step_id: str) -> dict:
    item = job_repo.get_job(current_user.tenant_id, job_id)
    if not item:
        raise not_found("Job", job_id)
    if item["tenant_id"] != current_user.tenant_id:
        raise tenant_mismatch("job")

    if item["status"] != "awaiting_approval":
        raise conflict(f"Job is not awaiting approval (status='{item['status']}')")
    step = _find_step(item, step_id)
    if not step:
        raise not_found("Step", step_id)
    if step["status"] != "awaiting_approval":
        raise conflict(f"Step '{step_id}' is not awaiting approval (status='{step['status']}')")

    step["status"] = "rejected"
    step["completedAt"] = _now()
    item["status"] = "failed"
    _persist_job_action(item)
    _resolve_review_outcome(item, current_user, approved=False)

    audit_service.write_event(
        current_user.tenant_id, current_user.user_id, current_user.role,
        "job.reject_step", "job", job_id, f"Rejected step '{step_id}' (run {item['run_id']})",
    )
    return _with_pipeline_environment(item)


async def background_refresh_running_jobs() -> int:
    """Called every JOB_REFRESH_INTERVAL_SECONDS by the startup background
    task, and usable directly in tests. Returns the number of jobs updated."""
    import asyncio

    def _do_refresh() -> int:
        updated = 0
        running_jobs = job_repo.list_jobs_by_status("running")
        for item in running_jobs:
            try:
                if _refresh_running_steps(item) and _persist_refresh(item):
                    updated += 1
            except Exception:
                logger.exception("Background refresh failed for job %s", item.get("job_id"))
        return updated

    return await asyncio.to_thread(_do_refresh)
