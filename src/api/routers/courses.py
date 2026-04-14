from collections import defaultdict
from enum import Enum
from typing import Any, Sequence, Annotated

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_
from sqlmodel import select

from database.model import Course, Event, Module, Staff
from schemas.courses import CourseDetailResponseModel, CourseListResponseModel
from .shared import SessionDep, export_parameters, export_event_parameters, paging_parameters, page_query, sort_query, filter_query, sort_parameters, fields_parameters, build_list_response, build_event_list_response, get_or_404, distinct_parameters

router = APIRouter(prefix="/courses", tags=["Courses"])
CourseField = Enum("CourseField", {f: f for f in Course.model_fields})


def _attach_course_relations(
    session: SessionDep,
    courses: Sequence[Course],
    items: list[dict[str, Any]],
    include_children: bool,
    include_parent: bool,
) -> list[dict[str, Any]]:
    if not courses or (not include_children and not include_parent):
        return items

    course_ids = [course.id for course in courses if course.id is not None]
    # module_ids = [course.module_id for course in courses]

    modules_by_id: dict[int, Module] = {}
    # if include_parent and module_ids:
    #     modules = session.exec(select(Module).where(Module.id.in_(module_ids))).all() # type: ignore
    #     modules_by_id = {module.id: module for module in modules if module.id is not None}

    events_by_course_id: dict[int, list[Event]] = defaultdict(list)
    # if include_children and course_ids:
    #     events = session.exec(select(Event).where(Event.course_id.in_(course_ids))).all() # type: ignore
    #     for event in events:
    #         events_by_course_id[event.course_id].append(event)

    # for course, item in zip(courses, items):
    #     if include_parent:
    #         parent_module = modules_by_id.get(course.module_id)
    #         item["module"] = parent_module.model_dump() if parent_module else None
    #     if include_children:
    #         course_id = course.id
    #         item["events"] = [
    #             event.model_dump()
    #             for event in (events_by_course_id.get(course_id, []) if course_id is not None else [])
    #         ]

    return items


@router.get("", summary="List all Courses", response_model=CourseListResponseModel)
def get_courses(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Course))],
    fielding: Annotated[dict, Depends(fields_parameters(Course))],
    paging: Annotated[dict, Depends(paging_parameters)],
    exports: Annotated[dict, Depends(export_parameters)],
    name: list[str] | None = Query(None, description="Course name values (repeatable; case-insensitive, partial match; OR within this filter)."),
    number: list[str] | None = Query(None, description="Course number values (repeatable; case-insensitive, partial match; OR within this filter)."),
    type: list[str] | None = Query(None, description="Course type values (repeatable; case-insensitive, partial match; OR within this filter), e.g. \"Vorlesung\", \"Seminar\"."),
    language: list[str] | None = Query(None, description="Course language values (repeatable; case-insensitive, partial match; OR within this filter)."),
    staff: list[str] | None = Query(None, description="Course staff values (repeatable; case-insensitive, partial match; OR within this filter)."),
    has_events: bool | None = Query(None, description="Filter by whether a course has at least one event (true) or no events (false)."),
    weekly_hours_min: int | None = Query(None, description="Minimum weekly hours for the course"),
    weekly_hours_max: int | None = Query(None, description="Maximum weekly hours for the course"),
    module_id: list[int] | None = Query(None, description="Module IDs the course belongs to (repeatable; direct match; OR within this filter)."),
    module_name: list[str] | None = Query(None, description="Module name values (repeatable; case-insensitive, partial match; OR within this filter)."),
    module_number: list[str] | None = Query(None, description="Module number values (repeatable; case-insensitive, partial match; OR within this filter)."),
    include_children: bool = Query(False, description="Include child data: events for each course."),
    include_parent: bool = Query(False, description="Include linked parent data: the module for each course."),
):
    """
    Retrieve a list of all courses
    """
    # Base query: select only Course rows
    query = select(Course)

    # Apply filters based on query parameters
    if name:
        query = query.where(or_(*[Course.name.ilike(f"%{value}%") for value in name])) # type: ignore
    if number:
        query = query.where(or_(*[Course.number.ilike(f"%{value}%") for value in number])) # type: ignore
    if type:
        query = query.where(or_(*[Course.type.ilike(f"%{value}%") for value in type])) # type: ignore
    if language:
        query = query.where(or_(*[Course.language.ilike(f"%{value}%") for value in language])) # type: ignore
    if staff:
        query = query.where(or_(*[Course.staff.ilike(f"%{value}%") for value in staff])) # type: ignore
    # if has_events is not None:
    #     events_exist = select(Event.id).where(Event.course_id == Course.id).exists()
    #     query = query.where(events_exist if has_events else ~events_exist)
    if weekly_hours_min is not None:
        query = query.where(Course.weekly_hours >= weekly_hours_min)
    if weekly_hours_max is not None:
        query = query.where(Course.weekly_hours <= weekly_hours_max)
    if module_id:
        query = query.where(Course.module_id.in_(module_id)) # type: ignore
    if module_name or module_number:
        query = query.join(Course.module) # type: ignore
        if module_name:
            query = query.where(or_(*[Module.name.ilike(f"%{value}%") for value in module_name])) # type: ignore
        if module_number:
            query = query.where(or_(*[Module.number.ilike(f"%{value}%") for value in module_number])) # type: ignore

    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Course)
    items = filter_query(session, query, fielding, Course)
    return build_list_response(data, items, exports)


