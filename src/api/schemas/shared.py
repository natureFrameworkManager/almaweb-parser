from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict


T = TypeVar("T")


class ReadSchema(BaseModel):
    """Base class for all read/response schemas. Supports ORM attribute access."""

    model_config = ConfigDict(from_attributes=True)


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard paginated list response envelope returned by all list endpoints."""

    count: int
    page: int
    limit: int
    total_pages: int
    items: list[T]
