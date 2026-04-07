from typing import Annotated

from fastapi import Depends
from sqlmodel import Session, SQLModel, create_engine, select

from .model import Course, CourseEvent, Module


DATABASE_URL = "sqlite:///database.db"

engine = create_engine(DATABASE_URL, echo=False)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def _get_or_insert_module(session: Session, module_data: dict) -> tuple[int, bool]:
    """Return (module_id, was_inserted)."""
    
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
    """Return (course_id, was_inserted)."""

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
    """Insert the event and return True, or return False if it already exists."""

    # Check if an event of this course with the same number, date, time, location, and staff already exists
    already_exists = session.exec(
        select(CourseEvent)
        .where(CourseEvent.course_id == course_id)
        .where(CourseEvent.number == event_data["number"])
        .where(CourseEvent.event_date == event_data["event_date"])
        .where(CourseEvent.start_time == event_data["start_time"])
        .where(CourseEvent.end_time == event_data["end_time"])
        .where(CourseEvent.location == event_data["location"])
        .where(CourseEvent.staff == event_data["staff"])
    ).first()

    if already_exists:
        return False

    # Unpacking of event_data into CourseEvent constructor, adding course_id for the foreign key relationship
    session.add(CourseEvent(**event_data, course_id=course_id))
    return True


def insert_module_graph(module_data: dict) -> tuple[bool, dict]:
    """Insert newly discovered module, course, and event records.

    Returns True if any new record was written to the database.
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
