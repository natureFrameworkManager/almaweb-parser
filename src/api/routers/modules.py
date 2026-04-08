from enum import Enum
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_
from sqlmodel import select

from database.database import SessionDep
from database.model import Module


class ModuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    name: str | None = None
    number: str | None = None
    path: list[str] | None = None
    responsible_person: str | None = None
    duration_semesters: int | None = None
    credits: float | None = None
    start_semester: str | None = None
    frequency: str | None = None
    goals: str | None = None
    content: str | None = None
    exam_prerequisites: str | None = None
    prerequisites: dict[str, str] | None = None


class ModuleListResponse(BaseModel):
    count: int
    page: int | None
    limit: int | None
    total_pages: int | None
    items: list[ModuleRead | dict[str, Any]]


router = APIRouter(prefix="/modules", tags=["Modules"])
ModuleField = Enum("ModuleField", {f: f for f in Module.model_fields})


@router.get("", summary="List all modules")
def get_modules(
    session: SessionDep,
    name: list[str] | None = Query(None, description="Module name values (repeatable; case-insensitive, partial match; OR within this filter)."),
    module_number: list[str] | None = Query(None, description="Module number values (repeatable; case-insensitive, partial match; OR within this filter)."),
    responsible_person: list[str] | None = Query(None, description="Responsible person values (repeatable; case-insensitive, partial match; OR within this filter)."),
    start_semester: list[str] | None = Query(None, description="Start semester values (repeatable; case-insensitive, partial match; OR within this filter)."),
    frequency: list[str] | None = Query(None, description="Frequency values (repeatable; case-insensitive, partial match; OR within this filter)."),
    goals: list[str] | None = Query(None, description="Goals text values (repeatable; case-insensitive, partial match; OR within this filter)."),
    content: list[str] | None = Query(None, description="Content text values (repeatable; case-insensitive, partial match; OR within this filter)."),
    exam_prerequisites: list[str] | None = Query(None, description="Exam prerequisites text values (repeatable; case-insensitive, partial match; OR within this filter)."),
    duration_semesters_min: int | None = Query(None, description="Minimum duration in semesters."),
    duration_semesters_max: int | None = Query(None, description="Maximum duration in semesters."),
    credits_min: int | None = Query(None, description="Minimum credits for the module"),
    credits_max: int | None = Query(None, description="Maximum credits for the module"),
    path_search: str | None = Query(None, description="Filter modules by path (case-insensitive, partial match). Matches on the joined path string, which is the path array joined with ' > '. For example, searching for 'Informatik > Softwaretechnik' will match modules in that path."),
    page: int | None = Query(None, ge=1, description="Page number (starts at 1). If omitted together with limit, pagination is disabled."),
    limit: int | None = Query(None, ge=1, description="Number of modules returned per page. If omitted together with page, pagination is disabled."),
    fields: list[ModuleField] | None = Query(None, description="Comma-separated list of fields to include in the response. If not provided, all fields will be included.") # type: ignore
):
    """
    Retrieve a list of all modules
    """
    # Base query: select only Module rows
    query = select(Module)

    # Apply filters based on query parameters
    if name:
        query = query.where(or_(*[Module.name.ilike(f"%{value}%") for value in name])) # type: ignore
    if module_number:
        query = query.where(or_(*[Module.number.ilike(f"%{value}%") for value in module_number])) # type: ignore
    if responsible_person:
        query = query.where(or_(*[Module.responsible_person.ilike(f"%{value}%") for value in responsible_person])) # type: ignore
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
    if path_search:
        # Normalize/Join JSON array like ["A","B"] into "A > B" for path substring search.
        normalized_path = func.replace(
            func.replace(
                func.replace(
                    func.replace(func.json_extract(Module.path, "$"), "[", ""),
                    "]",
                    "",
                ),
                '"',
                "",
            ),
            ",",
            " > ",
        )
        query = query.where(func.lower(normalized_path).ilike(f"%{path_search.lower()}%"))

    # Count all filtered rows before pagination.
    count_query = select(func.count()).select_from(query.distinct().subquery())
    total_count = session.exec(count_query).one()

    pagination_enabled = page is not None or limit is not None
    total_pages: int | None = None
    response_page: int = 1
    response_limit: int | None = None

    if pagination_enabled:
        response_page = page if page is not None else 1
        response_limit = limit if limit is not None else 50
        offset = (response_page - 1) * response_limit
        modules = session.exec(query.distinct().offset(offset).limit(response_limit)).all()
        total_pages = (total_count + response_limit - 1) // response_limit if total_count > 0 else 0
    else:
        modules = session.exec(query.distinct()).all()

    if fields:
        requested_fields = {
            field.strip()
            for value in fields
            for field in value.value.split(",")
            if field.strip()
        }
        valid_fields = set(Module.model_fields.keys())
        invalid_fields = sorted(requested_fields - valid_fields)

        if invalid_fields:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Invalid fields requested",
                    "invalid_fields": invalid_fields,
                    "valid_fields": sorted(valid_fields),
                },
            )

        selected_fields = sorted(requested_fields)
        return {
            "count": total_count,
            "page": response_page,
            "limit": response_limit,
            "total_pages": total_pages,
            "items": [
                {
                    field: module.model_dump().get(field)
                    for field in selected_fields
                }
                for module in modules
            ],
        }

    return {
        "count": total_count,
        "page": response_page,
        "limit": response_limit,
        "total_pages": total_pages,
        "items": modules,
    }


@router.get("/{module_id}", summary="Get a module by ID", response_model=ModuleRead)
def get_module(module_id: int, session: SessionDep):
    """
    Retrieve a single module by its ID.

    Returns **404** if the module does not exist.
    """
    module = session.get(Module, module_id)
    if module is None:
        raise HTTPException(status_code=404, detail="Module not found")

    return module
