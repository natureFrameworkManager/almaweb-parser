from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_
from sqlmodel import select

from database.model import Course, Event, Module, Staff
from .shared import SessionDep, export_parameters, export_event_parameters, paging_parameters, page_query, sort_query, filter_query, sort_parameters, fields_parameters, include_parameters, build_list_response, build_event_list_response, get_or_404, distinct_parameters
from schemas import PaginatedResponse, CourseRead, EventRead, ModuleRead, StaffRead

router = APIRouter(prefix="/courses", tags=["Courses"])


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
    language: list[str] | None = Query(None, description="Course language values (repeatable; case-insensitive, partial match; OR within this filter)."),
    staff: list[str] | None = Query(None, description="Course staff values (repeatable; case-insensitive, partial match; OR within this filter)."),
    has_events: bool | None = Query(None, description="Filter by whether a course has at least one event (true) or no events (false)."),
    weekly_hours_min: int | None = Query(None, description="Minimum weekly hours for the course"),
    weekly_hours_max: int | None = Query(None, description="Maximum weekly hours for the course"),
    module_id: list[int] | None = Query(None, description="Module IDs the course belongs to (repeatable; direct match; OR within this filter)."),
    module_name: list[str] | None = Query(None, description="Module name values (repeatable; case-insensitive, partial match; OR within this filter)."),
    module_number: list[str] | None = Query(None, description="Module number values (repeatable; case-insensitive, partial match; OR within this filter)."),
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
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Event)
    items = filter_query(session, query, fielding, Event, including)
    return build_event_list_response(data, items, exports)

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
    field = field_name.get("field")
    order = field_name.get("order")
    query = select(getattr(Course, field)).distinct()  # type: ignore
    if order:
        sort_column = getattr(Course, field)  # type: ignore
        query = query.order_by(sort_column.asc() if order.lower() == "asc" else sort_column.desc())
    data, query = page_query(session, query, paging)
    items = [{field: value} for value in session.exec(query).all()]
    return build_list_response(data, items, export)