from enum import Enum
from typing import Any, Sequence, Annotated

from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy import func, or_
from sqlmodel import select

from database.database import SessionDep
from database.model import Module, Course, Event, Staff, Degree
from schemas.modules import ModuleDetailResponseModel, ModuleListResponseModel
from .shared import export_event_parameters, export_parameters, paging_parameters, model_field_enum, sort_parameters, fields_parameters, page_query, sort_query, filter_query


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
    fielding: Annotated[dict, Depends(fields_parameters(Module))],
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


@router.get("/{module_id}", summary="Get a module by ID", response_model=ModuleDetailResponseModel)
def get_module(
    module_id: int,
    session: SessionDep,
    fielding: Annotated[dict, Depends(fields_parameters(Module))],
    exports: Annotated[dict, Depends(export_parameters)],
    include: list[IncludeOption] | None = Query(None, description="Related data to include: courses, events, staff. Repeatable for multiple relations."),
):
    """
    Retrieve a single module by its ID.

    Returns **404** if the module does not exist.
    """
    module = session.get(Module, module_id)
    if module is None:
        raise HTTPException(status_code=404, detail="Module not found")
    query = select(Module).where(Module.id == module_id)
    items = filter_query(session, query, fielding, Module)
    return items[0] if items else None

@router.get("/{module_id}/courses", summary="Courses linked to a module")
def get_module_courses(
    module_id: int,
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Course))],
    fielding: Annotated[dict, Depends(fields_parameters(Course))],
    paging: Annotated[dict, Depends(paging_parameters)],
    exports: Annotated[dict, Depends(export_parameters)],
    include: list[IncludeOption] | None = Query(None, description="Include data for related entities of courses: events, staff. Repeatable for multiple relations."),
):
    """
    Retrieve a module courses.
    """
    query = select(Course).where(Course.modules.any(Module.id == module_id))  # type: ignore
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Course)
    items = filter_query(session, query, fielding, Course)
    return {
        "count": data["count"],
        "page": data["page"],
        "limit": data["limit"],
        "total_pages": data["total_pages"],
        "items": items,
    }

@router.get("/{module_id}/events", summary="Events linked to a module")
def get_module_events(
    module_id: int,
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Event))],
    fielding: Annotated[dict, Depends(fields_parameters(Event))],
    paging: Annotated[dict, Depends(paging_parameters)],
    exports: Annotated[dict, Depends(export_event_parameters)],
    date_from: str | None = Query(None, description="Filter events that start on or after this ISO 8601 datetime."),
    date_to: str | None = Query(None, description="Filter events that end on or before this ISO 8601 datetime."),
    weekday: list[int] | None = Query(None, description="Filter events that occur on these weekdays (0=Monday, 6=Sunday). Repeatable for multiple days."),
    include: list[IncludeOption] | None = Query(None, description="Include data for related entities of events: courses, staff. Repeatable for multiple relations."),
):
    """
    Retrieve a module events.
    """
    query = select(Event).where(Event.courses.any(Course.modules.any(Module.id == module_id)))  # type: ignore
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Event)
    items = filter_query(session, query, fielding, Event)
    return {
        "count": data["count"],
        "page": data["page"],
        "limit": data["limit"],
        "total_pages": data["total_pages"],
        "items": items,
    }

@router.get("/{module_id}/staff", summary="Staff linked to a module")
def get_module_staff(
    module_id: int,
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Staff))],
    fielding: Annotated[dict, Depends(fields_parameters(Staff))],
    paging: Annotated[dict, Depends(paging_parameters)],
    exports: Annotated[dict, Depends(export_parameters)],
    include: list[IncludeOption] | None = Query(None, description="Include staff of related courses and events when requesting module staff. Repeatable for multiple relations."),
):
    """
    Retrieve a module staff.
    """
    query = select(Staff).where(Staff.modules.any(Module.id == module_id))  # type: ignore
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Staff)
    items = filter_query(session, query, fielding, Staff)
    return {
        "count": data["count"],
        "page": data["page"],
        "limit": data["limit"],
        "total_pages": data["total_pages"],
        "items": items,
    }

@router.get("/{module_id}/degrees", summary="Degrees linked to a module")
def get_module_degrees(
    module_id: int,
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Degree))],
    fielding: Annotated[dict, Depends(fields_parameters(Degree))],
    paging: Annotated[dict, Depends(paging_parameters)],
    exports: Annotated[dict, Depends(export_parameters)],
    include: list[IncludeOption] | None = Query(None, description="Include degrees of related courses and events when requesting module degrees. Repeatable for multiple relations."),
):
    """
    Retrieve a module degrees.
    """
    query = select(Degree).where(Degree.modules.any(Module.id == module_id))  # type: ignore
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