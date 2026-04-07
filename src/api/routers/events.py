from collections import defaultdict

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import select
from datetime import time
import re

from database.database import SessionDep
from database.model import CourseEvent, Course, Module

router = APIRouter(prefix="/events", tags=["Events"])


@router.get("", summary="List all Events")
def get_events(
    session: SessionDep,
    date: str | None = Query(None, description="Filter events by date (YYYY-MM-DD)"),
    start_time: str | None = Query(None, description="Filter events that start at or after this time (HH:MM)"),
    end_time: str | None = Query(None, description="Filter events that end at or before this time (HH:MM)"),
    location: str | None = Query(None, description="Filter events by location (case-insensitive, partial match)"),
    course_id: int | None = Query(None, description="Filter events that belong to the specified course ID"),
    course_name: str | None = Query(None, description="Filter events that belong to a course with the specified name (case-insensitive, partial match)"),
    course_number: str | None = Query(None, description="Filter events that belong to a course with the specified number (case-insensitive, partial match)"),
    course_type: str | None = Query(None, description="Filter events that belong to a course with the specified type (case-insensitive, partial match)"),
    module_id: int | None = Query(None, description="Filter events that belong to a course in the specified module ID"),
    module_name: str | None = Query(None, description="Filter events that belong to a course in a module with the specified name (case-insensitive, partial match)"),
    module_number: str | None = Query(None, description="Filter events that belong to a course in a module with the specified module number (case-insensitive, partial match)"),
):
    """
    Retrieve a list of all events
    """
    # Base query: select only CourseEvent rows
    query = select(CourseEvent)

    # Apply filters based on query parameters
    if date:
        query = query.where(CourseEvent.event_date == date)
    if start_time:
        start_time_match = re.match(r"^(\d{2}):(\d{2})$", start_time)
        if not start_time_match:
            raise HTTPException(status_code=400, detail="Invalid start_time format. Expected HH:MM.")
        parsed_start_time = time(int(start_time_match.group(1)), int(start_time_match.group(2)))
        query = query.where(CourseEvent.start_time >= parsed_start_time)
    if end_time:
        end_time_match = re.match(r"^(\d{2}):(\d{2})$", end_time)
        if not end_time_match:
            raise HTTPException(status_code=400, detail="Invalid end_time format. Expected HH:MM.")
        parsed_end_time = time(int(end_time_match.group(1)), int(end_time_match.group(2)))
        query = query.where(CourseEvent.end_time <= parsed_end_time)
    if location:
        query = query.where(CourseEvent.location.ilike(f"%{location}%")) # type: ignore
    if course_id is not None:
        query = query.where(CourseEvent.course_id == course_id)
    if course_name:
        query = query.join(Course).where(Course.name.ilike(f"%{course_name}%")) # type: ignore
    if course_number:
        query = query.join(Course).where(Course.number.ilike(f"%{course_number}%")) # type: ignore
    if course_type:
        query = query.join(Course).where(Course.type.ilike(f"%{course_type}%")) # type: ignore
    if module_id is not None:
        query = query.join(Course).where(Course.module_id == module_id)
    if module_name:
        query = query.join(Course).join(Module).where(Module.name.ilike(f"%{module_name}%")) # type: ignore
    if module_number:
        query = query.join(Course).join(Module).where(Module.number.ilike(f"%{module_number}%")) # type: ignore

    # Fetch distinct events (join filters can produce duplicates)
    events = session.exec(query.distinct()).all()

    return events


@router.get("/{event_id}", summary="Get an event by ID")
def get_event(event_id: int, session: SessionDep):
    """
    Retrieve a single event by its ID.

    Returns **404** if the event does not exist.
    """
    event = session.get(CourseEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")

    return event
