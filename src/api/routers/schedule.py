from typing import Annotated
from datetime import date

from fastapi import APIRouter, Query, Depends
from sqlalchemy import func, and_, cast, Integer
from sqlmodel import select

from database.model import Event, Course, Module, Staff, Location, Semester, Degree
from .shared import SessionDep, export_event_parameters, include_parameters, paging_parameters, sort_parameters, fields_parameters, page_query, sort_query, filter_query, build_list_response, PROBLEM_RESPONSES
from schemas import WeeklyRead, PaginatedResponse

router = APIRouter(prefix="/schedule", tags=["Schedule"], responses=PROBLEM_RESPONSES)

@router.get("/weekly", summary="Get generic weekly schedule", response_model=PaginatedResponse[WeeklyRead], response_model_exclude_unset=True)
def get_weekly_schedule(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Event))],
    including: Annotated[dict, Depends(include_parameters(Event))],
    fielding: Annotated[dict, Depends(fields_parameters(Event))],
    paging: Annotated[dict, Depends(paging_parameters)],
    exports: Annotated[dict, Depends(export_event_parameters)],
    semester_id: int | None = Query(None, description="ID of the semester to retrieve the schedule for."),
    faculty_ids: list[int] | None = Query(None, description="Filter schedule by faculty IDs (repeatable; OR within this filter)."),
    degree_ids: list[int] | None = Query(None, description="Filter schedule by degree IDs (repeatable; OR within this filter)."),
    course_ids: list[int] | None = Query(None, description="Filter schedule by course IDs (repeatable; OR within this filter)."),
    module_ids: list[int] | None = Query(None, description="Filter schedule by module IDs (repeatable; OR within this filter)."),
    staff_ids: list[int] | None = Query(None, description="Filter schedule by staff IDs (repeatable; OR within this filter)."),
    location_ids: list[int] | None = Query(None, description="Filter schedule by location IDs (repeatable; OR within this filter)."),
    building_ids: list[int] | None = Query(None, description="Filter schedule by building IDs (repeatable; OR within this filter)."),
    weekdays: list[int] | None = Query(None, description="Filter schedule by weekday IDs (0=Monday, 6=Sunday; repeatable; OR within this filter)."),
    split_by_day: bool = Query(False, description="Whether to split the schedule by day of the week in the response."),
):
    """Retrieve a generic weekly schedule.

    Returns deduplicated, recurring weekly time slots derived from raw event dates.
    Each entry represents a unique (weekday, start_time, end_time, location) combination
    that recurs throughout the semester — collapsing individual dated occurrences into a single
    canonical slot.

    All filter parameters narrow which events are considered before deduplication:
    - **semester_id** — restricts to a specific semester's event dates
    - **faculty_ids / degree_ids / module_ids / course_ids** — restrict by curriculum hierarchy
    - **staff_ids** — restrict to events taught by specific staff members
    - **location_ids / building_ids** — restrict to events in specific rooms or buildings
    - **weekdays** — restrict to specific days (0=Monday … 6=Sunday)

    When `split_by_day=true` the response is sorted by weekday.
    """
    # Weekday expression: SQLite strftime('%w') yields 0=Sun..6=Sat; normalise to 0=Mon..6=Sun
    weekday_col = (cast(func.strftime('%w', Event.event_date), Integer) + 6) % 7

    # Collect WHERE conditions
    conditions = []

    if semester_id is not None:
        conditions.append(
            Event.courses.any(  # type: ignore[union-attr]
                Course.modules.any(  # type: ignore[union-attr]
                    Module.start_semester.any(Semester.id == semester_id)  # type: ignore[union-attr]
                )
            )
        )

    if faculty_ids:
        conditions.append(
            Event.courses.any(  # type: ignore[union-attr]
                Course.modules.any(  # type: ignore[union-attr]
                    Module.faculty_id.in_(faculty_ids)  # type: ignore[union-attr]
                )
            )
        )

    if degree_ids:
        conditions.append(
            Event.courses.any(  # type: ignore[union-attr]
                Course.modules.any(  # type: ignore[union-attr]
                    Module.degrees.any(Degree.id.in_(degree_ids))  # type: ignore[union-attr]
                )
            )
        )

    if course_ids:
        conditions.append(Event.courses.any(Course.id.in_(course_ids)))  # type: ignore[union-attr]

    if module_ids:
        conditions.append(
            Event.courses.any(  # type: ignore[union-attr]
                Course.modules.any(Module.id.in_(module_ids))  # type: ignore[union-attr]
            )
        )

    if staff_ids:
        conditions.append(Event.staff.any(Staff.id.in_(staff_ids)))  # type: ignore[union-attr]

    if location_ids:
        conditions.append(Event.location_id.in_(location_ids))  # type: ignore[union-attr]

    if building_ids:
        conditions.append(
            Event.location.has(Location.building_id.in_(building_ids))  # type: ignore[union-attr]
        )

    if weekdays:
        # Convert API convention (0=Monday) to SQLite strftime '%w' (0=Sunday): (wd+1)%7
        sqlite_weekdays = [(wd + 1) % 7 for wd in weekdays]
        conditions.append(
            cast(func.strftime('%w', Event.event_date), Integer).in_(sqlite_weekdays)  # type: ignore[union-attr]
        )

    # Deduplication subquery: one representative event (MIN id) per canonical weekly slot
    dedup_q = select(func.min(Event.id).label("rep_id"))  # type: ignore[arg-type]
    if conditions:
        dedup_q = dedup_q.where(and_(*conditions))
    dedup_q = dedup_q.group_by(
        weekday_col,
        Event.start_time,  # type: ignore[arg-type]
        Event.end_time,  # type: ignore[arg-type]
        Event.location_id,  # type: ignore[arg-type]
    )

    # Load representative events
    query = select(Event).where(Event.id.in_(dedup_q))  # type: ignore[union-attr]

    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Event)
    if split_by_day:
        query = query.order_by(weekday_col)

    # Ensure event_date is present in the serialized output so weekday can be derived
    fielding_inner = dict(fielding)
    if fielding_inner.get("fields") is not None and "event_date" not in fielding_inner["fields"]:
        fielding_inner["fields"] = list(fielding_inner["fields"]) + ["event_date"]

    items = filter_query(session, query, fielding_inner, Event, including)

    # Inject computed weekday (0=Monday … 6=Sunday) derived from event_date
    for item in items:
        ev_date = item.get("event_date")
        if isinstance(ev_date, date):
            item["weekday"] = ev_date.isoweekday() - 1  # isoweekday 1=Mon→0, 7=Sun→6
        elif isinstance(ev_date, str):
            item["weekday"] = date.fromisoformat(ev_date).isoweekday() - 1
        else:
            item["weekday"] = 0

    return build_list_response(data, items, exports)
