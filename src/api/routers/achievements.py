from typing import Annotated

from fastapi import APIRouter, Query, Depends
from sqlalchemy import or_
from sqlmodel import select

from database.model import Module, ModuleAchievement
from .shared import SessionDep, export_parameters, paging_parameters, page_query, sort_query, filter_query, sort_parameters, fields_parameters, include_parameters, build_list_response, get_or_404, distinct_parameters, distinct_field_response, PROBLEM_RESPONSES
from schemas import PaginatedResponse, AchievementRead, ModuleRead

router = APIRouter(prefix="/achievements", tags=["Achievements"], responses=PROBLEM_RESPONSES)


@router.get("", summary="List all module achievements", response_model=PaginatedResponse[AchievementRead], response_model_exclude_unset=True)
def get_achievements(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(ModuleAchievement))],
    including: Annotated[dict, Depends(include_parameters(ModuleAchievement))],
    fielding: Annotated[dict, Depends(fields_parameters(ModuleAchievement))],
    paging: Annotated[dict, Depends(paging_parameters)],
    exports: Annotated[dict, Depends(export_parameters)],
    id: list[int] | None = Query(None, description="Achievement ID values (repeatable; OR within this filter)."),
    name: list[str] | None = Query(None, description="Achievement (Kurs/Modulabschlussleistungen) name values (repeatable; case-insensitive, partial match; OR within this filter)."),
    combination: list[str] | None = Query(None, description="Leistungskombination values (repeatable; case-insensitive, partial match; OR within this filter)."),
    required: bool | None = Query(None, description="Filter by whether the achievement is compulsory (true) or not (false)."),
    weight_min: float | None = Query(None, description="Minimum Gewichtung (weight) for the achievement."),
    weight_max: float | None = Query(None, description="Maximum Gewichtung (weight) for the achievement."),
    module_id: list[int] | None = Query(None, description="Module IDs the achievement belongs to (repeatable; direct match; OR within this filter)."),
    module_name: list[str] | None = Query(None, description="Module name values (repeatable; case-insensitive, partial match; OR within this filter)."),
    module_number: list[str] | None = Query(None, description="Module number values (repeatable; case-insensitive, partial match; OR within this filter)."),
):
    """
    Retrieve a list of all module achievements.

    An achievement is a ``Modulabschlussleistung`` from the module page's
    "Leistungen" table (name, Bestehenspflicht/Leistungskombination, Gewichtung).
    This is separate from `/exams`, which exposes the "Modulabschlussprüfungen".
    Records carry no room or building attribution, so no building filter exists.
    """
    query = select(ModuleAchievement)

    if id:
        query = query.where(ModuleAchievement.id.in_(id))  # type: ignore
    if name:
        query = query.where(or_(*[ModuleAchievement.name.ilike(f"%{value}%") for value in name]))  # type: ignore
    if combination:
        query = query.where(or_(*[ModuleAchievement.combination.ilike(f"%{value}%") for value in combination]))  # type: ignore
    if required is not None:
        query = query.where(ModuleAchievement.required == required)
    if weight_min is not None:
        query = query.where(ModuleAchievement.weight != None).where(ModuleAchievement.weight >= weight_min)  # type: ignore
    if weight_max is not None:
        query = query.where(ModuleAchievement.weight != None).where(ModuleAchievement.weight <= weight_max)  # type: ignore
    if module_id:
        query = query.where(ModuleAchievement.module_id.in_(module_id))  # type: ignore
    if module_name or module_number:
        query = query.join(ModuleAchievement.module)  # type: ignore
        if module_name:
            query = query.where(or_(*[Module.name.ilike(f"%{value}%") for value in module_name]))  # type: ignore
        if module_number:
            query = query.where(or_(*[Module.number.ilike(f"%{value}%") for value in module_number]))  # type: ignore

    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, ModuleAchievement)
    items = filter_query(session, query, fielding, ModuleAchievement, including)
    return build_list_response(data, items, exports)


@router.get("/{achievement_id}", summary="Get an achievement by ID", response_model=AchievementRead, response_model_exclude_unset=True)
def get_achievement(
    achievement_id: int,
    session: SessionDep,
    including: Annotated[dict, Depends(include_parameters(ModuleAchievement))],
    fielding: Annotated[dict, Depends(fields_parameters(ModuleAchievement))],
    export: Annotated[dict, Depends(export_parameters)],
):
    """
    Retrieve a single module achievement by its ID.

    Returns **404** if the achievement does not exist.
    """
    get_or_404(session, ModuleAchievement, achievement_id, "ModuleAchievement")
    query = select(ModuleAchievement).where(ModuleAchievement.id == achievement_id)
    items = filter_query(session, query, fielding, ModuleAchievement, including)
    return items[0] if items else None


@router.get("/{achievement_id}/modules", summary="Get modules linked to an achievement", response_model=PaginatedResponse[ModuleRead], response_model_exclude_unset=True)
def get_achievement_modules(
    achievement_id: int,
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Module))],
    including: Annotated[dict, Depends(include_parameters(Module))],
    fielding: Annotated[dict, Depends(fields_parameters(Module))],
    paging: Annotated[dict, Depends(paging_parameters)],
    exports: Annotated[dict, Depends(export_parameters)],
):
    """Retrieve the modules associated with a specific achievement."""
    get_or_404(session, ModuleAchievement, achievement_id, "ModuleAchievement")
    query = select(Module).where(Module.achievements.any(ModuleAchievement.id == achievement_id))  # type: ignore
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Module)
    items = filter_query(session, query, fielding, Module, including)
    return build_list_response(data, items, exports)


@router.get("/distinct/fields", summary="Get distinct values for an achievement field")
def get_achievement_distinct_field(
    session: SessionDep,
    field_name: Annotated[dict, Depends(distinct_parameters(ModuleAchievement))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
):
    """Retrieve distinct values for a specific field across all module achievements."""
    return distinct_field_response(session, ModuleAchievement, field_name, paging, export)
