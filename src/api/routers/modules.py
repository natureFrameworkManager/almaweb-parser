from enum import Enum
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy import func, or_
from sqlmodel import select

from database.model import Module, Course, Event, Staff, Degree
from schemas.modules import ModuleDetailResponseModel, ModuleListResponseModel
from .shared import SessionDep, export_event_parameters, export_parameters, paging_parameters, model_field_enum, sort_parameters, fields_parameters, include_parameters, page_query, sort_query, filter_query, build_list_response, build_event_list_response, get_or_404, distinct_parameters


router = APIRouter(prefix="/modules", tags=["Modules"])


@router.get("", summary="List all modules")
def get_modules(
    session: SessionDep,
    including: Annotated[dict, Depends(include_parameters(Module))],
    fielding: Annotated[dict, Depends(fields_parameters(Module))],
    sorting: Annotated[dict, Depends(sort_parameters(Module))],
    paging: Annotated[dict, Depends(paging_parameters)],
    exports: Annotated[dict, Depends(export_parameters)],
    id: list[int] | None = Query(None, description="Module ID values (repeatable; OR within this filter)."),
    name: list[str] | None = Query(None, description="Module name values (repeatable; case-insensitive, partial match; OR within this filter)."),
    number: list[str] | None = Query(None, description="Module number values (repeatable; case-insensitive, partial match; OR within this filter)."),
    language: list[str] | None = Query(None, description="Module language values (repeatable; case-insensitive, partial match; OR within this filter)."),
    frequency: list[str] | None = Query(None, description="Frequency values (repeatable; case-insensitive, partial match; OR within this filter)."),
    credits_min: int | None = Query(None, description="Minimum credits for the module"),
    credits_max: int | None = Query(None, description="Maximum credits for the module"),
    duration_semesters_min: int | None = Query(None, description="Minimum duration in semesters."),
    duration_semesters_max: int | None = Query(None, description="Maximum duration in semesters."),
    start_semester: list[str] | None = Query(None, description="Start semester values (repeatable; case-insensitive, partial match; OR within this filter)."),
    goals: list[str] | None = Query(None, description="Goals text values (repeatable; case-insensitive, partial match; OR within this filter)."),
    content: list[str] | None = Query(None, description="Content text values (repeatable; case-insensitive, partial match; OR within this filter)."),
    exam_prerequisites: list[str] | None = Query(None, description="Exam prerequisites text values (repeatable; case-insensitive, partial match; OR within this filter)."),
    degree_id: list[int] | None = Query(None, description="Degree ID values (repeatable; OR within this filter)."),
    faculty_id: list[int] | None = Query(None, description="Faculty ID values (repeatable; OR within this filter)."),
    semester_id: list[int] | None = Query(None, description="Semester ID values (repeatable; OR within this filter)."),
    staff_id: list[int] | None = Query(None, description="Staff ID values (repeatable; OR within this filter)."),
    course_id: list[int] | None = Query(None, description="Course ID values (repeatable; OR within this filter)."),
    has_courses: bool | None = Query(None, description="Filter modules that have (true) or do not have (false) any courses."),
    has_events: bool | None = Query(None, description="Filter modules that have (true) or do not have (false) any events in their courses."),
    has_staff: bool | None = Query(None, description="Filter modules that have (true) or do not have (false) any staff assigned to them."),
):
    """
    Retrieve a list of all modules
    """
    # Base query: select only Module rows
    query = select(Module)

    # Apply filters based on query parameters
    if name:
        query = query.where(or_(*[Module.name.ilike(f"%{value}%") for value in name])) # type: ignore
    if number:
        query = query.where(or_(*[Module.number.ilike(f"%{value}%") for value in number])) # type: ignore
    # if responsible_person:
    #     query = query.where(or_(*[Module.responsible_person.ilike(f"%{value}%") for value in responsible_person])) # type: ignore
    if start_semester:
        query = query.where(or_(*[Module.start_semester.ilike(f"%{value}%") for value in start_semester])) # type: ignore
    if frequency:
        query = query.where(or_(*[Module.frequency.ilike(f"%{value}%") for value in frequency])) # type: ignore
    if goals:
        query = query.where(or_(*[Module.goals.ilike(f"%{value}%") for value in goals])) # type: ignore
    if content:
        query = query.where(or_(*[Module.content.ilike(f"%{value}%") for value in content])) # type: ignore
    if exam_prerequisites:
        query = query.where(or_(*[Module.exam_prerequisites.ilike(f"%{value}%") for value in exam_prerequisites])) # type: ignore
    if duration_semesters_min is not None:
        query = query.where(Module.duration_semesters >= duration_semesters_min)
    if duration_semesters_max is not None:
        query = query.where(Module.duration_semesters <= duration_semesters_max)
    if credits_min is not None:
        query = query.where(Module.credits >= credits_min)
    if credits_max is not None:
        query = query.where(Module.credits <= credits_max)

    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Module)
    items = filter_query(session, query, fielding, Module, including)
    return build_list_response(data, items, exports)


