"""Repository-level concurrency guarantees: optimistic locking, conditional
creates, idempotent snapshots, and group-mapping resolution."""
import pytest

from app.auth.group_mapping import resolve_role_and_tenant
from app.config import settings
from app.core.exceptions import ConcurrentWriteError
from app.db.client import get_table
from app.repositories import job_repo, model_repo, monitoring_repo


def _job_item(job_id="job-test0001"):
    return {
        "tenant_id": "acme",
        "job_id": job_id,
        "pipeline_id": "pl-x",
        "pipeline_version": 1,
        "run_id": "RUN-0001",
        "status": "pending",
        "steps": [],
        "runHistory": [],
        "submittedBy": "u",
        "submittedAt": "2026-01-01T00:00:00+00:00",
        "all_pk": "ALL",
        "all_sk": "acme#2026-01-01T00:00:00+00:00",
    }


def test_create_job_refuses_to_overwrite(aws):
    job_repo.create_job(_job_item())
    with pytest.raises(ConcurrentWriteError):
        job_repo.create_job(_job_item())


def test_put_job_optimistic_locking(aws):
    job_repo.create_job(_job_item())

    reader_a = job_repo.get_job("acme", "job-test0001")
    reader_b = job_repo.get_job("acme", "job-test0001")

    reader_a["status"] = "running"
    job_repo.put_job(reader_a)  # A wins

    reader_b["status"] = "cancelled"
    with pytest.raises(ConcurrentWriteError):
        job_repo.put_job(reader_b)  # B lost -- must not clobber A

    # B's in-memory copy is left un-bumped so a re-read/retry works cleanly.
    assert job_repo.get_job("acme", "job-test0001")["status"] == "running"


def test_put_job_upgrades_legacy_items_without_version(aws):
    # Seeded/legacy rows were written without item_version.
    get_table(settings.TABLE_JOBS).put_item(Item=_job_item())

    legacy = job_repo.get_job("acme", "job-test0001")
    assert "item_version" not in legacy
    job_repo.put_job(legacy)
    assert job_repo.get_job("acme", "job-test0001")["item_version"] == 1


def test_update_stage_conditional_on_expected_stage(aws):
    model_repo.create_model({
        "tenant_id": "acme", "model_name": "m", "version": "1", "stage": "Staging",
        "currentMonitoringStatus": "NotStarted",
    })
    with pytest.raises(ConcurrentWriteError):
        model_repo.update_stage("acme", "m", "1", "Production", expected_stage="None",
                                promoted_by="u", promoted_at="t")
    updated = model_repo.update_stage("acme", "m", "1", "Production", expected_stage="Staging",
                                      promoted_by="u", promoted_at="t")
    assert updated["stage"] == "Production"


def test_create_model_refuses_duplicates(aws):
    item = {"tenant_id": "acme", "model_name": "m", "version": "1", "stage": "None"}
    model_repo.create_model(dict(item))
    with pytest.raises(ConcurrentWriteError):
        model_repo.create_model(dict(item))


def _snapshot(status="Passed", error_rate=0.01):
    return {
        "tenant_id": "acme", "model_name": "m", "version": "1",
        "job_id": "job-1", "run_id": "RUN-0001",
        "recordedAt": "2026-01-01T00:00:00+00:00",
        "requestCount": 1, "avgLatencyMs": 1.0, "errorRate": error_rate,
        "driftMetrics": {}, "maxPsi": 0.0, "dataQualityPassed": True,
        "dataQualityDetails": {}, "derivedStatus": status,
        "thresholdsUsed": {}, "all_pk": "ALL", "model_trend_pk": "acme#m#1",
    }


def test_snapshot_is_idempotent_per_run_and_transactional(aws):
    model_repo.create_model({
        "tenant_id": "acme", "model_name": "m", "version": "1", "stage": "None",
        "currentMonitoringStatus": "NotStarted",
    })

    first = monitoring_repo.record_snapshot_with_model_status(_snapshot("Passed"), update_model=True)
    # A racing duplicate for the same run loses: the FIRST snapshot is returned
    # and the model keeps the first writer's status.
    second = monitoring_repo.record_snapshot_with_model_status(
        _snapshot("Failed", error_rate=0.9), update_model=True
    )
    assert second["derivedStatus"] == first["derivedStatus"] == "Passed"
    assert len(monitoring_repo.list_snapshots_for_tenant("acme")) == 1
    assert model_repo.get_model("acme", "m", "1")["currentMonitoringStatus"] == "Passed"


def test_group_mapping_resolution_picks_highest_privilege(aws):
    table = get_table(settings.TABLE_GROUP_MAPPINGS)
    table.put_item(Item={"group_id": "g-ds", "role": "DataScientist", "tenant_id": "acme",
                         "displayName": "DS"})
    table.put_item(Item={"group_id": "g-op", "role": "Operator", "tenant_id": None,
                         "displayName": "Ops"})

    assert resolve_role_and_tenant(["g-unknown"]) is None
    role, tenant, _ = resolve_role_and_tenant(["g-ds"])
    assert (role, tenant) == ("DataScientist", "acme")
    # Member of both: Operator outranks DataScientist.
    role, tenant, _ = resolve_role_and_tenant(["g-ds", "g-op"])
    assert (role, tenant) == ("Operator", None)
