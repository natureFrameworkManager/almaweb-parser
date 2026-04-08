from collections import defaultdict
from enum import Enum
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func
from sqlmodel import select

from database.database import SessionDep
from database.model import Course, Module


class CourseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    name: str | None = None
    number: str | None = None
    staff: list[str] | None = None
    type: str | None = None
    weekly_hours: int | None = None
    language: str | None = None
    module_id: int | None = None


class CourseListResponse(BaseModel):
    count: int
    page: int
    limit: int | None
    total_pages: int | None
    items: list[CourseRead | dict[str, Any]]


router = APIRouter(prefix="/courses", tags=["Courses"])
CourseField = Enum("CourseField", {f: f for f in Course.model_fields})


@router.get("", summary="List all Courses")
def get_courses(
    session: SessionDep,
    name: str | None = Query(None, description="Course name (case-insensitive, partial match)"),
    number: str | None = Query(None, description="Course number (case-insensitive, partial match)"),
    type: str | None = Query(None, description="Course type (case-insensitive, partial match), (e.g. \"Vorlesung\", \"Seminar\", etc.)"),
    language: str | None = Query(None, description="Course language (case-insensitive, partial match)"),
    staff: str | None = Query(None, description="Course staff (case-insensitive, partial match)."),
    weekly_hours_min: int | None = Query(None, description="Minimum weekly hours for the course"),
    weekly_hours_max: int | None = Query(None, description="Maximum weekly hours for the course"),
    module_id: int | None = Query(None, description="ID of the module the course belongs to"),
    module_name: str | None = Query(None, description="Name of the module the course belongs to (case-insensitive, partial match)"),
    module_number: str | None = Query(None, description="Number of the module the course belongs to (case-insensitive, partial match)"),
    page: int | None = Query(None, ge=1, description="Page number (starts at 1). If omitted together with limit, pagination is disabled."),
    limit: int | None = Query(None, ge=1, description="Number of courses returned per page. If omitted together with page, pagination is disabled."),
    fields: list[CourseField] | None = Query(None, description="Comma-separated list of fields to include in the response. If not provided, all fields will be included.") # type: ignore
):
    """
    Retrieve a list of all courses
    """
    # Base query: select only Course rows
    query = select(Course)

    # Apply filters based on query parameters
    if name:
        query = query.where(Course.name.ilike(f"%{name}%")) # type: ignore
    if number:
        query = query.where(Course.number.ilike(f"%{number}%")) # type: ignore
    if type:
        query = query.where(Course.type.ilike(f"%{type}%")) # type: ignore
    if language:
        query = query.where(Course.language.ilike(f"%{language}%")) # type: ignore
    if staff:
        query = query.where(Course.staff.ilike(f"%{staff}%")) # type: ignore
    if weekly_hours_min is not None:
        query = query.where(Course.weekly_hours >= weekly_hours_min)
    if weekly_hours_max is not None:
        query = query.where(Course.weekly_hours <= weekly_hours_max)
    if module_id is not None:
        query = query.where(Course.module_id == module_id)
    if module_name:
        query = query.join(Course.module).where(Module.name.ilike(f"%{module_name}%")) # type: ignore
    if module_number:
        query = query.join(Course.module).where(Module.number.ilike(f"%{module_number}%")) # type: ignore

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
        courses = session.exec(query.distinct().offset(offset).limit(response_limit)).all()
        total_pages = (total_count + response_limit - 1) // response_limit if total_count > 0 else 0
    else:
        courses = session.exec(query.distinct()).all()

    if fields:
        requested_fields = {
            field.strip()
            for value in fields
            for field in value.value.split(",")
            if field.strip()
        }
        valid_fields = set(Course.model_fields.keys())
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
                    field: course.model_dump().get(field)
                    for field in selected_fields
                }
                for course in courses
            ],
        }

    return {
        "count": total_count,
        "page": response_page,
        "limit": response_limit,
        "total_pages": total_pages,
        "items": courses,
    }


@router.get("/{course_id}", summary="Get a course by ID", response_model=CourseRead)
def get_course(course_id: int, session: SessionDep):
    """
    Retrieve a single course by its ID.

    Returns **404** if the course does not exist.
    """
    course = session.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")

    return course