@router.get("/{course_id}", summary="Get a course by ID", response_model=CourseDetailResponseModel)
def get_course(
    course_id: int,
    session: SessionDep,
    fielding: Annotated[dict, Depends(fields_parameters(Course))],
    export: Annotated[dict, Depends(export_parameters)],
    include_children: bool = Query(False, description="Include child data: events for this course."),
    include_parent: bool = Query(False, description="Include linked parent data: the module for this course."),
):
    """
    Retrieve a single course by its ID.

    Returns **404** if the course does not exist.
    """
    get_or_404(session, Course, course_id, "Course")
    query = select(Course).where(Course.id == course_id)
    items = filter_query(session, query, fielding, Course)
    return items[0] if items else None

@router.get("/{course_id}/events", summary="List events for a course")
def get_course_events(
    course_id: int,
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Event))],
    fielding: Annotated[dict, Depends(fields_parameters(Event))],
    paging: Annotated[dict, Depends(paging_parameters)],
    exports: Annotated[dict, Depends(export_event_parameters)],
    include: list[str] | None = Query(None, description="Include related entities in the response. Possible values: 'modules'. Repeatable for multiple relations."),
):
    """Retrieve a list of events associated with a specific course."""
    query = select(Event).where(Event.courses.any(Course.id == course_id))  # type: ignore
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Event)
    items = filter_query(session, query, fielding, Event)
    return build_event_list_response(data, items, exports)

@router.get("/{course_id}/modules", summary="Get modules linked to a course")
def get_course_modules(
    course_id: int,
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Module))],
    fielding: Annotated[dict, Depends(fields_parameters(Module))],
    paging: Annotated[dict, Depends(paging_parameters)],
    exports: Annotated[dict, Depends(export_parameters)],
    include: list[str] | None = Query(None, description="Include related entities in the response. Possible values: 'events'. Repeatable for multiple relations."),
):
    """Retrieve the modules associated with a specific course."""
    query = select(Module).where(Module.courses.any(Course.id == course_id))  # type: ignore
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Module)
    items = filter_query(session, query, fielding, Module)
    return build_list_response(data, items, exports)

@router.get("/{course_id}/staff", summary="Get staff for a course")
def get_course_staff(
    course_id: int,
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Staff))],
    fielding: Annotated[dict, Depends(fields_parameters(Staff))],
    paging: Annotated[dict, Depends(paging_parameters)],
    exports: Annotated[dict, Depends(export_parameters)],
    include: list[str] | None = Query(None, description="Include related entities in the response. Possible values: 'modules'. Repeatable for multiple relations."),
):
    """Retrieve the staff associated with a specific course."""
    query = select(Staff).where(Staff.courses.any(Course.id == course_id))  # type: ignore
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Staff)
    items = filter_query(session, query, fielding, Staff)
    return build_list_response(data, items, exports)

@router.get("/distinct/{field_name}", summary="Get distinct values for a course field")
def get_course_distinct_field(
    session: SessionDep,
    field_name: str,
    sort: str | None = Query(None, description="Sort order for the results. For example, 'asc' or 'desc'."),
    format: str | None = Query(None, description="Response format (e.g., 'json', 'csv')."),
):
    """Retrieve distinct values for a specific field across all courses."""
    pass

@router.get("/changes", summary="Get course changelog")
def get_course_changes(
    session: SessionDep,
    paging: Annotated[dict, Depends(paging_parameters)],
    since: str = Query(..., description="Filter changes that occurred on or after this ISO 8601 datetime."),
    until: str | None = Query(None, description="Filter changes that occurred on or before this ISO 8601 datetime."),
    include_deleted: bool = Query(False, description="Whether to include deleted courses in the changelog."),
    sort: str | None = Query(None, description="Sort order for the results. For example, 'date_asc' or 'date_desc'."),
    format: str | None = Query(None, description="Response format (e.g., 'json', 'csv')."),
):
    """Retrieve a changelog of course modifications within a specified time range."""
    pass