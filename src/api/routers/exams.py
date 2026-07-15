from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_
from sqlmodel import select

from database.model import Course, Event, Module, Staff, ModuleExam
from .shared import SessionDep, export_parameters, export_event_parameters, paging_parameters, page_query, sort_query, filter_query, sort_parameters, fields_parameters, include_parameters, build_list_response, build_event_list_response, get_or_404, distinct_parameters, PROBLEM_RESPONSES, _ical_augment_including
from schemas import PaginatedResponse, ExamRead, CourseRead, EventRead, ModuleRead, StaffRead
from .events import parse_iso_date, parse_hhmm_time

router = APIRouter(prefix="/exams", tags=["Exams"], responses=PROBLEM_RESPONSES)


@router.get("", summary="List all Exams", response_model=PaginatedResponse[ExamRead], response_model_exclude_unset=True)
def get_exams(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(ModuleExam))],
    including: Annotated[dict, Depends(include_parameters(ModuleExam))],
    fielding: Annotated[dict, Depends(fields_parameters(ModuleExam))],
    paging: Annotated[dict, Depends(paging_parameters)],
    exports: Annotated[dict, Depends(export_parameters)],
    name: list[str] | None = Query(None, description="Exam name values (repeatable; case-insensitive, partial match; OR within this filter)."),
    exam_date: list[str] | None = Query(None, description="Exam date values (repeatable; YYYY-MM-DD; OR within this filter)."),
    exam_date_from: str | None = Query(None, description="Minimum exam date (YYYY-MM-DD) for the exam"),
    exam_date_to: str | None = Query(None, description="Maximum exam date (YYYY-MM-DD) for the exam"),
    start_time_from: str | None = Query(None, description="Minimum start time (HH:MM:SS) for the exam"),
    start_time_to: str | None = Query(None, description="Maximum start time (HH:MM:SS) for the exam"),
    end_time_from: str | None = Query(None, description="Minimum end time (HH:MM:SS) for the exam"),
    end_time_to: str | None = Query(None, description="Maximum end time (HH:MM:SS) for the exam"),
    required: bool | None = Query(None, description="Filter by whether an exam is required (true) or optional (false)."),    
    staff: list[str] | None = Query(None, description="Exam staff values (repeatable; case-insensitive, partial match; OR within this filter)."),
    module_id: list[int] | None = Query(None, description="Module IDs the exam belongs to (repeatable; direct match; OR within this filter)."),
    module_name: list[str] | None = Query(None, description="Module name values (repeatable; case-insensitive, partial match; OR within this filter)."),
    module_number: list[str] | None = Query(None, description="Module number values (repeatable; case-insensitive, partial match; OR within this filter)."),
):
    """
    Retrieve a list of all exams
    """
    # Base query: select only ModuleExam rows
    query = select(ModuleExam)

    # Apply filters based on query parameters
    if name:
        query = query.where(or_(*[ModuleExam.name.ilike(f"%{value}%") for value in name])) # type: ignore
    if exam_date:
        query = query.where(or_(*[ModuleExam.exam_date == parse_iso_date(value, "exam_date") for value in exam_date])) # type: ignore
    if exam_date_from:
        query = query.where(ModuleExam.exam_date != None).where(ModuleExam.exam_date >= parse_iso_date(exam_date_from, "exam_date_from")) # type: ignore
    if exam_date_to:
        query = query.where(ModuleExam.exam_date != None).where(ModuleExam.exam_date <= parse_iso_date(exam_date_to, "exam_date_to")) # type: ignore
    if start_time_from:
        query = query.where(ModuleExam.start_time != None).where(ModuleExam.start_time >= parse_hhmm_time(start_time_from, "start_time_from")) # type: ignore
    if start_time_to:
        query = query.where(ModuleExam.start_time != None).where(ModuleExam.start_time <= parse_hhmm_time(start_time_to, "start_time_to")) # type: ignore
    if end_time_from:
        query = query.where(ModuleExam.end_time != None).where(ModuleExam.end_time >= parse_hhmm_time(end_time_from, "end_time_from")) # type: ignore
    if end_time_to:
        query = query.where(ModuleExam.end_time != None).where(ModuleExam.end_time <= parse_hhmm_time(end_time_to, "end_time_to")) # type: ignore
    if required is not None:
        query = query.where(ModuleExam.required == required)
    if staff:
        query = query.where(or_(*[ModuleExam.staff.any(Staff.name.ilike(f"%{value}%")) for value in staff])) # type: ignore
    if module_id:
        query = query.where(ModuleExam.module_id.in_(module_id)) # type: ignore
    if module_name or module_number:
        query = query.join(ModuleExam.module) # type: ignore
        if module_name:
            query = query.where(or_(*[Module.name.ilike(f"%{value}%") for value in module_name])) # type: ignore
        if module_number:
            query = query.where(or_(*[Module.number.ilike(f"%{value}%") for value in module_number])) # type: ignore

    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, ModuleExam)
    items = filter_query(session, query, fielding, ModuleExam, including)
    return build_list_response(data, items, exports)


