from typing import Annotated

from fastapi import APIRouter, Query, Depends
from sqlmodel import select
from sqlalchemy import or_

from database.model import Course, Degree, Faculty, Module
from .shared import SessionDep, export_parameters, paging_parameters, page_query, sort_parameters, sort_query, filter_query, fields_parameters, include_parameters, build_list_response, get_or_404, distinct_parameters, PROBLEM_RESPONSES
from schemas import PaginatedResponse, DegreeRead, ModuleRead, FacultyRead

router = APIRouter(prefix="/degrees", tags=["Degrees"], responses=PROBLEM_RESPONSES)

@router.get("", summary="List all degrees", response_model=PaginatedResponse[DegreeRead], response_model_exclude_unset=True)
def get_degrees(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Degree))],
    including: Annotated[dict, Depends(include_parameters(Degree))],
    fielding: Annotated[dict, Depends(fields_parameters(Degree))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
    ids: list[int] | None = Query(None, description="Degree ID values (repeatable; OR within this filter)."),
    names: list[str] | None = Query(None, description="Degree name values (repeatable; case-insensitive, partial match; OR within this filter)."),
    faculty: list[int] | None = Query(None, description="Faculty ID values (repeatable; OR within this filter)."),
    modules: list[int] | None = Query(None, description="Module ID values to filter degrees that include these modules (repeatable; OR within this filter)."),
):
    """Retrieve a list of all degrees."""
    query = select(Degree)
    if ids:
        query = query.where(or_(*[Degree.id == value for value in ids])) # type: ignore
    if names:
        query = query.where(or_(*[Degree.name.ilike(f"%{value}%") for value in names])) # type: ignore
    if faculty:
        query = query.where(or_(*[Degree.faculty_id == value for value in faculty])) # type: ignore
    if modules:
        query = query.where(or_(*[Degree.modules.any(Module.id == value) for value in modules])) # type: ignore
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Degree)
    items = filter_query(session, query, fielding, Degree, including)
    return build_list_response(data, items, export)

@router.get("/{degree_id}", summary="Get degree details", response_model=DegreeRead, response_model_exclude_unset=True)
def get_degree_details(
    session: SessionDep,
    including: Annotated[dict, Depends(include_parameters(Degree))],
    fielding: Annotated[dict, Depends(fields_parameters(Degree))],
    export: Annotated[dict, Depends(export_parameters)],
    degree_id: int,
):
    """Retrieve detailed information about a specific degree by its ID."""
    get_or_404(session, Degree, degree_id, "Degree")
    query = select(Degree).where(Degree.id == degree_id)
    items = filter_query(session, query, fielding, Degree, including)
    return items[0] if items else None

@router.get("/{degree_id}/modules", summary="List modules for a degree", response_model=PaginatedResponse[ModuleRead], response_model_exclude_unset=True)
def get_degree_modules(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Module))],
    including: Annotated[dict, Depends(include_parameters(Module))],
    fielding: Annotated[dict, Depends(fields_parameters(Module))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
    degree_id: int,
):
    """Retrieve a list of modules associated with a specific degree."""
    query = select(Module).where(Module.degrees.any(Degree.id == degree_id))  # type: ignore
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Module)
    items = filter_query(session, query, fielding, Module, including)
    return build_list_response(data, items, export)

@router.get("/{degree_id}/faculty", summary="Get faculty for a degree", response_model=PaginatedResponse[FacultyRead], response_model_exclude_unset=True)
def get_degree_faculty(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Faculty))],
    including: Annotated[dict, Depends(include_parameters(Faculty))],
    fielding: Annotated[dict, Depends(fields_parameters(Faculty))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
    degree_id: int,
):
    """Retrieve faculty information associated with a specific degree."""
    query = select(Faculty).where(Faculty.degrees.any(Degree.id == degree_id))  # type: ignore
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Faculty)
    items = filter_query(session, query, fielding, Faculty, including)
    return build_list_response(data, items, export)

@router.get("/distinct/fields", summary="Get distinct values")
def get_degree_distinct_field(
    session: SessionDep,
    field_name: Annotated[dict, Depends(distinct_parameters(Degree))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
):
    """Retrieve distinct values for a specific field across all degrees."""
    field = field_name.get("field")
    order = field_name.get("order")
    query = select(getattr(Degree, field)).distinct()  # type: ignore
    if order:
        sort_column = getattr(Degree, field)  # type: ignore
        query = query.order_by(sort_column.asc() if order.lower() == "asc" else sort_column.desc())
    data, query = page_query(session, query, paging)
    items = [{field: value} for value in session.exec(query).all()]
    return build_list_response(data, items, export)