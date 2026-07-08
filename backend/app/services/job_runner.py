"""
Dummy job runner (v1).

Each executable step (data_pipeline, execute_model, data_quality_check) is a
placeholder function call: it prints when the step starts, "runs" for
STEP_DURATION_SECONDS (wall-clock, no thread is held — the GET-refresh path
and the background loop advance the step once its time has elapsed), then
prints when it finishes. Swap these prints for real work when the platform
grows real executors.
"""


def run_data_pipeline(job_id: str, run_id: str, step_id: str, config: dict) -> None:
    print(
        f"[job-runner] job={job_id} run={run_id} step={step_id} "
        f"START data_pipeline: {config.get('snowflakeTable', '?')} -> {config.get('destinationS3Uri', '?')}",
        flush=True,
    )


def run_execute_model(job_id: str, run_id: str, step_id: str, config: dict) -> None:
    print(
        f"[job-runner] job={job_id} run={run_id} step={step_id} "
        f"START execute_model: {config.get('modelName', '?')} v{config.get('modelVersion', '?')}",
        flush=True,
    )


def run_data_quality_check(job_id: str, run_id: str, step_id: str, config: dict) -> None:
    print(
        f"[job-runner] job={job_id} run={run_id} step={step_id} "
        f"START data_quality_check: {len(config.get('checks', []))} check(s)",
        flush=True,
    )


START_BY_TYPE = {
    "data_pipeline": run_data_pipeline,
    "execute_model": run_execute_model,
    "data_quality_check": run_data_quality_check,
}


def start_step(item: dict, step: dict) -> None:
    fn = START_BY_TYPE.get(step["type"])
    if fn:
        fn(item["job_id"], item["run_id"], step["step_id"], step.get("config") or {})


def finish_step(item: dict, step: dict) -> None:
    print(
        f"[job-runner] job={item['job_id']} run={item['run_id']} step={step['step_id']} "
        f"FINISH {step['type']} -> {step['status']}",
        flush=True,
    )
