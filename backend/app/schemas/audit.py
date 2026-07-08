from typing import Optional

from app.schemas.common import ApiModel


class AuditEvent(ApiModel):
    tenant_id: str
    event_id: str
    timestamp: str
    actor: str
    actorRole: str
    action: str
    entityType: str
    entityId: str
    summary: str
