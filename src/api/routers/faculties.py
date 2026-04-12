from typing import Annotated

from fastapi import APIRouter, Query, Depends

from database.database import SessionDep
from .shared import export_parameters, paging_parameters

router = APIRouter(prefix="/faculties", tags=["Faculties"])

@router.get("", summary="List all faculties")
def get_faculties(
    session: SessionDep,
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
    ids: list[int] | None = Query(None, description="Faculty ID values (repeatable; OR within this filter)."),
    names: list[str] | None = Query(None, description="Faculty name values (repeatable; case-insensitive, partial match; OR within this filter)."),
    degrees: list[int] | None = Query(None, description="Degree ID values (repeatable; OR within this filter)."),  
    sort: str | None = Query(None, description="Sort order for the results. For example, 'name_asc' or 'id_desc'."),
):
    """Retrieve a list of all faculties."""
    pass

@router.get("/{faculty_id}", summary="Get faculty details")
def get_faculty_details(
    session: SessionDep,
    export: Annotated[dict, Depends(export_parameters)],
    faculty_id: int,
    include: list[str] | None = Query(None, description="Include related entities in the response. Possible values: 'courses'. Repeatable for multiple relations."),
    fields: list[str] | None = Query(None, description="Comma-separated list of fields to include in the response. If not provided, all fields will be included."), # type: ignore
):
    """Retrieve detailed information about a specific faculty by its ID."""
    pass

@router.get("/{faculty_id}/courses", summary="List courses for a faculty")
def get_faculty_courses(
    session: SessionDep,
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
    faculty_id: int,
    include: list[str] | None = Query(None, description="Include related entities in the response. Possible values: 'modules'. Repeatable for multiple relations."),
    fields: list[str] | None = Query(None, description="Comma-separated list of fields to include in the response. If not provided, all fields will be included."), # type: ignore
    sort: str | None = Query(None, description="Sort order for the results. For example, 'name_asc' or 'credits_desc'."),
):
    """Retrieve a list of courses associated with a specific faculty."""
    pass

@router.get("/distinct/{field_name}", summary="Get distinct values")
def get_faculty_distinct_field(
    session: SessionDep,
    field_name: str,
    sort: str | None = Query(None, description="Sort order for the results. For example, 'asc' or 'desc'."),
    format: str | None = Query(None, description="Response format (e.g., 'json', 'csv')."),
):
    """Retrieve distinct values for a specific field across all faculties."""
    pass

@router.get("/changes", summary="Get faculty changelog")
def get_faculty_changes(
    session: SessionDep,
    paging: Annotated[dict, Depends(paging_parameters)],
    since: str = Query(..., description="Filter changes that occurred on or after this ISO 8601 datetime."),
    until: str | None = Query(None, description="Filter changes that occurred on or before this ISO 8601 datetime."),
    include_deleted: bool = Query(False, description="Whether to include deleted faculties in the changelog."),
    sort: str | None = Query(None, description="Sort order for the results. For example, 'date_asc' or 'date_desc'."),
    format: str | None = Query(None, description="Response format (e.g., 'json', 'csv')."),
):
    """Retrieve a changelog of faculty modifications within a specified time range."""
    pass