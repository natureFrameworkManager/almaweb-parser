from typing import Annotated

from fastapi import Depends
from sqlmodel import Session, SQLModel, create_engine, select

from .model import Course, Event, Module


DATABASE_URL = "sqlite:///database.db"

engine = create_engine(DATABASE_URL, echo=False)


def create_db_and_tables():
    """
    Create all database tables defined in the SQLModel metadata, if they do not already exist.
    """
    SQLModel.metadata.create_all(engine)


def get_session():
    """
    FastAPI dependency that opens a database session, yields it for use in a request handler, and closes it automatically when the request is done.
    """
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def _get_or_insert_module(session: Session, module_data: dict) -> tuple[int, bool]:
    """
    Look up a module by number and name. If it does not exist, insert it.

    Returns a tuple of (module_id, was_inserted) where was_inserted is True if a new row was written and False if an existing one was reused.
    """
    
    # Check if a module with the same number and name already exists
    module = session.exec(
        select(Module)
        .where(Module.number == module_data["number"])
        .where(Module.name == module_data["name"])
    ).first()

    if module is not None:
        if module.id is None:
            raise RuntimeError("Module to add to database has no id")
        return module.id, False

    # Unpacking of module_data into Module constructor, excluding "courses" key for separate handling, because "courses" is not a field of Module
    module = Module(**{k: v for k, v in module_data.items() if k != "courses"})
    # Add the module to the session and flush (save to DB) to get an ID assigned, which is needed for linking courses
    session.add(module)
    session.flush()
    if module.id is None:
        raise RuntimeError("Could not get module id after add and flush to database")
    return module.id, True


def _get_or_insert_course(session: Session, course_data: dict, module_id: int) -> tuple[int, bool]:
    """
    Look up a course belonging to the given module by name, number, type, and staff. If it does not exist, insert it.

    Returns a tuple of (course_id, was_inserted) where was_inserted is True if a new row was written and False if an existing one was reused.
    """

    # Check if a course of this module and with the same name, number, type, and staff already exists
    course = session.exec(
        select(Course)
        .where(Course.module_id == module_id)
        .where(Course.name == course_data["name"])
        .where(Course.number == course_data["number"])
        .where(Course.type == course_data["type"])
        .where(Course.staff == course_data["staff"])
    ).first()

    if course is not None:
        if course.id is None:
            raise RuntimeError("Course to add to database has no id")
        return course.id, False

    # Unpacking of course_data into Course constructor, excluding "events" key for separate handling, because "events" is not a field of Course
    course = Course(**{k: v for k, v in course_data.items() if k != "events"}, module_id=module_id)
    # Add the course to the session and flush (save to DB) to get an ID assigned, which is needed for linking events
    session.add(course)
    session.flush()
    if course.id is None:
        raise RuntimeError("Could not get course id after add and flush to database")
    return course.id, True


def _insert_event_if_new(session: Session, event_data: dict, course_id: int) -> bool:
    """
    Insert a course event if no identical record (same course, number, date, time slot, location, and staff) already exists.

    Returns True if a new event was inserted, False if it was skipped as a duplicate.
    """

    # Check if an event of this course with the same number, date, time, location, and staff already exists
    already_exists = session.exec(
        select(Event)
        .where(Event.course_id == course_id)
        .where(Event.number == event_data["number"])
        .where(Event.event_date == event_data["event_date"])
        .where(Event.start_time == event_data["start_time"])
        .where(Event.end_time == event_data["end_time"])
        .where(Event.location == event_data["location"])
        .where(Event.staff == event_data["staff"])
    ).first()

    if already_exists:
        return False

    # Unpacking of event_data into CourseEvent constructor, adding course_id for the foreign key relationship
    session.add(Event(**event_data, course_id=course_id))
    return True


def insert_module_graph(module_data: dict) -> tuple[bool, dict]:
    """
    Insert a complete module graph - the module itself, its courses, and each course's events - skipping any records that already exist.

    All inserts are committed in a single transaction. If anything fails, no partial data is written and the exception propagates to the caller.

    Returns a tuple of:
    - inserted (bool): True if at least one new record was written.
    - inserted_count (dict): Per-type counts with keys 'modules', 'courses', and 'events'.
    """
    inserted_count = {
        "modules": 0,
        "courses": 0,
        "events": 0
    }
    with Session(engine) as session:
        # Get or insert the module, and get its ID for linking courses
        module_id, inserted = _get_or_insert_module(session, module_data)
        if inserted:
            inserted_count["modules"] += 1

        for course_data in module_data["courses"]:
            # Get or insert each course, and get its corresponding ID for linking the events
            course_id, course_inserted = _get_or_insert_course(session, course_data, module_id)
            if course_inserted:
                inserted_count["courses"] += 1
            inserted = inserted or course_inserted

            for event_data in course_data["events"]:
                # Insert each event if it does not already exist.
                if _insert_event_if_new(session, event_data, course_id):
                    inserted_count["events"] += 1
                    inserted = True

        # Commit all changes to the database at once after processing the entire module graph
        # This doesn't insert any record if any error occurs during the process, so all relationships are guaranteed to be consistent
        session.commit()

        return inserted, inserted_count
