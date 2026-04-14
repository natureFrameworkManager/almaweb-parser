from typing import Annotated

from fastapi import APIRouter, Query, Depends
from sqlmodel import select
from sqlalchemy import or_

from database.model import EventType, Status
from .shared import SessionDep, export_parameters, paging_parameters, page_query, sort_parameters, sort_query, filter_query, fields_parameters, build_list_response

router = APIRouter(prefix="/catalog", tags=["Catalog"])

@router.get("/event-types", summary="List all event types")
def get_event_types(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(EventType))],
    fielding: Annotated[dict, Depends(fields_parameters(EventType))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
    ids: list[int] | None = Query(None, description="Event type ID values (repeatable; OR within this filter)."),
    names: list[str] | None = Query(None, description="Event type name values (repeatable; case-insensitive, partial match; OR within this filter)."),
):
    """Retrieve a list of all event types."""
    query = select(EventType)
    if ids:
        query = query.where(or_(*[EventType.id == value for value in ids])) # type: ignore
    if names:
        query = query.where(or_(*[EventType.name.ilike(f"%{value}%") for value in names])) # type: ignore
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, EventType)
    items = filter_query(session, query, fielding, EventType)
    return build_list_response(data, items, export)


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
    sorting: Annotated[dict, Depends(sort_parameters(Status))],
    fielding: Annotated[dict, Depends(fields_parameters(Status))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
    ids: list[int] | None = Query(None, description="Event status ID values (repeatable; OR within this filter)."),
    names: list[str] | None = Query(None, description="Event status name values (repeatable; case-insensitive, partial match; OR within this filter)."),
):
    """Retrieve a list of all possible event statuses."""
    query = select(Status)
    if ids:
        query = query.where(or_(*[Status.id == value for value in ids])) # type: ignore
    if names:
        query = query.where(or_(*[Status.name.ilike(f"%{value}%") for value in names])) # type: ignore
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Status)
    items = filter_query(session, query, fielding, Status)
    return build_list_response(data, items, export)

@router.get("/statuses/{status_id}", summary="Get event status details")
def get_event_status_details(
    session: SessionDep,
    status_id: int,
):
    """Retrieve detailed information about a specific event status by its ID."""
    query = select(Status).where(Status.id == status_id)
    return session.exec(query).first()