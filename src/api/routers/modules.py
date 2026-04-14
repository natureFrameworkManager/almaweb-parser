from enum import Enum
from typing import Any, Sequence, Annotated

from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy import func, or_
from sqlmodel import select

from database.database import SessionDep
from database.model import Module
from schemas.modules import ModuleDetailResponseModel, ModuleListResponseModel
from .shared import export_event_parameters, export_parameters, paging_parameters, model_field_enum, sort_parameters


router = APIRouter(prefix="/modules", tags=["Modules"])
ModuleField = model_field_enum(Module)

class IncludeOption(str, Enum):
    courses = "courses"
    events = "events"
    staff = "staff"
    degrees = "degrees"

class SortOption(str, Enum):
    id_asc = "id_asc"
    id_desc = "id_desc"
    name_asc = "name_asc"
    name_desc = "name_desc"
    number_asc = "number_asc"
    number_desc = "number_desc"
    credits_asc = "credits_asc"
    credits_desc = "credits_desc"
    duration_semesters_asc = "duration_semesters_asc"
    duration_semesters_desc = "duration_semesters_desc"
    updated_at_asc = "updated_at_asc"
    updated_at_desc = "updated_at_desc"

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

    # courses = session.exec(select(Course).where(Course.module_id.in_(module_ids))).all() # type: ignore
    # courses_by_module_id: dict[int, list[Course]] = defaultdict(list)
    # for course in courses:
    #     courses_by_module_id[course.module_id].append(course)

    # course_ids = [course.id for course in courses if course.id is not None]
    # events_by_course_id: dict[int, list[Event]] = defaultdict(list)
    # if course_ids:
    #     events = session.exec(select(Event).where(Event.course_id.in_(course_ids))).all() # type: ignore
    #     for event in events:
    #         events_by_course_id[event.course_id].append(event)

    # for module, item in zip(modules, items):
    #     module_id = module.id
    #     related_courses = courses_by_module_id.get(module_id, []) if module_id is not None else []
    #     course_items: list[dict[str, Any]] = []
    #     for course in related_courses:
    #         course_id = course.id
    #         related_events = events_by_course_id.get(course_id, []) if course_id is not None else []
    #         course_items.append(
    #             {
    #                 **course.model_dump(),
    #                 "events": [event.model_dump() for event in related_events],
    #             }
    #         )
    #     item["courses"] = course_items

    return items


