"""Shared HTTPException helpers so services/routers raise consistent errors."""
from fastapi import HTTPException, status


class ConcurrentWriteError(Exception):
    """A DynamoDB conditional write lost a race (ConditionalCheckFailed).

    Raised by repositories; services decide what losing means -- a refresh
    path drops its write (another writer already advanced the item), a
    user-action path surfaces 409."""


def not_found(entity: str, entity_id: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{entity} '{entity_id}' not found")


def tenant_mismatch(entity: str = "resource") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"You do not have access to this {entity} (tenant mismatch)",
    )


def conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def forbidden(detail: str = "You are not authorized to perform this action") -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
