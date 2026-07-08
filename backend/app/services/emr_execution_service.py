"""
EMR execution abstraction -- mock/real split selected by EMR_MODE.

Interface:
  start(step_config: dict) -> {"emrJobRunId": str}
  get_status(emr_job_run_id: str, started_at_iso: str) -> {"state": str, "stateDetail": str}
  cancel(emr_job_run_id: str, step_config: dict) -> None  (best-effort)

States surfaced by get_status follow EMR Serverless: SUBMITTED / PENDING /
SCHEDULED / QUEUED / RUNNING / CANCELLING are non-terminal; SUCCESS / FAILED /
CANCELLED are terminal. job_service polls get_status on every refresh pass and
only completes or fails the step on a terminal state.

MockEmrExecutionService is a PURE in-process simulation -- it never calls any
AWS API and is NOT routed through moto (moto has no meaningful emr-serverless
emulation anyway). Elapsed wall-clock time since `started_at_iso` drives the
state machine:
    < 3s   -> PENDING
    3-10s  -> RUNNING
    >= 10s -> terminal (SUCCESS, unless this run was chosen to fail)

The success/failure outcome is decided once, deterministically, as a pure
function of `emr_job_run_id` + EMR_MOCK_FAILURE_RATE -- NOT re-rolled on every
poll -- by hashing the run id into a stable pseudo-random draw in [0, 1).
Because it's a pure function of the (immutable) run id, recomputing it on
every call always yields the same answer without needing any separate
in-memory or persisted "decision" flag; only `emrJobRunId` and `startedAt`
need to be stored on the job's step state, which is what job_service already
does, so this survives process restarts and works correctly with both the
per-GET refresh and the 30s background polling loop.
"""
import abc
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.config import settings

PENDING_SECONDS = 3
RUNNING_SECONDS = 10

# Terminal EMR Serverless job-run states. Everything else means "still going".
TERMINAL_STATES = {"SUCCESS", "FAILED", "CANCELLED"}


class EmrExecutionService(abc.ABC):
    @abc.abstractmethod
    def start(self, step_config: dict) -> dict:
        ...

    @abc.abstractmethod
    def get_status(self, emr_job_run_id: str, started_at_iso: Optional[str] = None, step_config: Optional[dict] = None) -> dict:
        ...

    @abc.abstractmethod
    def cancel(self, emr_job_run_id: str, step_config: Optional[dict] = None) -> None:
        """Best-effort cancellation of a running job run (stop_job / timeout)."""
        ...


def _elapsed_seconds(started_at_iso: str) -> float:
    started_at = datetime.fromisoformat(started_at_iso)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return (now - started_at).total_seconds()


def _deterministic_will_fail(emr_job_run_id: str, failure_rate: float) -> bool:
    if failure_rate <= 0:
        return False
    digest = hashlib.md5(emr_job_run_id.encode("utf-8")).hexdigest()
    draw = (int(digest, 16) % 10_000) / 10_000.0
    return draw < failure_rate


class MockEmrExecutionService(EmrExecutionService):
    def start(self, step_config: dict) -> dict:
        emr_job_run_id = "mock-emr-" + uuid.uuid4().hex[:12]
        return {"emrJobRunId": emr_job_run_id}

    def get_status(self, emr_job_run_id: str, started_at_iso: Optional[str] = None, step_config: Optional[dict] = None) -> dict:
        if not started_at_iso:
            return {"state": "PENDING", "stateDetail": "Not yet started"}

        elapsed = _elapsed_seconds(started_at_iso)
        if elapsed < PENDING_SECONDS:
            return {"state": "PENDING", "stateDetail": f"Queued ({elapsed:.1f}s elapsed)"}
        if elapsed < RUNNING_SECONDS:
            return {"state": "RUNNING", "stateDetail": f"Executing Spark job ({elapsed:.1f}s elapsed)"}

        will_fail = _deterministic_will_fail(emr_job_run_id, settings.EMR_MOCK_FAILURE_RATE)
        if will_fail:
            return {"state": "FAILED", "stateDetail": "Mock EMR job run failed (synthetic failure injection)"}
        return {"state": "SUCCESS", "stateDetail": "Mock EMR job run completed successfully"}

    def cancel(self, emr_job_run_id: str, step_config: Optional[dict] = None) -> None:
        # Nothing to cancel -- the mock holds no state. A cancelled job stops
        # being refreshed, so the simulated run simply never gets polled again.
        return None


class RealEmrExecutionService(EmrExecutionService):
    def __init__(self):
        import boto3

        self._client = boto3.client("emr-serverless", region_name=settings.AWS_REGION)

    def start(self, step_config: dict) -> dict:
        resp = self._client.start_job_run(
            applicationId=step_config["emrApplicationId"],
            executionRoleArn=step_config["executionRoleArn"],
            jobDriver={
                "sparkSubmit": {
                    "entryPoint": step_config["entryPointS3Uri"],
                    "entryPointArguments": [
                        step_config["modelName"],
                        str(step_config["modelVersion"]),
                        step_config["inputS3Uri"],
                        step_config["outputS3Uri"],
                    ],
                    **({"sparkSubmitParameters": step_config["sparkSubmitParameters"]} if step_config.get("sparkSubmitParameters") else {}),
                }
            },
        )
        return {"emrJobRunId": resp["jobRunId"]}

    def get_status(self, emr_job_run_id: str, started_at_iso: Optional[str] = None, step_config: Optional[dict] = None) -> dict:
        resp = self._client.get_job_run(
            applicationId=step_config["emrApplicationId"],
            jobRunId=emr_job_run_id,
        )
        job_run = resp["jobRun"]
        return {"state": job_run["state"], "stateDetail": job_run.get("stateDetails", "")}

    def cancel(self, emr_job_run_id: str, step_config: Optional[dict] = None) -> None:
        self._client.cancel_job_run(
            applicationId=(step_config or {})["emrApplicationId"],
            jobRunId=emr_job_run_id,
        )


def get_emr_execution_service() -> EmrExecutionService:
    if settings.EMR_MODE == "real":
        return RealEmrExecutionService()
    return MockEmrExecutionService()
