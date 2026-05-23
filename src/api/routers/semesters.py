from typing import Annotated

from fastapi import APIRouter, Query, Depends
from sqlmodel import select
from sqlalchemy import or_

from database.model import Semester, Event, Course, Module
from .shared import SessionDep, export_parameters, export_event_parameters, paging_parameters, page_query, sort_parameters, sort_query, filter_query, fields_parameters, include_parameters, build_list_response, build_event_list_response, get_or_404, distinct_parameters
from schemas import PaginatedResponse, SemesterRead, EventRead, CourseRead, ModuleRead

router = APIRouter(prefix="/semesters", tags=["Semesters"])

@router.get("", summary="List all semesters", response_model=PaginatedResponse[SemesterRead], response_model_exclude_unset=True)
def get_semesters(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Semester))],
    including: Annotated[dict, Depends(include_parameters(Semester))],
    fielding: Annotated[dict, Depends(fields_parameters(Semester))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
    name: list[str] | None = Query(None, description="Semester name values (repeatable; case-insensitive, partial match; OR within this filter)."),
    years: list[int] | None = Query(None, description="Year values to filter semesters that occur in specific years (repeatable; OR within this filter)."),
    terms: list[str] | None = Query(None, description="Term values to filter semesters that occur in specific terms (e.g., 'Spring', 'Fall'; repeatable; OR within this filter)."),
):
    """Retrieve a list of all semesters."""
    query = select(Semester)
    if name:
        query = query.where(or_(*[Semester.name.ilike(f"%{value}%") for value in name])) # type: ignore
    if years:
        query = query.where(or_(*[Semester.year == value for value in years])) # type: ignore
    if terms:
        query = query.where(or_(*[Semester.term.ilike(f"%{value}%") for value in terms])) # type: ignore
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Semester)
    items = filter_query(session, query, fielding, Semester, including)
    return build_list_response(data, items, export)

@router.get("/{semester_id}", summary="Get semester details", response_model=SemesterRead, response_model_exclude_unset=True)
def get_semester_details(
    session: SessionDep,
    including: Annotated[dict, Depends(include_parameters(Semester))],
    fielding: Annotated[dict, Depends(fields_parameters(Semester))],
    export: Annotated[dict, Depends(export_parameters)],
    semester_id: int,
):
    """Retrieve detailed information about a specific semester by its ID."""
    get_or_404(session, Semester, semester_id, "Semester")
    query = select(Semester).where(Semester.id == semester_id)
    items = filter_query(session, query, fielding, Semester, including)
    return items[0] if items else None

@router.get("/{semester_id}/events", summary="List events for a semester", response_model=PaginatedResponse[EventRead], response_model_exclude_unset=True)
def get_semester_events(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Event))],
    including: Annotated[dict, Depends(include_parameters(Event))],
    fielding: Annotated[dict, Depends(fields_parameters(Event))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_event_parameters)],
    semester_id: int,
):
    """Retrieve a list of events associated with a specific semester with a many-to-many relationship."""
    query = select(Event).where(Event.courses.any(Course.modules.any(Module.start_semester.any(Semester.id == semester_id))))  # type: ignore
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Event)
    items = filter_query(session, query, fielding, Event, including)
    return build_event_list_response(data, items, export)
    

@router.get("/{semester_id}/courses", summary="List courses for a semester", response_model=PaginatedResponse[CourseRead], response_model_exclude_unset=True)
def get_semester_courses(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Course))],
    including: Annotated[dict, Depends(include_parameters(Course))],
    fielding: Annotated[dict, Depends(fields_parameters(Course))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
    semester_id: int,
):
    """Retrieve a list of courses associated with a specific semester."""
    query = select(Course).where(Course.modules.any(Module.start_semester.any(Semester.id == semester_id)))  # type: ignore
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Course)
    items = filter_query(session, query, fielding, Course, including)
    return build_list_response(data, items, export)

@router.get("/{semester_id}/modules", summary="List modules for a semester", response_model=PaginatedResponse[ModuleRead], response_model_exclude_unset=True)
def get_semester_modules(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Module))],
    including: Annotated[dict, Depends(include_parameters(Module))],
    fielding: Annotated[dict, Depends(fields_parameters(Module))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
    semester_id: int,
):
    """Retrieve a list of modules associated with a specific semester."""
    query = select(Module).where(Module.start_semester.any(Semester.id == semester_id))  # type: ignore
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Module)
    items = filter_query(session, query, fielding, Module, including)
    return build_list_response(data, items, export)

@router.get("/distinct/fields", summary="Get distinct values")
def get_semester_distinct_field(
    session: SessionDep,
    field_name: Annotated[dict, Depends(distinct_parameters(Semester))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
):
    """Retrieve distinct values for a specific field across all semesters."""
    field = field_name.get("field")
    order = field_name.get("order")
    query = select(getattr(Semester, field)).distinct()  # type: ignore
    if order:
        sort_column = getattr(Semester, field)  # type: ignore
        query = query.order_by(sort_column.asc() if order.lower() == "asc" else sort_column.desc())
    data, query = page_query(session, query, paging)
    items = [{field: value} for value in session.exec(query).all()]
    return build_list_response(data, items, export)