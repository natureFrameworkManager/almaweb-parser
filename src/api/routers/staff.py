from typing import Annotated

from fastapi import APIRouter, Query, Depends
from sqlmodel import select
from sqlalchemy import or_

from database.database import SessionDep
from database.model import Staff
from .shared import export_parameters, export_event_parameters, paging_parameters

router = APIRouter(prefix="/staff", tags=["Staff"])

@router.get("", summary="List all staff members")
def get_staff(
    session: SessionDep,
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
    ids: list[int] | None = Query(None, description="Staff ID values (repeatable; OR within this filter)."),
    names: list[str] | None = Query(None, description="Staff name values (repeatable; case-insensitive, partial match; OR within this filter)."),
    events: list[int] | None = Query(None, description="Event ID values to filter staff associated with specific events (repeatable; OR within this filter)."),
    courses: list[int] | None = Query(None, description="Course ID values to filter staff associated with specific courses (repeatable; OR within this filter)."),
    modules: list[int] | None = Query(None, description="Module ID values to filter staff associated with specific modules (repeatable; OR within this filter)."),
    sort: str | None = Query(None, description="Sort order for the results. For example, 'name_asc' or 'id_desc'."),
):
    """Retrieve a list of all staff members."""
    query = select(Staff)
    if ids:
        query = query.where(or_(*[Staff.id == value for value in ids])) # type: ignore
    if names:
        query = query.where(or_(*[Staff.name.ilike(f"%{value}%") for value in names])) # type: ignore
    if events:
        query = query.where(or_(*[Staff.events.any(Event.id == value) for value in events])) # type: ignore
    if courses:
        query = query.where(or_(*[Staff.courses.any(Course.id == value) for value in courses])) # type: ignore
    if modules:
        query = query.where(or_(*[Staff.modules.any(Module.id == value) for value in modules])) # type: ignore
    return session.exec(query).all()

@router.get("/{staff_id}", summary="Get staff details")
def get_staff_details(
    session: SessionDep,
    export: Annotated[dict, Depends(export_parameters)],
    staff_id: int,
    include: list[str] | None = Query(None, description="Include related entities in the response. Possible values: 'courses'. Repeatable for multiple relations."),
    fields: list[str] | None = Query(None, description="Comma-separated list of fields to include in the response. If not provided, all fields will be included."), # type: ignore
):
    """Retrieve detailed information about a specific staff member by their ID."""
    query = select(Staff).where(Staff.id == staff_id)
    return session.exec(query).first()

@router.get("/{staff_id}/events", summary="List events for a staff member")
def get_staff_events(
    session: SessionDep,
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_event_parameters)],
    staff_id: int,
    include: list[str] | None = Query(None, description="Include related entities in the response. Possible values: 'modules'. Repeatable for multiple relations."),
    fields: list[str] | None = Query(None, description="Comma-separated list of fields to include in the response. If not provided, all fields will be included."), # type: ignore
    sort: str | None = Query(None, description="Sort order for the results. For example, 'name_asc' or 'credits_desc'."),
):
    """Retrieve a list of events associated with a specific staff member."""
    staff = session.exec(select(Staff).where(Staff.id == staff_id)).first()
    if staff:
        return staff.events

@router.get("/{staff_id}/courses", summary="List courses for a staff member")
def get_staff_courses(
    session: SessionDep,
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
    staff_id: int,
    include: list[str] | None = Query(None, description="Include related entities in the response. Possible values: 'modules'. Repeatable for multiple relations."),
    fields: list[str] | None = Query(None, description="Comma-separated list of fields to include in the response. If not provided, all fields will be included."), # type: ignore
    sort: str | None = Query(None, description="Sort order for the results. For example, 'name_asc' or 'credits_desc'."),
):
    """Retrieve a list of courses associated with a specific staff member."""
    staff = session.exec(select(Staff).where(Staff.id == staff_id)).first()
    if staff:
        return staff.courses

@router.get("/{staff_id}/modules", summary="List modules for a staff member")
def get_staff_modules(
    session: SessionDep,
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
    staff_id: int,
    include: list[str] | None = Query(None, description="Include related entities in the response. Possible values: 'modules'. Repeatable for multiple relations."),
    fields: list[str] | None = Query(None, description="Comma-separated list of fields to include in the response. If not provided, all fields will be included."), # type: ignore
    sort: str | None = Query(None, description="Sort order for the results. For example, 'name_asc' or 'credits_desc'."),
):
    """Retrieve a list of modules associated with a specific staff member as the responsible person."""
    staff = session.exec(select(Staff).where(Staff.id == staff_id)).first()
    if staff:
        return staff.modules

@router.get("/distinct/{field_name}", summary="Get distinct values for a staff field")
def get_staff_distinct_field(
    session: SessionDep,
    field_name: str,
    sort: str | None = Query(None, description="Sort order for the results. For example, 'asc' or 'desc'."),
    format: str | None = Query(None, description="Response format (e.g., 'json', 'csv')."),
):
    """Retrieve distinct values for a specific field across all staff members."""
    pass

@router.get("/changes", summary="Get staff changelog")
def get_staff_changes(
    session: SessionDep,
    paging: Annotated[dict, Depends(paging_parameters)],
    since: str = Query(..., description="Filter changes that occurred on or after this ISO 8601 datetime."),
    until: str | None = Query(None, description="Filter changes that occurred on or before this ISO 8601 datetime."),
    include_deleted: bool = Query(False, description="Whether to include deleted staff members in the changelog."),
    sort: str | None = Query(None, description="Sort order for the results. For example, 'date_asc' or 'date_desc'."),
    format: str | None = Query(None, description="Response format (e.g., 'json', 'csv')."),
):
    """Retrieve a changelog of staff modifications within a specified time range."""
    pass