@router.get("", summary="List all modules", response_model=ModuleListResponseModel)
def get_modules(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Module))],
    paging: Annotated[dict, Depends(paging_parameters)],
    exports: Annotated[dict, Depends(export_parameters)],
    id: list[int] | None = Query(None, description="Module ID values (repeatable; OR within this filter)."),
    name: list[str] | None = Query(None, description="Module name values (repeatable; case-insensitive, partial match; OR within this filter)."),
    number: list[str] | None = Query(None, description="Module number values (repeatable; case-insensitive, partial match; OR within this filter)."),
    language: list[str] | None = Query(None, description="Module language values (repeatable; case-insensitive, partial match; OR within this filter)."),
    frequency: list[str] | None = Query(None, description="Frequency values (repeatable; case-insensitive, partial match; OR within this filter)."),
    credits_min: int | None = Query(None, description="Minimum credits for the module"),
    credits_max: int | None = Query(None, description="Maximum credits for the module"),
    duration_semesters_min: int | None = Query(None, description="Minimum duration in semesters."),
    duration_semesters_max: int | None = Query(None, description="Maximum duration in semesters."),
    start_semester: list[str] | None = Query(None, description="Start semester values (repeatable; case-insensitive, partial match; OR within this filter)."),
    goals: list[str] | None = Query(None, description="Goals text values (repeatable; case-insensitive, partial match; OR within this filter)."),
    content: list[str] | None = Query(None, description="Content text values (repeatable; case-insensitive, partial match; OR within this filter)."),
    exam_prerequisites: list[str] | None = Query(None, description="Exam prerequisites text values (repeatable; case-insensitive, partial match; OR within this filter)."),
    degree_id: list[int] | None = Query(None, description="Degree ID values (repeatable; OR within this filter)."),
    faculty_id: list[int] | None = Query(None, description="Faculty ID values (repeatable; OR within this filter)."),
    semester_id: list[int] | None = Query(None, description="Semester ID values (repeatable; OR within this filter)."),
    staff_id: list[int] | None = Query(None, description="Staff ID values (repeatable; OR within this filter)."),
    course_id: list[int] | None = Query(None, description="Course ID values (repeatable; OR within this filter)."),
    has_courses: bool | None = Query(None, description="Filter modules that have (true) or do not have (false) any courses."),
    has_events: bool | None = Query(None, description="Filter modules that have (true) or do not have (false) any events in their courses."),
    has_staff: bool | None = Query(None, description="Filter modules that have (true) or do not have (false) any staff assigned to them."),
    updated_since: str | None = Query(None, description="Filter modules that have been updated since the given ISO 8601 datetime string."),
    updated_before: str | None = Query(None, description="Filter modules that have been updated before the given ISO 8601 datetime string."),
    include: list[IncludeOption] | None = Query(None, description="Related data to include: courses, events, staff. Repeatable for multiple relations."),
    fields: list[ModuleField] | None = Query(None, description="Comma-separated list of fields to include in the response. If not provided, all fields will be included."), # type: ignore
):
    """
    Retrieve a list of all modules
    """
    # Base query: select only Module rows
    query = select(Module)

    # Apply filters based on query parameters
    if name:
        query = query.where(or_(*[Module.name.ilike(f"%{value}%") for value in name])) # type: ignore
    if number:
        query = query.where(or_(*[Module.number.ilike(f"%{value}%") for value in number])) # type: ignore
    # if responsible_person:
    #     query = query.where(or_(*[Module.responsible_person.ilike(f"%{value}%") for value in responsible_person])) # type: ignore
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

    sort_field = sorting.get("sort")
    if sort_field:
        sort_column = getattr(Module, sort_field, None)
        if sort_column is not None:
            if sorting.get("order") == "desc":
                query = query.order_by(sort_column.desc())
            else:
                query = query.order_by(sort_column.asc())
    # if path_search:
    #     # Normalize/Join JSON array like ["A","B"] into "A > B" for path substring search.
    #     normalized_path = func.replace(
    #         func.replace(
    #             func.replace(
    #                 func.replace(func.json_extract(Module.path, "$"), "[", ""),
    #                 "]",
    #                 "",
    #             ),
    #             '"',
    #             "",
    #         ),
    #         ",",
    #         " > ",
    #     )
    #     query = query.where(func.lower(normalized_path).ilike(f"%{path_search.lower()}%"))

    # Count all filtered rows before pagination.
    count_query = select(func.count()).select_from(query.distinct().subquery())
    total_count = session.exec(count_query).one()

    pagination_enabled = paging["page"] is not None or paging["page_size"] is not None
    total_pages: int | None = None
    response_page: int = 1
    response_limit: int | None = None

    if pagination_enabled:
        response_page = paging["page"] if paging["page"] is not None else 1
        response_limit = paging["page_size"] if paging["page_size"] is not None else 50
        offset = (response_page - 1) * response_limit
        modules = session.exec(query.distinct().offset(offset).limit(response_limit)).all()
        total_pages = (total_count + response_limit - 1) // response_limit if total_count > 0 else 0
    else:
        modules = session.exec(query.distinct()).all()

    # include_related = include_children  # Modules have no parent, so include_parent has no effect here.

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
        # if include_related:
        #     items = _attach_module_relations(session, modules, items)

        return {
            "count": total_count,
            "page": response_page,
            "limit": response_limit,
            "total_pages": total_pages,
            "items": items,
        }

    # if include_related:
    #     items = [module.model_dump() for module in modules]
    #     items = _attach_module_relations(session, modules, items, include_children=include_children)
    #     return {
    #         "count": total_count,
    #         "page": response_page,
    #         "limit": response_limit,
    #         "total_pages": total_pages,
    #         "items": items,
    #     }

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
    exports: Annotated[dict, Depends(export_parameters)],
    include: list[IncludeOption] | None = Query(None, description="Related data to include: courses, events, staff. Repeatable for multiple relations."),
    fields: list[ModuleField] | None = Query(None, description="Comma-separated list of fields to include in the response. If not provided, all fields will be included."), # type: ignore
):
    """
    Retrieve a single module by its ID.

    Returns **404** if the module does not exist.
    """
    module = session.get(Module, module_id)
    if module is None:
        raise HTTPException(status_code=404, detail="Module not found")

    # include_related = include_children  # Modules have no parent, so include_parent has no effect here.

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
        # if include_related:
        #     item = _attach_module_relations(session, [module], [item], include_children=include_children)[0]
        # return item

    # if include_related:
    #     item = module.model_dump()
    #     item = _attach_module_relations(session, [module], [item], include_children=include_children)[0]
    #     return JSONResponse(content=jsonable_encoder(item))

    return module

