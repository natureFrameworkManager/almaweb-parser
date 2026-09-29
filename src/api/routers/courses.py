from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_
from sqlmodel import select

from database.model import Course, Event, EventType, Module, Staff, Semester
from .shared import SessionDep, export_parameters, export_event_parameters, paging_parameters, page_query, sort_query, filter_query, sort_parameters, fields_parameters, include_parameters, build_list_response, build_event_list_response, get_or_404, distinct_parameters, distinct_field_response, PROBLEM_RESPONSES, _ical_augment_including
from schemas import PaginatedResponse, CourseRead, EventRead, ModuleRead, StaffRead

router = APIRouter(prefix="/courses", tags=["Courses"], responses=PROBLEM_RESPONSES)


@router.get("", summary="List all Courses", response_model=PaginatedResponse[CourseRead], response_model_exclude_unset=True)
def get_courses(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Course))],
    including: Annotated[dict, Depends(include_parameters(Course))],
    fielding: Annotated[dict, Depends(fields_parameters(Course))],
    paging: Annotated[dict, Depends(paging_parameters)],
    exports: Annotated[dict, Depends(export_parameters)],
    name: list[str] | None = Query(None, description="Course name values (repeatable; case-insensitive, partial match; OR within this filter)."),
    number: list[str] | None = Query(None, description="Course number values (repeatable; case-insensitive, partial match; OR within this filter)."),
    type: list[str] | None = Query(None, description="Course type values (repeatable; case-insensitive, partial match; OR within this filter), e.g. \"Vorlesung\", \"Seminar\"."),
    type_id: list[int] | None = Query(None, description="Event type IDs the course belongs to (repeatable; direct match; OR within this filter). Use when you already have type IDs instead of names."),
    language: list[str] | None = Query(None, description="Course language values (repeatable; case-insensitive, partial match; OR within this filter)."),
    org_unit: list[str] | None = Query(None, description="Organisational unit (Orga-Einheit) values (repeatable; case-insensitive, partial match; OR within this filter)."),
    staff: list[str] | None = Query(None, description="Course staff values (repeatable; case-insensitive, partial match; OR within this filter)."),
    staff_id: list[int] | None = Query(None, description="Staff IDs the course is taught by (repeatable; OR within this filter)."),
    has_events: bool | None = Query(None, description="Filter by whether a course has at least one event (true) or no events (false)."),
    weekly_hours_min: int | None = Query(None, description="Minimum weekly hours for the course"),
    weekly_hours_max: int | None = Query(None, description="Maximum weekly hours for the course"),
    module_id: list[int] | None = Query(None, description="Module IDs the course belongs to (repeatable; direct match; OR within this filter)."),
    module_name: list[str] | None = Query(None, description="Module name values (repeatable; case-insensitive, partial match; OR within this filter)."),
    module_number: list[str] | None = Query(None, description="Module number values (repeatable; case-insensitive, partial match; OR within this filter)."),
    semester_id: list[int] | None = Query(None, description="Semester IDs the course is offered in (repeatable; OR within this filter). Based on the course's semester links, not the module start semester."),
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
        # Course.type is an int FK to EventType; the API advertises type *names*, so resolve them first.
        query = query.where(Course.type.in_(select(EventType.id).where(or_(*[EventType.name.ilike(f"%{value}%") for value in type])))) # type: ignore
    if type_id:
        query = query.where(Course.type.in_(type_id)) # type: ignore
    if language:
        query = query.where(or_(*[Course.language.ilike(f"%{value}%") for value in language])) # type: ignore
    if org_unit:
        query = query.where(or_(*[Course.org_unit.ilike(f"%{value}%") for value in org_unit])) # type: ignore
    if staff:
        query = query.where(or_(*[Course.staff.any(Staff.name.ilike(f"%{value}%")) for value in staff])) # type: ignore
    if staff_id:
        query = query.where(Course.staff.any(Staff.id.in_(staff_id)))  # type: ignore
    if has_events is not None:
        events_exist = Course.events.any()  # type: ignore
        query = query.where(events_exist if has_events else ~events_exist)
    if weekly_hours_min is not None:
        query = query.where(Course.weekly_hours >= weekly_hours_min)
    if weekly_hours_max is not None:
        query = query.where(Course.weekly_hours <= weekly_hours_max)
    if semester_id:
        # Courses offered in any of the given semesters (CourseSemesterLink).
        query = query.where(Course.semesters.any(Semester.id.in_(semester_id)))  # type: ignore
    if module_id:
        query = query.where(Course.modules.any(Module.id.in_(module_id))) # type: ignore
    if module_name:
        query = query.where(or_(*[Course.modules.any(Module.name.ilike(f"%{value}%")) for value in module_name])) # type: ignore
    if module_number:
        query = query.where(or_(*[Course.modules.any(Module.number.ilike(f"%{value}%")) for value in module_number])) # type: ignore

    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Course)
    items = filter_query(session, query, fielding, Course, including)
    return build_list_response(data, items, exports)


