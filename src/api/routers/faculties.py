from typing import Annotated

from fastapi import APIRouter, Query, Depends
from sqlmodel import select
from sqlalchemy import or_

from database.model import Faculty, Degree
from .shared import SessionDep, export_parameters, paging_parameters, page_query, sort_parameters, sort_query, filter_query, fields_parameters, include_parameters, build_list_response, get_or_404, distinct_parameters
from schemas import PaginatedResponse, FacultyRead, DegreeRead

router = APIRouter(prefix="/faculties", tags=["Faculties"])

@router.get("", summary="List all faculties", response_model=PaginatedResponse[FacultyRead], response_model_exclude_unset=True)
def get_faculties(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Faculty))],
    including: Annotated[dict, Depends(include_parameters(Faculty))],
    fielding: Annotated[dict, Depends(fields_parameters(Faculty))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
    ids: list[int] | None = Query(None, description="Faculty ID values (repeatable; OR within this filter)."),
    names: list[str] | None = Query(None, description="Faculty name values (repeatable; case-insensitive, partial match; OR within this filter)."),
    degrees: list[int] | None = Query(None, description="Degree ID values (repeatable; OR within this filter)."),
):
    """Retrieve a list of all faculties."""
    query = select(Faculty)
    if ids:
        query = query.where(or_(*[Faculty.id == value for value in ids])) # type: ignore
    if names:
        query = query.where(or_(*[Faculty.name.ilike(f"%{value}%") for value in names])) # type: ignore
    if degrees:
        query = query.where(or_(*[Faculty.degrees.any(Degree.id == value) for value in degrees])) # type: ignore
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Faculty)
    items = filter_query(session, query, fielding, Faculty, including)
    return build_list_response(data, items, export)

@router.get("/{faculty_id}", summary="Get faculty details", response_model=FacultyRead, response_model_exclude_unset=True)
def get_faculty_details(
    session: SessionDep,
    including: Annotated[dict, Depends(include_parameters(Faculty))],
    fielding: Annotated[dict, Depends(fields_parameters(Faculty))],
    export: Annotated[dict, Depends(export_parameters)],
    faculty_id: int,
):
    """Retrieve detailed information about a specific faculty by its ID."""
    get_or_404(session, Faculty, faculty_id, "Faculty")
    query = select(Faculty).where(Faculty.id == faculty_id)
    items = filter_query(session, query, fielding, Faculty, including)
    return items[0] if items else None

@router.get("/{faculty_id}/degrees", summary="List degrees for a faculty", response_model=PaginatedResponse[DegreeRead], response_model_exclude_unset=True)
def get_faculty_degrees(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Degree))],
    including: Annotated[dict, Depends(include_parameters(Degree))],
    fielding: Annotated[dict, Depends(fields_parameters(Degree))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
    faculty_id: int,
):
    """Retrieve a list of degrees associated with a specific faculty."""
    query = select(Degree).where(Degree.faculty_id == faculty_id)
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Degree)
    items = filter_query(session, query, fielding, Degree, including)
    return build_list_response(data, items, export)

@router.get("/distinct/{field_name}", summary="Get distinct values")
def get_faculty_distinct_field(
    session: SessionDep,
    field_name: str,
    sort: str | None = Query(None, description="Sort order for the results. For example, 'asc' or 'desc'."),
    format: str | None = Query(None, description="Response format (e.g., 'json', 'csv')."),
):
    """Retrieve distinct values for a specific field across all faculties."""
    valid_fields = {"name", "prefix"}
    if field_name not in valid_fields:
        raise ValueError(f"Invalid field name. Valid options are: {', '.join(valid_fields)}")
    
    query = select(getattr(Faculty, field_name)).distinct()
    if sort:
        sort_column = getattr(Faculty, field_name)
        query = query.order_by(sort_column.asc() if sort.lower() == "asc" else sort_column.desc())
    
    return session.exec(query).all()