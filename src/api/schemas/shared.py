from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict


T = TypeVar("T")


class Problem(BaseModel):
    """RFC 9457 Problem Details for HTTP APIs."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None


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
