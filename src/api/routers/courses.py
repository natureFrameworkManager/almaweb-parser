from collections import defaultdict

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import select

from database.database import SessionDep
from database.model import Course, Module

router = APIRouter(prefix="/courses", tags=["Courses"])


@router.get("", summary="List all Courses")
def get_courses(
    session: SessionDep,
    type: str | None = Query(None, description="Filter courses by type (case-insensitive, partial match)"),
    language: str | None = Query(None, description="Filter courses by language (case-insensitive, partial match)"),
    staff: str | None = Query(None, description="Filter courses by staff (case-insensitive, partial match)."),
    weekly_hours_min: int | None = Query(None, description="Filter courses with weekly hours greater than or equal to this value"),
    weekly_hours_max: int | None = Query(None, description="Filter courses with weekly hours less than or equal to this value"),
    module_id: int | None = Query(None, description="Filter courses that belong to the specified module ID"),
    module_name: str | None = Query(None, description="Filter courses that belong to a module with the specified name (case-insensitive, partial match)"),
    module_number: str | None = Query(None, description="Filter courses that belong to a module with the specified module number (case-insensitive, partial match)"),
):
    """
    Retrieve a list of all courses
    """
    # Base query: select only Course rows
    query = select(Course)

    # Apply filters based on query parameters
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

    # Fetch distinct courses (join filters can produce duplicates)
    courses = session.exec(query.distinct()).all()

    return courses


@router.get("/{course_id}", summary="Get a course by ID")
def get_course(course_id: int, session: SessionDep):
    """
    Retrieve a single course by its ID.

    Returns **404** if the course does not exist.
    """
    course = session.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")

    return course
