from fastapi import APIRouter, Query
from sqlmodel import select
from sqlalchemy import or_

from database.database import SessionDep
from database.model import EventType, Status

router = APIRouter(prefix="/catalog", tags=["Catalog"])

@router.get("/event-types", summary="List all event types")
def get_event_types(
    session: SessionDep,
    ids: list[int] | None = Query(None, description="Event type ID values (repeatable; OR within this filter)."),
    names: list[str] | None = Query(None, description="Event type name values (repeatable; case-insensitive, partial match; OR within this filter)."),
):
    """Retrieve a list of all event types."""
    query = select(EventType)
    if ids:
        query = query.where(or_(*[EventType.id == value for value in ids])) # type: ignore
    if names:
        query = query.where(or_(*[EventType.name.ilike(f"%{value}%") for value in names])) # type: ignore
    return session.exec(query).all()


@router.get("/event-types/{event_type_id}", summary="Get event type details")
def get_event_type_details(
    session: SessionDep,
    event_type_id: int,
):
    """Retrieve detailed information about a specific event type by its ID."""
    query = select(EventType).where(EventType.id == event_type_id)
    return session.exec(query).first()

@router.get("/statuses", summary="List all event statuses")
def get_event_statuses(
    session: SessionDep,
    ids: list[int] | None = Query(None, description="Event status ID values (repeatable; OR within this filter)."),
    names: list[str] | None = Query(None, description="Event status name values (repeatable; case-insensitive, partial match; OR within this filter)."),
):
    """Retrieve a list of all possible event statuses."""
    query = select(Status)
    if ids:
        query = query.where(or_(*[Status.id == value for value in ids])) # type: ignore
    if names:
        query = query.where(or_(*[Status.name.ilike(f"%{value}%") for value in names])) # type: ignore
    return session.exec(query).all()

@router.get("/statuses/{status_id}", summary="Get event status details")
def get_event_status_details(
    session: SessionDep,
    status_id: int,
):
    """Retrieve detailed information about a specific event status by its ID."""
    query = select(Status).where(Status.id == status_id)
    return session.exec(query).first()