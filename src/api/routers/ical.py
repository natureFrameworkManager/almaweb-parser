from datetime import datetime, time, date

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from icalendar import Calendar, Event
from sqlmodel import select
import re

from database.database import SessionDep
from database.model import CourseEvent, Course, Module

router = APIRouter(prefix="/ical", tags=["iCal"])

@router.get("", summary="Export events as iCal")
def export_ical(
    session: SessionDep,
    date_from: date | None = Query(None, description="Include events on or after this date (YYYY-MM-DD)"),
    date_to: date | None = Query(None, description="Include events on or before this date (YYYY-MM-DD)"),
    start_time: str | None = Query(None, description="Include events starting at or after this time (HH:MM)"),
    end_time: str | None = Query(None, description="Include events ending at or before this time (HH:MM)"),
    location: str | None = Query(None, description="Filter by location (case-insensitive, partial match)"),
    course_id: int | None = Query(None, description="Filter by course ID"),
    course_name: str | None = Query(None, description="Filter by course name (case-insensitive, partial match)"),
    course_number: str | None = Query(None, description="Filter by course number (case-insensitive, partial match)"),
    course_type: str | None = Query(None, description="Filter by course type (case-insensitive, partial match)"),
    module_id: int | None = Query(None, description="Filter by module ID"),
    module_name: str | None = Query(None, description="Filter by module name (case-insensitive, partial match)"),
    module_number: str | None = Query(None, description="Filter by module number (case-insensitive, partial match)"),
):
    """
    Generate an iCalendar (.ics) file of the matching events.
    """
    
    query = select(CourseEvent)

    if date_from:
        query = query.where(CourseEvent.event_date >= date_from)
    if date_to:
        query = query.where(CourseEvent.event_date <= date_to)
    if start_time:
        match = re.match(r"^(\d{2}):(\d{2})$", start_time)
        if not match:
            raise HTTPException(status_code=400, detail="Invalid start_time format. Expected HH:MM.")
        query = query.where(CourseEvent.start_time >= time(int(match.group(1)), int(match.group(2))))
    if end_time:
        match = re.match(r"^(\d{2}):(\d{2})$", end_time)
        if not match:
            raise HTTPException(status_code=400, detail="Invalid end_time format. Expected HH:MM.")
        query = query.where(CourseEvent.end_time <= time(int(match.group(1)), int(match.group(2))))
    if location:
        query = query.where(CourseEvent.location.ilike(f"%{location}%"))  # type: ignore
    if course_id:
        query = query.where(CourseEvent.course_id == course_id)
    if course_name:
        query = query.join(Course).where(Course.name.ilike(f"%{course_name}%"))  # type: ignore
    if course_number:
        query = query.join(Course).where(Course.number.ilike(f"%{course_number}%"))  # type: ignore
    if course_type:
        query = query.join(Course).where(Course.type.ilike(f"%{course_type}%"))  # type: ignore
    if module_id:
        query = query.join(Course).where(Course.module_id == module_id)
    if module_name:
        query = query.join(Course).join(Module).where(Module.name.ilike(f"%{module_name}%"))  # type: ignore
    if module_number:
        query = query.join(Course).join(Module).where(Module.number.ilike(f"%{module_number}%"))  # type: ignore 

    events = session.exec(query.distinct()).all()

    cal = Calendar()
    cal.add("prodid", "-//Almaweb Parser//EN")
    cal.add("version", "2.0")

    for ev in events:
        course: Course | None = session.get(Course, ev.course_id)
        course_label = course.name if course else "Unknown Course"

        ical_event = Event()
        ical_event.add("uid", f"event-{ev.id}@almaweb-parser")
        ical_event.add("summary", course_label)
        ical_event.add("dtstart", datetime.combine(ev.event_date, ev.start_time))
        ical_event.add("dtend", datetime.combine(ev.event_date, ev.end_time))
        if ev.location:
            ical_event.add("location", ev.location)
        if ev.staff:
            ical_event.add("description", f"Dozenten: {', '.join(ev.staff)}")
        cal.add_component(ical_event)

    return Response(
        content=cal.to_ical(),
        media_type="text/calendar",
        headers={"Content-Disposition": "attachment; filename=events.ics"},
    )