@router.get("/{course_id}", summary="Get a course by ID", response_model=CourseRead, response_model_exclude_unset=True)
def get_course(
    course_id: int,
    session: SessionDep,
    including: Annotated[dict, Depends(include_parameters(Course))],
    fielding: Annotated[dict, Depends(fields_parameters(Course))],
    export: Annotated[dict, Depends(export_parameters)],
):
    """
    Retrieve a single course by its ID.

    Returns **404** if the course does not exist.
    """
    get_or_404(session, Course, course_id, "Course")
    query = select(Course).where(Course.id == course_id)
    items = filter_query(session, query, fielding, Course, including)
    return items[0] if items else None

@router.get("/{course_id}/events", summary="List events for a course", response_model=PaginatedResponse[EventRead], response_model_exclude_unset=True)
def get_course_events(
    course_id: int,
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Event))],
    including: Annotated[dict, Depends(include_parameters(Event))],
    fielding: Annotated[dict, Depends(fields_parameters(Event))],
    paging: Annotated[dict, Depends(paging_parameters)],
    exports: Annotated[dict, Depends(export_event_parameters)],
):
    """Retrieve a list of events associated with a specific course."""
    query = select(Event).where(Event.courses.any(Course.id == course_id))  # type: ignore
    crs = session.get(Course, course_id)
    ical_exports = {**exports, "_filter_course_name": crs.name if crs else None}
    ical_including = _ical_augment_including(including, ical_exports)
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Event)
    items = filter_query(session, query, fielding, Event, ical_including)
    return build_event_list_response(session, data, items, ical_exports)

@router.get("/{course_id}/modules", summary="Get modules linked to a course", response_model=PaginatedResponse[ModuleRead], response_model_exclude_unset=True)
def get_course_modules(
    course_id: int,
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Module))],
    including: Annotated[dict, Depends(include_parameters(Module))],
    fielding: Annotated[dict, Depends(fields_parameters(Module))],
    paging: Annotated[dict, Depends(paging_parameters)],
    exports: Annotated[dict, Depends(export_parameters)],
):
    """Retrieve the modules associated with a specific course."""
    query = select(Module).where(Module.courses.any(Course.id == course_id))  # type: ignore
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Module)
    items = filter_query(session, query, fielding, Module, including)
    return build_list_response(data, items, exports)

@router.get("/{course_id}/staff", summary="Get staff for a course", response_model=PaginatedResponse[StaffRead], response_model_exclude_unset=True)
def get_course_staff(
    course_id: int,
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Staff))],
    including: Annotated[dict, Depends(include_parameters(Staff))],
    fielding: Annotated[dict, Depends(fields_parameters(Staff))],
    paging: Annotated[dict, Depends(paging_parameters)],
    exports: Annotated[dict, Depends(export_parameters)],
):
    """Retrieve the staff associated with a specific course."""
    query = select(Staff).where(Staff.courses.any(Course.id == course_id))  # type: ignore
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Staff)
    items = filter_query(session, query, fielding, Staff, including)
    return build_list_response(data, items, exports)

@router.get("/distinct/fields", summary="Get distinct values for a course field")
def get_course_distinct_field(
    session: SessionDep,
    field_name: Annotated[dict, Depends(distinct_parameters(Course))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
):
    """Retrieve distinct values for a specific field across all courses."""
    return distinct_field_response(session, Course, field_name, paging, export)