from enum import Enum

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict
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


router = APIRouter(prefix="/modules", tags=["Modules"])
ModuleField = Enum("ModuleField", {f: f for f in Module.model_fields})


@router.get("", summary="List all modules", response_model=list[ModuleRead])
def get_modules(
    session: SessionDep,
    name: str | None = Query(None, description="Module name (case-insensitive, partial match)"),
    module_number: str | None = Query(None, description="Module number (case-insensitive, partial match)"),
    credits_min: int | None = Query(None, description="Minimum credits for the module"),
    credits_max: int | None = Query(None, description="Maximum credits for the module"),
    path_search: str | None = Query(None, description="Filter modules by path (case-insensitive, partial match). Matches on the joined path string, which is the path array joined with ' > '. For example, searching for 'Informatik > Softwaretechnik' will match modules in that path."),
    fields: list[ModuleField] | None = Query(None, description="Comma-separated list of fields to include in the response. If not provided, all fields will be included.") # type: ignore
):
    """
    Retrieve a list of all modules
    """
    # Base query: select only Module rows
    query = select(Module)

    # Apply filters based on query parameters
    if name:
        query = query.where(Module.name.ilike(f"%{name}%")) # type: ignore
    if module_number:
        query = query.where(Module.number.ilike(f"%{module_number}%")) # type: ignore
    if credits_min is not None:
        query = query.where(Module.credits >= credits_min)
    if credits_max is not None:
        query = query.where(Module.credits <= credits_max)
    if path_search:
        # TODO: Substring match on the joinded path array. Path is joined with " > ", so we can search for "Informatik > Softwaretechnik" to match modules in that path.
        query = query

    # Fetch distinct modules (join filters can produce duplicates)
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
        return [
            {
                field: module.model_dump().get(field)
                for field in selected_fields
            }
            for module in modules
        ]

    return modules


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
