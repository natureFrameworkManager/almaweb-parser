from collections import defaultdict

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import select

from database.database import SessionDep
from database.model import CourseEvent

router = APIRouter(prefix="/events", tags=["Events"])


@router.get("", summary="List all Events")
def get_events(
    session: SessionDep
):
    """
    Retrieve a list of all events
    """
    # Base query: select only CourseEvent rows
    query = select(CourseEvent)

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
