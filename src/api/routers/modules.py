from collections import defaultdict
from enum import Enum
from typing import Any, Sequence

from fastapi import APIRouter, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_
from sqlmodel import select

from database.database import SessionDep
from database.model import Course, CourseEvent, Module
from schemas.modules import ModuleDetailResponseModel, ModuleListResponseModel


router = APIRouter(prefix="/modules", tags=["Modules"])
ModuleField = Enum("ModuleField", {f: f for f in Module.model_fields})


def _attach_module_relations(
    session: SessionDep,
    modules: Sequence[Module],
    items: list[dict[str, Any]],
    include_children: bool,
) -> list[dict[str, Any]]:
    if not include_children or not modules:
        return items

    module_ids = [module.id for module in modules if module.id is not None]
    if not module_ids:
        for item in items:
            item["courses"] = []
        return items

    courses = session.exec(select(Course).where(Course.module_id.in_(module_ids))).all() # type: ignore
    courses_by_module_id: dict[int, list[Course]] = defaultdict(list)
    for course in courses:
        courses_by_module_id[course.module_id].append(course)

    course_ids = [course.id for course in courses if course.id is not None]
    events_by_course_id: dict[int, list[CourseEvent]] = defaultdict(list)
    if course_ids:
        events = session.exec(select(CourseEvent).where(CourseEvent.course_id.in_(course_ids))).all() # type: ignore
        for event in events:
            events_by_course_id[event.course_id].append(event)

    for module, item in zip(modules, items):
        module_id = module.id
        related_courses = courses_by_module_id.get(module_id, []) if module_id is not None else []
        course_items: list[dict[str, Any]] = []
        for course in related_courses:
            course_id = course.id
            related_events = events_by_course_id.get(course_id, []) if course_id is not None else []
            course_items.append(
                {
                    **course.model_dump(),
                    "events": [event.model_dump() for event in related_events],
                }
            )
        item["courses"] = course_items

    return items


@router.get("", summary="List all modules", response_model=ModuleListResponseModel)
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
    include_children: bool = Query(False, description="Include child data: courses and each course's events."),
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

    include_related = include_children  # Modules have no parent, so include_parent has no effect here.

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
        items = [
            {
                field: module.model_dump().get(field)
                for field in selected_fields
            }
            for module in modules
        ]
        if include_related:
            items = _attach_module_relations(session, modules, items, include_children=include_children)

        return {
            "count": total_count,
            "page": response_page,
            "limit": response_limit,
            "total_pages": total_pages,
            "items": items,
        }

    if include_related:
        items = [module.model_dump() for module in modules]
        items = _attach_module_relations(session, modules, items, include_children=include_children)
        return {
            "count": total_count,
            "page": response_page,
            "limit": response_limit,
            "total_pages": total_pages,
            "items": items,
        }

    return {
        "count": total_count,
        "page": response_page,
        "limit": response_limit,
        "total_pages": total_pages,
        "items": modules,
    }


@router.get("/{module_id}", summary="Get a module by ID", response_model=ModuleDetailResponseModel)
def get_module(
    module_id: int,
    session: SessionDep,
    include_children: bool = Query(False, description="Include child data: courses and each course's events."),
    fields: list[ModuleField] | None = Query(None, description="Comma-separated list of fields to include in the response. If not provided, all fields will be included."), # type: ignore
):
    """
    Retrieve a single module by its ID.

    Returns **404** if the module does not exist.
    """
    module = session.get(Module, module_id)
    if module is None:
        raise HTTPException(status_code=404, detail="Module not found")

    include_related = include_children  # Modules have no parent, so include_parent has no effect here.

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
        item = {
            field: module.model_dump().get(field)
            for field in selected_fields
        }
        if include_related:
            item = _attach_module_relations(session, [module], [item], include_children=include_children)[0]
        return item

    if include_related:
        item = module.model_dump()
        item = _attach_module_relations(session, [module], [item], include_children=include_children)[0]
        return JSONResponse(content=jsonable_encoder(item))

    return module
