"""Helpers to slice a full result list into a PageEnvelope.

Our DynamoDB access patterns fetch full (small, demo-scale) result sets via
Query against a GSI and then paginate in-memory. This keeps repositories
simple (pure CRUD / query) while routers/services stay consistent about the
envelope shape.
"""
from typing import List, TypeVar

from app.schemas.common import PageEnvelope

T = TypeVar("T")


def paginate(items: List[T], page: int = 1, page_size: int = 20) -> PageEnvelope:
    page = max(page, 1)
    page_size = max(page_size, 1)
    start = (page - 1) * page_size
    end = start + page_size
    sliced = items[start:end]
    return PageEnvelope(items=sliced, total=len(items), page=page, pageSize=page_size)
