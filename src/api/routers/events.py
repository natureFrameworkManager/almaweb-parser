from collections import defaultdict
from enum import Enum
from typing import Annotated, Any, Sequence

from fastapi import APIRouter, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlmodel import select
from datetime import date, time
import re

from database.database import SessionDep
from database.model import CourseEvent, Course, Module
from schemas.events import EventDetailResponseModel, EventListResponseModel


router = APIRouter(prefix="/events", tags=["Events"])
EventField = Enum("EventField", {f: f for f in CourseEvent.model_fields})


def _attach_event_relations(
    session: SessionDep,
    events: Sequence[CourseEvent],
    items: list[dict[str, Any]],
    include_parent: bool,
) -> list[dict[str, Any]]:
    if not events or not include_parent:
        return items

    course_ids = [event.course_id for event in events]
    courses = session.exec(select(Course).where(Course.id.in_(course_ids))).all() # type: ignore
    courses_by_id = {course.id: course for course in courses if course.id is not None}

    module_ids = [course.module_id for course in courses]
    modules_by_id: dict[int, Module] = {}
    if module_ids:
        modules = session.exec(select(Module).where(Module.id.in_(module_ids))).all() # type: ignore
        modules_by_id = {module.id: module for module in modules if module.id is not None}

    for event, item in zip(events, items):
        parent_course = courses_by_id.get(event.course_id)
        parent_module = modules_by_id.get(parent_course.module_id) if parent_course else None
        item["course"] = (
            {
                **parent_course.model_dump(),
                "module": parent_module.model_dump() if parent_module else None,
            }
            if parent_course
            else None
        )
        item["module"] = parent_module.model_dump() if parent_module else None

    return items

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
    page: int | None = Query(None, ge=1, description="Page number (starts at 1). If omitted together with limit, pagination is disabled."),
    limit: int | None = Query(None, ge=1, description="Number of events returned per page. If omitted together with page, pagination is disabled."),
    include_parent: bool = Query(False, description="Include linked parent data: course and module for each event."),
    fields: list[EventField] | None = Query(None, description="Comma-separated list of fields to include in the response. If not provided, all fields will be included.") # type: ignore
):
    """
    Retrieve a list of all events
    """
    # Base query: select only CourseEvent rows
    query = select(CourseEvent)

    # Apply filters based on query parameters
    if date:
        query = query.where(CourseEvent.event_date == parse_iso_date(date, "date"))
    if date_from:
        query = query.where(CourseEvent.event_date >= parse_iso_date(date_from, "date_from"))
    if date_to:
        query = query.where(CourseEvent.event_date <= parse_iso_date(date_to, "date_to"))
    if weekday:
        sqlite_weekdays = [str((day + 1) % 7) for day in weekday]
        query = query.where(func.strftime("%w", CourseEvent.event_date).in_(sqlite_weekdays))
    if start_time:
        parsed_start_time = parse_hhmm_time(start_time, "start_time")
        query = query.where(CourseEvent.start_time >= parsed_start_time)
    if end_time:
        parsed_end_time = parse_hhmm_time(end_time, "end_time")
        query = query.where(CourseEvent.end_time <= parsed_end_time)
    if time_overlap:
        parsed_overlap_time = parse_hhmm_time(time_overlap, "time_overlap")
        query = query.where(CourseEvent.start_time <= parsed_overlap_time)
        query = query.where(CourseEvent.end_time >= parsed_overlap_time)
    if location:
        query = query.where(CourseEvent.location.ilike(f"%{location}%")) # type: ignore
    if course_id is not None:
        query = query.where(CourseEvent.course_id == course_id)
    if course_name:
        query = query.join(Course).where(Course.name.ilike(f"%{course_name}%")) # type: ignore
    if course_number:
        query = query.join(Course).where(Course.number.ilike(f"%{course_number}%")) # type: ignore
    if course_type:
        query = query.join(Course).where(Course.type.ilike(f"%{course_type}%")) # type: ignore
    if module_id is not None:
        query = query.join(Course).where(Course.module_id == module_id)
    if module_name:
        query = query.join(Course).join(Module).where(Module.name.ilike(f"%{module_name}%")) # type: ignore
    if module_number:
        query = query.join(Course).join(Module).where(Module.number.ilike(f"%{module_number}%")) # type: ignore

    # Count all filtered rows before pagination.
    count_query = select(func.count()).select_from(query.distinct().subquery())
    total_count = session.exec(count_query).one()

    pagination_enabled = page is not None or limit is not None
    total_pages: int | None = None
    response_page: int = 1
    response_limit: int | None = None

    if pagination_enabled:
        response_page = page if page is not None else 1
        response_limit = limit if limit is not None else 50
        offset = (response_page - 1) * response_limit
        events = session.exec(query.distinct().offset(offset).limit(response_limit)).all()
        total_pages = (total_count + response_limit - 1) // response_limit if total_count > 0 else 0
    else:
        events = session.exec(query.distinct()).all()

    include_related = include_parent  # Events have no children, so include_children has no effect here.

    if fields:
        requested_fields = {
            field.strip()
            for value in fields
            for field in value.value.split(",")
            if field.strip()
        }
        valid_fields = set(CourseEvent.model_fields.keys())
        invalid_fields = sorted(requested_fields - valid_fields)

        if invalid_fields:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Invalid fields requested",
                    "invalid_fields": invalid_fields,
                    "valid_fields": sorted(valid_fields),
                },
            )

        selected_fields = sorted(requested_fields)
        items = [
            {
                field: event.model_dump().get(field)
                for field in selected_fields
            }
            for event in events
        ]
        if include_related:
            items = _attach_event_relations(session, events, items, include_parent=include_parent)

        return {
            "count": total_count,
            "page": response_page,
            "limit": response_limit,
            "total_pages": total_pages,
            "items": items,
        }

    if include_related:
        items = [event.model_dump() for event in events]
        items = _attach_event_relations(session, events, items, include_parent=include_parent)
        return {
            "count": total_count,
            "page": response_page,
            "limit": response_limit,
            "total_pages": total_pages,
            "items": items,
        }

    return {
        "count": total_count,
        "page": response_page,
        "limit": response_limit,
        "total_pages": total_pages,
        "items": events,
    }


@router.get("/{event_id}", summary="Get an event by ID", response_model=EventDetailResponseModel)
def get_event(
    event_id: int,
    session: SessionDep,
    include_parent: bool = Query(False, description="Include linked parent data: course and module for this event."),
    fields: list[EventField] | None = Query(None, description="Comma-separated list of fields to include in the response. If not provided, all fields will be included."), # type: ignore
):
    """
    Retrieve a single event by its ID.

    Returns **404** if the event does not exist.
    """
    event = session.get(CourseEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")

    include_related = include_parent  # Events have no children, so include_children has no effect here.

    if fields:
        requested_fields = {
            field.strip()
            for value in fields
            for field in value.value.split(",")
            if field.strip()
        }
        valid_fields = set(CourseEvent.model_fields.keys())
        invalid_fields = sorted(requested_fields - valid_fields)

        if invalid_fields:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Invalid fields requested",
                    "invalid_fields": invalid_fields,
                    "valid_fields": sorted(valid_fields),
                },
            )

        selected_fields = sorted(requested_fields)
        item = {
            field: event.model_dump().get(field)
            for field in selected_fields
        }
        if include_related:
            item = _attach_event_relations(session, [event], [item], include_parent=include_parent)[0]
        return item

    if include_related:
        item = event.model_dump()
        item = _attach_event_relations(session, [event], [item], include_parent=include_parent)[0]
        return JSONResponse(content=jsonable_encoder(item))

    return event
