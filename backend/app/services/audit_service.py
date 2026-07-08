"""
Shared audit-event writer.

Every mutating service method calls `write_event(...)` as the LAST step of its
operation.

Durability policy (explicit, decided): audit writes are BEST-EFFORT — a
failed audit write never rolls back or fails the operation it describes.
The trade-off is deliberate: the alternative (failing user operations whose
state already persisted) is worse for correctness and no better for
compliance. What best-effort must never be is *silent*, so every failure is
logged at ERROR (the log-based alerting hook) and counted in-process; the
counter is exposed on GET /health as `auditWriteFailures` for dashboards and
alarms. A non-zero value means the audit trail has gaps and the DynamoDB
audit table needs attention.
"""
import logging
import time
import uuid
from datetime import datetime, timezone

from app.repositories import audit_repo

logger = logging.getLogger(__name__)

PLATFORM_PARTITION = "PLATFORM"

_write_failures = 0
_last_failure_at: float = 0.0


def write_failure_count() -> int:
    return _write_failures


def seconds_since_last_failure() -> float:
    """0 means 'never failed' to keep the health payload simple."""
    return round(time.time() - _last_failure_at, 1) if _last_failure_at else 0.0


def write_event(
    tenant_id: str,
    actor: str,
    actor_role: str,
    action: str,
    entity_type: str,
    entity_id: str,
    summary: str,
) -> None:
    try:
        now = datetime.now(timezone.utc)
        timestamp = now.isoformat()
        event_id = uuid.uuid4().hex[:8]
        item = {
            "tenant_id": tenant_id,
            "sk": f"{timestamp}#{event_id}",
            "event_id": event_id,
            "timestamp": timestamp,
            "actor": actor,
            "actorRole": actor_role,
            "action": action,
            "entityType": entity_type,
            "entityId": entity_id,
            "summary": summary,
            "entity_pk": f"{entity_type}#{entity_id}",
            "event_date": now.strftime("%Y-%m-%d"),
        }
        audit_repo.put_event(item)
    except Exception:
        global _write_failures, _last_failure_at
        _write_failures += 1
        _last_failure_at = time.time()
        logger.error(
            "AUDIT WRITE FAILED (action=%s entityType=%s entityId=%s tenant=%s actor=%s) -- "
            "operation continues but the audit trail now has a gap (%d total failures)",
            action,
            entity_type,
            entity_id,
            tenant_id,
            actor,
            _write_failures,
            exc_info=True,
        )