@router.get("/{module_id}", summary="Get a module by ID")
def get_module(
    module_id: int,
    session: SessionDep,
    including: Annotated[dict, Depends(include_parameters(Module))],
    fielding: Annotated[dict, Depends(fields_parameters(Module))],
    exports: Annotated[dict, Depends(export_parameters)],
):
    """
    Retrieve a single module by its ID.

    Returns **404** if the module does not exist.
    """
    get_or_404(session, Module, module_id, "Module")
    query = select(Module).where(Module.id == module_id)
    items = filter_query(session, query, fielding, Module, including)
    return items[0] if items else None

@router.get("/{module_id}/courses", summary="Courses linked to a module")
def get_module_courses(
    module_id: int,
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Course))],
    including: Annotated[dict, Depends(include_parameters(Course))],
    fielding: Annotated[dict, Depends(fields_parameters(Course))],
    paging: Annotated[dict, Depends(paging_parameters)],
    exports: Annotated[dict, Depends(export_parameters)],
):
    """
    Retrieve a module courses.
    """
    query = select(Course).where(Course.modules.any(Module.id == module_id))  # type: ignore
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Course)
    items = filter_query(session, query, fielding, Course, including)
    return build_list_response(data, items, exports)

@router.get("/{module_id}/events", summary="Events linked to a module")
def get_module_events(
    module_id: int,
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Event))],
    including: Annotated[dict, Depends(include_parameters(Event))],
    fielding: Annotated[dict, Depends(fields_parameters(Event))],
    paging: Annotated[dict, Depends(paging_parameters)],
    exports: Annotated[dict, Depends(export_event_parameters)],
    date_from: str | None = Query(None, description="Filter events that start on or after this ISO 8601 datetime."),
    date_to: str | None = Query(None, description="Filter events that end on or before this ISO 8601 datetime."),
    weekday: list[int] | None = Query(None, description="Filter events that occur on these weekdays (0=Monday, 6=Sunday). Repeatable for multiple days."),
):
    """
    Retrieve a module events.
    """
    query = select(Event).where(Event.courses.any(Course.modules.any(Module.id == module_id)))  # type: ignore
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Event)
    items = filter_query(session, query, fielding, Event, including)
    return build_event_list_response(data, items, exports)

@router.get("/{module_id}/staff", summary="Staff linked to a module")
def get_module_staff(
    module_id: int,
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Staff))],
    including: Annotated[dict, Depends(include_parameters(Staff))],
    fielding: Annotated[dict, Depends(fields_parameters(Staff))],
    paging: Annotated[dict, Depends(paging_parameters)],
    exports: Annotated[dict, Depends(export_parameters)],
):
    """
    Retrieve a module staff.
    """
    query = select(Staff).where(Staff.modules.any(Module.id == module_id))  # type: ignore
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Staff)
    items = filter_query(session, query, fielding, Staff, including)
    return build_list_response(data, items, exports)

@router.get("/{module_id}/degrees", summary="Degrees linked to a module")
def get_module_degrees(
    module_id: int,
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Degree))],
    including: Annotated[dict, Depends(include_parameters(Degree))],
    fielding: Annotated[dict, Depends(fields_parameters(Degree))],
    paging: Annotated[dict, Depends(paging_parameters)],
    exports: Annotated[dict, Depends(export_parameters)],
):
    """
    Retrieve a module degrees.
    """
    query = select(Degree).where(Degree.modules.any(Module.id == module_id))  # type: ignore
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Degree)
    items = filter_query(session, query, fielding, Degree, including)
    return build_list_response(data, items, exports)

@router.get("/distinct/{field}", summary="Distinct values for a module field")
def get_distinct_module_field(
    session: SessionDep,
    paging: Annotated[dict, Depends(paging_parameters)],
    field: str | None, # type: ignore
    sort: str | None = Query(None, description="Sort order for the results. For example, 'asc' or 'desc'."),
    format: str | None = Query(None, description="Response format (e.g., 'json', 'csv')."),
):
    """
    Retrieve distinct values for a module field.
    """
    pass