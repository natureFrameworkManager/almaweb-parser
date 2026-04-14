from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import func, and_
from sqlmodel import select
from datetime import date, time, timedelta
import re

from database.model import Event, Course, Module, Staff, Location
from schemas.events import EventDetailResponseModel, EventListResponseModel
from .shared import SessionDep, export_parameters, export_event_parameters, paging_parameters, page_query, sort_query, filter_query, sort_parameters, fields_parameters, include_parameters, build_list_response, build_event_list_response, get_or_404, distinct_parameters

router = APIRouter(prefix="/events", tags=["Events"])

def parse_iso_date(value: str, param_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {param_name} format. Expected YYYY-MM-DD.") from exc


def parse_hhmm_time(value: str, param_name: str) -> time:
    match = re.match(r"^(\d{2}):(\d{2})$", value)
    if not match:
        raise HTTPException(status_code=400, detail=f"Invalid {param_name} format. Expected HH:MM.")
    hours = int(match.group(1))
    minutes = int(match.group(2))
    if hours > 23 or minutes > 59:
        raise HTTPException(status_code=400, detail=f"Invalid {param_name} format. Expected HH:MM.")
    return time(hours, minutes)

@router.get("", summary="List all Events", response_model=EventListResponseModel)
def get_events(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Event))],
    including: Annotated[dict, Depends(include_parameters(Event))],
    fielding: Annotated[dict, Depends(fields_parameters(Event))],
    paging: Annotated[dict, Depends(paging_parameters)],
    exports: Annotated[dict, Depends(export_event_parameters)],
    date: str | None = Query(None, description="Event date (YYYY-MM-DD)"),
    date_from: str | None = Query(None, description="Start date for range filtering (YYYY-MM-DD, inclusive)"),
    date_to: str | None = Query(None, description="End date for range filtering (YYYY-MM-DD, inclusive)"),
    weekday: list[Annotated[int, Query(ge=0, le=6)]] | None = Query(None, description="Filter by weekday values. (0=Sunday, 1=Monday, ..., 6=Saturday)"),
    start_time: str | None = Query(None, description="Event start time (HH:MM)"),
    end_time: str | None = Query(None, description="Event end time (HH:MM)"),
    time_overlap: str | None = Query(None, description="Return events active at this time (HH:MM), i.e. start_time <= value <= end_time."),
    location: str | None = Query(None, description="Event location (case-insensitive, partial match)"),
    course_id: int | None = Query(None, description="ID of the course the event belongs to"),
    course_name: str | None = Query(None, description="Name of the course the event belongs to (case-insensitive, partial match)"),
    course_number: str | None = Query(None, description="Number of the course the event belongs to (case-insensitive, partial match)"),
    course_type: str | None = Query(None, description="Type of the course the event belongs to (case-insensitive, partial match)"),
    module_id: int | None = Query(None, description="ID of the module the event belongs to"),
    module_name: str | None = Query(None, description="Name of the module the event belongs to (case-insensitive, partial match)"),
    module_number: str | None = Query(None, description="Number of the module the event belongs to (case-insensitive, partial match)"),
):
    """
    Retrieve a list of all events
    """
    # Base query: select only CourseEvent rows
    query = select(Event)

    # Apply filters based on query parameters
    if date:
        query = query.where(Event.event_date == parse_iso_date(date, "date"))
    if date_from:
        query = query.where(Event.event_date >= parse_iso_date(date_from, "date_from"))
    if date_to:
        query = query.where(Event.event_date <= parse_iso_date(date_to, "date_to"))
    if weekday:
        sqlite_weekdays = [str((day + 1) % 7) for day in weekday]
        query = query.where(func.strftime("%w", Event.event_date).in_(sqlite_weekdays))
    if start_time:
        parsed_start_time = parse_hhmm_time(start_time, "start_time")
        query = query.where(Event.start_time >= parsed_start_time)
    if end_time:
        parsed_end_time = parse_hhmm_time(end_time, "end_time")
        query = query.where(Event.end_time <= parsed_end_time)
    if time_overlap:
        parsed_overlap_time = parse_hhmm_time(time_overlap, "time_overlap")
        query = query.where(Event.start_time <= parsed_overlap_time)
        query = query.where(Event.end_time >= parsed_overlap_time)
    if location:
        query = query.where(Event.location.ilike(f"%{location}%")) # type: ignore
    # if course_id is not None:
    #     query = query.where(Event.course_id == course_id)
    if course_name:
        query = query.join(Course).where(Course.name.ilike(f"%{course_name}%")) # type: ignore
    if course_number:
        query = query.join(Course).where(Course.number.ilike(f"%{course_number}%")) # type: ignore
    if course_type:
        query = query.join(Course).where(Course.type.ilike(f"%{course_type}%")) # type: ignore
    # if module_id is not None:
    #     query = query.join(Course).where(Course.module_id == module_id)
    if module_name:
        query = query.join(Course).join(Module).where(Module.name.ilike(f"%{module_name}%")) # type: ignore
    if module_number:
        query = query.join(Course).join(Module).where(Module.number.ilike(f"%{module_number}%")) # type: ignore

    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Event)
    items = filter_query(session, query, fielding, Event, including)
    return build_event_list_response(data, items, exports)

