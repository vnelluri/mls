from fastapi import APIRouter

from app.services import audit_service

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    """Liveness plus the audit-durability signal: audit writes are
    best-effort by policy, so `auditWriteFailures` > 0 is the alarm that the
    audit trail has gaps (per-process counter; alert on the ERROR log line
    for fleet-wide visibility)."""
    return {
        "status": "ok",
        "auditWriteFailures": audit_service.write_failure_count(),
        "secondsSinceLastAuditFailure": audit_service.seconds_since_last_failure(),
    }
