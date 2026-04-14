from typing import Annotated

from fastapi import APIRouter, Query, Depends
from sqlmodel import select
from sqlalchemy import or_

from database.database import SessionDep
from database.model import Semester, Event, Course, Module
from .shared import export_parameters, export_event_parameters, paging_parameters

router = APIRouter(prefix="/semesters", tags=["Semesters"])

@router.get("", summary="List all semesters")
def get_semesters(
    session: SessionDep,
    paging: Annotated[dict, Depends(paging_parameters)],
    name: list[str] | None = Query(None, description="Semester name values (repeatable; case-insensitive, partial match; OR within this filter)."),
    years: list[int] | None = Query(None, description="Year values to filter semesters that occur in specific years (repeatable; OR within this filter)."),
    terms: list[str] | None = Query(None, description="Term values to filter semesters that occur in specific terms (e.g., 'Spring', 'Fall'; repeatable; OR within this filter)."),
    sort: str | None = Query(None, description="Sort order for the results. For example, 'name_asc' or 'year_desc'."),
):
    """Retrieve a list of all semesters."""
    query = select(Semester)
    if name:
        query = query.where(or_(*[Semester.name.ilike(f"%{value}%") for value in name])) # type: ignore
    if years:
        query = query.where(or_(*[Semester.year == value for value in years])) # type: ignore
    if terms:
        query = query.where(or_(*[Semester.term.ilike(f"%{value}%") for value in terms])) # type: ignore

    return session.exec(query).all()

@router.get("/{semester_id}", summary="Get semester details")
def get_semester_details(
    session: SessionDep,
    export: Annotated[dict, Depends(export_parameters)],
    semester_id: int,
    include: list[str] | None = Query(None, description="Include related entities in the response. Possible values: 'courses'. Repeatable for multiple relations."),
    fields: list[str] | None = Query(None, description="Comma-separated list of fields to include in the response. If not provided, all fields will be included."), # type: ignore
):
    """Retrieve detailed information about a specific semester by its ID."""
    return session.exec(select(Semester).where(Semester.id == semester_id)).first()

@router.get("/{semester_id}/events", summary="List events for a semester")
def get_semester_events(
    session: SessionDep,
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_event_parameters)],
    semester_id: int,
    include: list[str] | None = Query(None, description="Include related entities in the response. Possible values: 'modules', 'staff'. Repeatable for multiple relations."),
    fields: list[str] | None = Query(None, description="Comma-separated list of fields to include in the response. If not provided, all fields will be included."), # type: ignore
    sort: str | None = Query(None, description="Sort order for the results. For example, 'name_asc' or 'credits_desc'."),
):
    """Retrieve a list of events associated with a specific semester with a many-to-many relationship."""
    semester = session.exec(select(Semester).where(Semester.id == semester_id)).first()
    if semester:
        return semester.events # type: ignore
    

@router.get("/{semester_id}/courses", summary="List courses for a semester")
def get_semester_courses(
    session: SessionDep,
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
    semester_id: int,
    include: list[str] | None = Query(None, description="Include related entities in the response. Possible values: 'modules', 'staff'. Repeatable for multiple relations."),
    fields: list[str] | None = Query(None, description="Comma-separated list of fields to include in the response. If not provided, all fields will be included."), # type: ignore
    sort: str | None = Query(None, description="Sort order for the results. For example, 'name_asc' or 'credits_desc'."),
):
    """Retrieve a list of courses associated with a specific semester."""
    pass

@router.get("/{semester_id}/modules", summary="List modules for a semester")
def get_semester_modules(
    session: SessionDep,
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
    semester_id: int,
    include: list[str] | None = Query(None, description="Include related entities in the response. Possible values: 'events', 'staff'. Repeatable for multiple relations."),
    fields: list[str] | None = Query(None, description="Comma-separated list of fields to include in the response. If not provided, all fields will be included."), # type: ignore
    sort: str | None = Query(None, description="Sort order for the results. For example, 'name_asc' or 'credits_desc'."),
):
    """Retrieve a list of modules associated with a specific semester."""
    pass

@router.get("/distinct/{field_name}", summary="Get distinct values")
def get_semester_distinct_field(
    session: SessionDep,
    field_name: str,
    sort: str | None = Query(None, description="Sort order for the results. For example, 'asc' or 'desc'."),
    format: str | None = Query(None, description="Response format (e.g., 'json', 'csv')."),
):
    """Retrieve distinct values for a specific field across all semesters."""
    pass

@router.get("/changes", summary="Get semester changelog")
def get_semester_changes(
    session: SessionDep,
    paging: Annotated[dict, Depends(paging_parameters)],
    since: str = Query(..., description="Filter changes that occurred on or after this ISO 8601 datetime."),
    until: str | None = Query(None, description="Filter changes that occurred on or before this ISO 8601 datetime."),
    include_deleted: bool = Query(False, description="Whether to include deleted semesters in the changelog."),
    sort: str | None = Query(None, description="Sort order for the results. For example, 'date_asc' or 'date_desc'."),
    format: str | None = Query(None, description="Response format (e.g., 'json', 'csv')."),
):
    """Retrieve a changelog of semester modifications within a specified time range."""
    pass