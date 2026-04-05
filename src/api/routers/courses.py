from collections import defaultdict

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import select

from database.database import SessionDep
from database.model import Course, CourseEvent

router = APIRouter(prefix="/courses", tags=["Courses"])


@router.get("", summary="List all Courses")
def get_courses(
    session: SessionDep
):
    """
    Retrieve a list of all courses
    """
    # Base query: select only Course rows
    query = select(Course)

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
