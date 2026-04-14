from typing import Annotated

from fastapi import APIRouter, Query, Depends
from sqlmodel import select
from sqlalchemy import or_

from database.model import Staff, Event, Course, Module
from .shared import SessionDep, export_parameters, export_event_parameters, paging_parameters, page_query, sort_parameters, sort_query, filter_query, fields_parameters, include_parameters, build_list_response, build_event_list_response, get_or_404, distinct_parameters

router = APIRouter(prefix="/staff", tags=["Staff"])

@router.get("", summary="List all staff members")
def get_staff(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Staff))],
    including: Annotated[dict, Depends(include_parameters(Staff))],
    filtering: Annotated[dict, Depends(fields_parameters(Staff))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
    ids: list[int] | None = Query(None, description="Staff ID values (repeatable; OR within this filter)."),
    names: list[str] | None = Query(None, description="Staff name values (repeatable; case-insensitive, partial match; OR within this filter)."),
    events: list[int] | None = Query(None, description="Event ID values to filter staff associated with specific events (repeatable; OR within this filter)."),
    courses: list[int] | None = Query(None, description="Course ID values to filter staff associated with specific courses (repeatable; OR within this filter)."),
    modules: list[int] | None = Query(None, description="Module ID values to filter staff associated with specific modules (repeatable; OR within this filter)."),
):
    """Retrieve a list of all staff members."""
    query = select(Staff)
    if ids:
        query = query.where(or_(*[Staff.id == value for value in ids])) # type: ignore
    if names:
        query = query.where(or_(*[Staff.name.ilike(f"%{value}%") for value in names])) # type: ignore
    if events:
        query = query.where(or_(*[Staff.events.any(Event.id == value) for value in events])) # type: ignore
    if courses:
        query = query.where(or_(*[Staff.courses.any(Course.id == value) for value in courses])) # type: ignore
    if modules:
        query = query.where(or_(*[Staff.modules.any(Module.id == value) for value in modules])) # type: ignore
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Staff)
    items = filter_query(session, query, filtering, Staff, including)
    return build_list_response(data, items, export)

@router.get("/{staff_id}", summary="Get staff details")
def get_staff_details(
    session: SessionDep,
    including: Annotated[dict, Depends(include_parameters(Staff))],
    fielding: Annotated[dict, Depends(fields_parameters(Staff))],
    export: Annotated[dict, Depends(export_parameters)],
    staff_id: int,
):
    """Retrieve detailed information about a specific staff member by their ID."""
    get_or_404(session, Staff, staff_id, "Staff")
    query = select(Staff).where(Staff.id == staff_id)
    items = filter_query(session, query, fielding, Staff, including)
    return items[0] if items else None

@router.get("/{staff_id}/events", summary="List events for a staff member")
def get_staff_events(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Event))],
    including: Annotated[dict, Depends(include_parameters(Event))],
    fielding: Annotated[dict, Depends(fields_parameters(Event))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_event_parameters)],
    staff_id: int,
):
    """Retrieve a list of events associated with a specific staff member."""
    query = select(Event).where(Event.staff.any(Staff.id == staff_id))  # type: ignore
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Event)
    items = filter_query(session, query, fielding, Event, including)
    return build_event_list_response(data, items, export)

@router.get("/{staff_id}/courses", summary="List courses for a staff member")
def get_staff_courses(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Course))],
    including: Annotated[dict, Depends(include_parameters(Course))],
    fielding: Annotated[dict, Depends(fields_parameters(Course))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
    staff_id: int,
):
    """Retrieve a list of courses associated with a specific staff member."""
    query = select(Course).where(Course.staff.any(Staff.id == staff_id))  # type: ignore
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Course)
    items = filter_query(session, query, fielding, Course, including)
    return build_list_response(data, items, export)

@router.get("/{staff_id}/modules", summary="List modules for a staff member")
def get_staff_modules(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Module))],
    including: Annotated[dict, Depends(include_parameters(Module))],
    fielding: Annotated[dict, Depends(fields_parameters(Module))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
    staff_id: int,
):
    """Retrieve a list of modules associated with a specific staff member as the responsible person."""
    query = select(Module).where(Module.responsible_persons.any(Staff.id == staff_id))  # type: ignore
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Module)
    items = filter_query(session, query, fielding, Module, including)
    return build_list_response(data, items, export)

@router.get("/distinct/{field_name}", summary="Get distinct values for a staff field")
def get_staff_distinct_field(
    session: SessionDep,
    field_name: str,
    sort: str | None = Query(None, description="Sort order for the results. For example, 'asc' or 'desc'."),
    format: str | None = Query(None, description="Response format (e.g., 'json', 'csv')."),
):
    """Retrieve distinct values for a specific field across all staff members."""
    pass

@router.get("/changes", summary="Get staff changelog")
def get_staff_changes(
    session: SessionDep,
    paging: Annotated[dict, Depends(paging_parameters)],
    since: str = Query(..., description="Filter changes that occurred on or after this ISO 8601 datetime."),
    until: str | None = Query(None, description="Filter changes that occurred on or before this ISO 8601 datetime."),
    include_deleted: bool = Query(False, description="Whether to include deleted staff members in the changelog."),
    sort: str | None = Query(None, description="Sort order for the results. For example, 'date_asc' or 'date_desc'."),
    format: str | None = Query(None, description="Response format (e.g., 'json', 'csv')."),
):
    """Retrieve a changelog of staff modifications within a specified time range."""
    pass