@router.get("/{module_id}/courses", summary="Courses linked to a module")
def get_module_courses(
    module_id: int,
    session: SessionDep,
    paging: Annotated[dict, Depends(paging_parameters)],
    exports: Annotated[dict, Depends(export_parameters)],
    include: list[IncludeOption] | None = Query(None, description="Include data for related entities of courses: events, staff. Repeatable for multiple relations."),
    fields: list[ModuleField] | None = Query(None, description="Comma-separated list of fields to include in the response. If not provided, all fields will be included."), # type: ignore
    sort: SortOption | None = Query(None, description="Sort order for the results. For example, 'name_asc' or 'credits_desc'."),
):
    """
    Retrieve a module courses.
    """
    module = session.exec(select(Module).where(Module.id == module_id)).first()
    if module and module.courses:
        return module.courses

@router.get("/{module_id}/events", summary="Events linked to a module")
def get_module_events(
    module_id: int,
    session: SessionDep,
    paging: Annotated[dict, Depends(paging_parameters)],
    exports: Annotated[dict, Depends(export_event_parameters)],
    date_from: str | None = Query(None, description="Filter events that start on or after this ISO 8601 datetime."),
    date_to: str | None = Query(None, description="Filter events that end on or before this ISO 8601 datetime."),
    weekday: list[int] | None = Query(None, description="Filter events that occur on these weekdays (0=Monday, 6=Sunday). Repeatable for multiple days."),
    include: list[IncludeOption] | None = Query(None, description="Include data for related entities of events: courses, staff. Repeatable for multiple relations."),
    fields: list[ModuleField] | None = Query(None, description="Comma-separated list of fields to include in the response. If not provided, all fields will be included."), # type: ignore
    sort: SortOption | None = Query(None, description="Sort order for the results. For example, 'name_asc' or 'credits_desc'."),
):
    """
    Retrieve a module events.
    """
    module = session.exec(select(Module).where(Module.id == module_id)).first()
    if module and module.courses:
        return [event for course in module.courses if course.events is not None for event in course.events]

@router.get("/{module_id}/staff", summary="Staff linked to a module")
def get_module_staff(
    module_id: int,
    session: SessionDep,
    paging: Annotated[dict, Depends(paging_parameters)],
    exports: Annotated[dict, Depends(export_parameters)],
    include: list[IncludeOption] | None = Query(None, description="Include staff of related courses and events when requesting module staff. Repeatable for multiple relations."),
    fields: list[ModuleField] | None = Query(None, description="Comma-separated list of fields to include in the response. If not provided, all fields will be included."), # type: ignore
    sort: SortOption | None = Query(None, description="Sort order for the results. For example, 'name_asc' or 'credits_desc'."),
):
    """
    Retrieve a module staff.
    """
    module = session.exec(select(Module).where(Module.id == module_id)).first()
    if module and module.responsible_persons:
        return module.responsible_persons

@router.get("/{module_id}/degrees", summary="Degrees linked to a module")
def get_module_degrees(
    module_id: int,
    session: SessionDep,
    paging: Annotated[dict, Depends(paging_parameters)],
    exports: Annotated[dict, Depends(export_parameters)],
    include: list[IncludeOption] | None = Query(None, description="Include degrees of related courses and events when requesting module degrees. Repeatable for multiple relations."),
    fields: list[ModuleField] | None = Query(None, description="Comma-separated list of fields to include in the response. If not provided, all fields will be included."), # type: ignore
    sort: SortOption | None = Query(None, description="Sort order for the results. For example, 'name_asc' or 'credits_desc'."),
):
    """
    Retrieve a module degrees.
    """
    module = session.exec(select(Module).where(Module.id == module_id)).first()
    if module and module.degrees:
        return module.degrees

@router.get("/distinct/{field}", summary="Distinct values for a module field")
def get_distinct_module_field(
    session: SessionDep,
    paging: Annotated[dict, Depends(paging_parameters)],
    field: ModuleField | None, # type: ignore
    sort: str | None = Query(None, description="Sort order for the results. For example, 'asc' or 'desc'."),
    format: str | None = Query(None, description="Response format (e.g., 'json', 'csv')."),
):
    """
    Retrieve distinct values for a module field.
    """
    pass

@router.get("/changes", summary="Get changelog")
def get_module_changes(
    session: SessionDep,
    paging: Annotated[dict, Depends(paging_parameters)],
    since: str = Query(..., description="Filter changes that occurred on or after this ISO 8601 datetime."),
    until: str | None = Query(None, description="Filter changes that occurred before this ISO 8601 datetime."),
    include_deleted: bool = Query(False, description="Whether to include deleted modules in the changelog."),
    sort: SortOption | None = Query(None, description="Sort order for the results. For example, 'name_asc' or 'credits_desc'."),
    format: str | None = Query(None, description="Response format (e.g., 'json', 'csv')."),
):
    """
    Retrieve a module changelog.
    """
    pass