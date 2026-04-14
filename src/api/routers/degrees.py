from typing import Annotated

from fastapi import APIRouter, Query, Depends
from sqlmodel import select
from sqlalchemy import or_

from database.database import SessionDep
from database.model import Degree, Module
from .shared import export_parameters, paging_parameters, page_query, sort_parameters, sort_query, filter_query, fields_parameters

router = APIRouter(prefix="/degrees", tags=["Degrees"])

@router.get("", summary="List all degrees")
def get_degrees(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Degree))],
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
    items = filter_query(session, query, fielding, Degree)
    return {
        "count": data["count"],
        "page": data["page"],
        "limit": data["limit"],
        "total_pages": data["total_pages"],
        "items": items,
    }

@router.get("/{degree_id}", summary="Get degree details")
def get_degree_details(
    session: SessionDep,
    export: Annotated[dict, Depends(export_parameters)],
    degree_id: int,
    include: list[str] | None = Query(None, description="Include related entities in the response. Possible values: 'modules', 'faculty'. Repeatable for multiple relations."),
    fields: list[str] | None = Query(None, description="Comma-separated list of fields to include in the response. If not provided, all fields will be included."), # type: ignore
):
    """Retrieve detailed information about a specific degree by its ID."""
    query = select(Degree).where(Degree.id == degree_id)
    return session.exec(query).first()

@router.get("/{degree_id}/modules", summary="List modules for a degree")
def get_degree_modules(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Module))],
    fielding: Annotated[dict, Depends(fields_parameters(Module))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
    degree_id: int,
    include: list[str] | None = Query(None, description="Include related entities in the response. Possible values: 'events', 'staff'. Repeatable for multiple relations."),
):
    """Retrieve a list of modules associated with a specific degree."""
    query = select(Module).where(Module.degrees.any(Degree.id == degree_id))  # type: ignore
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Module)
    items = filter_query(session, query, fielding, Module)
    return {
        "count": data["count"],
        "page": data["page"],
        "limit": data["limit"],
        "total_pages": data["total_pages"],
        "items": items,
    }

@router.get("/{degree_id}/faculty", summary="Get faculty for a degree")
def get_degree_faculty(
    session: SessionDep,
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
    degree_id: int,
    include: list[str] | None = Query(None, description="Include related entities in the response. Possible values: 'modules', 'events'. Repeatable for multiple relations."),
    fields: list[str] | None = Query(None, description="Comma-separated list of fields to include in the response. If not provided, all fields will be included."), # type: ignore
    sort: str | None = Query(None, description="Sort order for the results. For example, 'name_asc' or 'id_desc'."),
):
    """Retrieve faculty information associated with a specific degree."""
    degree = session.exec(select(Degree).where(Degree.id == degree_id)).first()
    if degree and degree.faculty:
        return degree.faculty

@router.get("/distinct/{field_name}", summary="Get distinct values")
def get_degree_distinct_field(
    session: SessionDep,
    field_name: str,
    sort: str | None = Query(None, description="Sort order for the results. For example, 'asc' or 'desc'."),
    format: str | None = Query(None, description="Response format (e.g., 'json', 'csv')."),
):
    """Retrieve distinct values for a specific field across all degrees."""
    pass

@router.get("/changes", summary="Get degree changelog")
def get_degree_changes(
    session: SessionDep,
    paging: Annotated[dict, Depends(paging_parameters)],
    since: str = Query(..., description="Filter changes that occurred on or after this ISO 8601 datetime."),
    until: str | None = Query(None, description="Filter changes that occurred on or before this ISO 8601 datetime."),
    include_deleted: bool = Query(False, description="Whether to include deleted degrees in the changelog."),
    sort: str | None = Query(None, description="Sort order for the results. For example, 'date_asc' or 'date_desc'."),
    format: str | None = Query(None, description="Response format (e.g., 'json', 'csv')."),
):
    """Retrieve a changelog of degree modifications within a specified time range."""
    pass