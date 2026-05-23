from typing import Annotated

from fastapi import APIRouter, Query, Depends
from sqlmodel import select

from database.model import Event, EventStaffLink, CourseEventLink
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
    Each entry represents a unique (course, weekday, start_time, end_time, location) combination
    that recurs throughout the semester — collapsing individual dated occurrences into a single
    canonical slot.

    All filter parameters narrow which events are considered before deduplication:
    - **semester_id** — restricts to a specific semester's event dates
    - **faculty_ids / degree_ids / module_ids / course_ids** — restrict by curriculum hierarchy
    - **staff_ids** — restrict to events taught by specific staff members
    - **location_ids / building_ids** — restrict to events in specific rooms or buildings
    - **weekdays** — restrict to specific days (0=Monday … 6=Sunday)

    When `split_by_day=true` the response groups slots by weekday.

    > **Note:** Filtering and day-grouping are not yet implemented.
    > The endpoint currently returns a flat, unfiltered event list.
    """
    # TODO: real weekly filter by combining dates
    query = select(Event)
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Event)
    items = filter_query(session, query, fielding, Event, including)
    return build_list_response(data, items, exports)