@router.get("/{exam_id}", summary="Get an exam by ID", response_model=ExamRead, response_model_exclude_unset=True)
def get_exam(
    exam_id: int,
    session: SessionDep,
    including: Annotated[dict, Depends(include_parameters(ModuleExam))],
    fielding: Annotated[dict, Depends(fields_parameters(ModuleExam))],
    export: Annotated[dict, Depends(export_parameters)],
):
    """
    Retrieve a single exam by its ID.

    Returns **404** if the exam does not exist.
    """
    get_or_404(session, ModuleExam, exam_id, "ModuleExam")
    query = select(ModuleExam).where(ModuleExam.id == exam_id)
    items = filter_query(session, query, fielding, ModuleExam, including)
    return items[0] if items else None

@router.get("/{exam_id}/modules", summary="Get modules linked to an exam", response_model=PaginatedResponse[ModuleRead], response_model_exclude_unset=True)
def get_exam_modules(
    exam_id: int,
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Module))],
    including: Annotated[dict, Depends(include_parameters(Module))],
    fielding: Annotated[dict, Depends(fields_parameters(Module))],
    paging: Annotated[dict, Depends(paging_parameters)],
    exports: Annotated[dict, Depends(export_parameters)],
):
    """Retrieve the modules associated with a specific exam."""
    query = select(Module).where(Module.exams.any(ModuleExam.id == exam_id))  # type: ignore
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Module)
    items = filter_query(session, query, fielding, Module, including)
    return build_list_response(data, items, exports)

@router.get("/{exam_id}/staff", summary="Get staff for an exam", response_model=PaginatedResponse[StaffRead], response_model_exclude_unset=True)
def get_exam_staff(
    exam_id: int,
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Staff))],
    including: Annotated[dict, Depends(include_parameters(Staff))],
    fielding: Annotated[dict, Depends(fields_parameters(Staff))],
    paging: Annotated[dict, Depends(paging_parameters)],
    exports: Annotated[dict, Depends(export_parameters)],
):
    """Retrieve the staff associated with a specific exam."""
    query = select(Staff).where(Staff.exams.any(ModuleExam.id == exam_id))  # type: ignore
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Staff)
    items = filter_query(session, query, fielding, Staff, including)
    return build_list_response(data, items, exports)

@router.get("/distinct/fields", summary="Get distinct values for a exam field")
def get_exam_distinct_field(
    session: SessionDep,
    field_name: Annotated[dict, Depends(distinct_parameters(ModuleExam))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
):
    """Retrieve distinct values for a specific field across all exams."""
    field = field_name.get("field")
    order = field_name.get("order")
    query = select(getattr(ModuleExam, field)).distinct()  # type: ignore
    if order:
        sort_column = getattr(ModuleExam, field)  # type: ignore
        query = query.order_by(sort_column.asc() if order.lower() == "asc" else sort_column.desc())
    data, query = page_query(session, query, paging)
    items = [{field: value} for value in session.exec(query).all()]
    return build_list_response(data, items, export)