@router.get("/today", summary="List today's events")
def get_todays_events(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Event))],
    including: Annotated[dict, Depends(include_parameters(Event))],
    fielding: Annotated[dict, Depends(fields_parameters(Event))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_event_parameters)],
):
    """Retrieve a list of events occurring today."""
    today = date.today()
    query = select(Event).where(Event.event_date == today)
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Event)
    items = filter_query(session, query, fielding, Event, including)
    return build_event_list_response(data, items, export)

@router.get("/tomorrow", summary="List tomorrow's events")
def get_tomorrows_events(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Event))],
    including: Annotated[dict, Depends(include_parameters(Event))],
    fielding: Annotated[dict, Depends(fields_parameters(Event))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_event_parameters)],
):
    """Retrieve a list of events occurring tomorrow."""
    tomorrow = date.today() + timedelta(days=1)
    query = select(Event).where(Event.event_date == tomorrow)
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Event)
    items = filter_query(session, query, fielding, Event, including)
    return build_event_list_response(data, items, export)

@router.get("/week", summary="List events for the current week")
def get_weeks_events(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Event))],
    including: Annotated[dict, Depends(include_parameters(Event))],
    fielding: Annotated[dict, Depends(fields_parameters(Event))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_event_parameters)],
):
    """Retrieve a list of events occurring in the current week (Monday to Sunday)."""
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())  # Monday
    end_of_week = start_of_week + timedelta(days=6)  # Sunday
    query = select(Event).where(Event.event_date >= start_of_week).where(Event.event_date <= end_of_week)
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Event)
    items = filter_query(session, query, fielding, Event, including)
    return build_event_list_response(data, items, export)

@router.get("/day/{date}", summary="List events for a specific date")
def get_events_by_date(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Event))],
    including: Annotated[dict, Depends(include_parameters(Event))],
    fielding: Annotated[dict, Depends(fields_parameters(Event))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_event_parameters)],
    date: date,
):
    """Retrieve a list of events occurring on a specific date."""
    query = select(Event).where(Event.event_date == date)
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Event)
    items = filter_query(session, query, fielding, Event, including)
    return build_event_list_response(data, items, export)

@router.get("/week/{date}", summary="List events for a specific week")
def get_events_by_week(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Event))],
    including: Annotated[dict, Depends(include_parameters(Event))],
    fielding: Annotated[dict, Depends(fields_parameters(Event))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_event_parameters)],
    date: date,
):
    """Retrieve a list of events occurring in the week of a specific date (Monday to Sunday)."""
    start_of_week = date - timedelta(days=date.weekday())  # Monday
    end_of_week = start_of_week + timedelta(days=6)  # Sunday
    query = select(Event).where(Event.event_date >= start_of_week).where(Event.event_date <= end_of_week)
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Event)
    items = filter_query(session, query, fielding, Event, including)
    return build_event_list_response(data, items, export)

@router.get("/month/{date}", summary="List events for a specific month")
def get_events_by_month(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Event))],
    including: Annotated[dict, Depends(include_parameters(Event))],
    fielding: Annotated[dict, Depends(fields_parameters(Event))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_event_parameters)],
    date: date,
):
    """Retrieve a list of events occurring in the month of a specific date."""
    start_of_month = date.replace(day=1)
    if date.month == 12:
        start_of_next_month = start_of_month.replace(year=date.year + 1, month=1)
    else:
        start_of_next_month = start_of_month.replace(month=date.month + 1)
    query = select(Event).where(Event.event_date >= start_of_month).where(Event.event_date < start_of_next_month)
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Event)
    items = filter_query(session, query, fielding, Event, including)
    return build_event_list_response(data, items, export)

@router.get("/{event_id}", summary="Get an event by ID", response_model=EventDetailResponseModel)
def get_event(
    event_id: int,
    session: SessionDep,
    including: Annotated[dict, Depends(include_parameters(Event))],
    fielding: Annotated[dict, Depends(fields_parameters(Event))],
):
    """
    Retrieve a single event by its ID.

    Returns **404** if the event does not exist.
    """
    get_or_404(session, Event, event_id, "Event")
    query = select(Event).where(Event.id == event_id)
    items = filter_query(session, query, fielding, Event, including)
    return items[0] if items else None

@router.get("/{event_id}/courses", summary="Get courses linked to an event")
def get_event_course(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Course))],
    including: Annotated[dict, Depends(include_parameters(Course))],
    fielding: Annotated[dict, Depends(fields_parameters(Course))],
    paging: Annotated[dict, Depends(paging_parameters)],
    event_id: int,
    export: Annotated[dict, Depends(export_parameters)],
):
    """Retrieve the course associated with a specific event."""
    query = select(Course).where(Course.events.any(Event.id == event_id))  # type: ignore
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Course)
    items = filter_query(session, query, fielding, Course, including)
    return build_list_response(data, items, export)

@router.get("/{event_id}/module", summary="Get module for an event")
def get_event_module(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Module))],
    including: Annotated[dict, Depends(include_parameters(Module))],
    fielding: Annotated[dict, Depends(fields_parameters(Module))],
    paging: Annotated[dict, Depends(paging_parameters)],
    event_id: int,
    export: Annotated[dict, Depends(export_parameters)],
):
    """Retrieve the module associated with a specific event."""
    query = select(Module).where(Module.courses.any(Course.events.any(Event.id == event_id)))  # type: ignore
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Module)
    items = filter_query(session, query, fielding, Module, including)
    return build_list_response(data, items, export)

@router.get("/{event_id}/staff", summary="Get staff for an event")
def get_event_staff(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Staff))],
    including: Annotated[dict, Depends(include_parameters(Staff))],
    fielding: Annotated[dict, Depends(fields_parameters(Staff))],
    paging: Annotated[dict, Depends(paging_parameters)],
    event_id: int,
    export: Annotated[dict, Depends(export_parameters)],
):
    """Retrieve the staff members associated with a specific event."""
    query = select(Staff).where(Staff.events.any(Event.id == event_id))  # type: ignore
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Staff)
    items = filter_query(session, query, fielding, Staff, including)
    return build_list_response(data, items, export)

@router.get("/{event_id}/location", summary="Get location for an event")
def get_event_location(
    session: SessionDep,
    event_id: int,
    including: Annotated[dict, Depends(include_parameters(Location))],
    fielding: Annotated[dict, Depends(fields_parameters(Location))],
    export: Annotated[dict, Depends(export_parameters)],
):
    """Retrieve the location associated with a specific event."""
    query = select(Location).where(Location.events.any(Event.id == event_id))  # type: ignore
    items = filter_query(session, query, fielding, Location, including)
    return items[0] if items else None

@router.get("/distinct/{field_name}", summary="Get distinct values for an event field")
def get_event_distinct_field(
    session: SessionDep,
    field_name: str,
    sort: str | None = Query(None, description="Sort order for the results. For example, 'asc' or 'desc'."),
    format: str | None = Query(None, description="Format of the returned distinct values. Possible values: 'json' (default) or 'csv'."),
):
    """Retrieve a list of distinct values for a specified event field."""
    pass

@router.get("/changes", summary="List recent event changes")
def get_event_changes(
    session: SessionDep,
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
    since: str | None = Query(None, description="Filter changes that occurred after this timestamp (ISO 8601 format)."),
    until: str | None = Query(None, description="Filter changes that occurred before this timestamp (ISO 8601 format)."),
    include_deleted: bool = Query(False, description="Whether to include deleted events in the changelog."),
    sort: str | None = Query(None, description="Sort order for the results. For example, 'date_asc' or 'date_desc'."),
    format: str | None = Query(None, description="Format of the returned changelog entries. Possible values: 'json' (default) or 'csv'."),
):
    """Retrieve a list of recent changes to events."""
    pass