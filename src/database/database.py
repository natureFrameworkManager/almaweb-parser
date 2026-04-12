from typing import TYPE_CHECKING, Annotated

from fastapi import Depends
from sqlmodel import Session, SQLModel, create_engine, select

try:
    from parser.types import CourseType, EventType, ModuleType
except ModuleNotFoundError:
    from src.parser.types import CourseType, EventType, ModuleType

try:
    from .model import Course, Event, Module, ModuleCourseLink, CourseEventLink
except ModuleNotFoundError:
    from src.database.model import Course, Event, Module, ModuleCourseLink, CourseEventLink

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

def _get_or_insert_event_type(session: Session, name: str) -> int:
    """
    Look up an event type by name. If it does not exist, insert it.

    Returns the event type ID.
    """

    try:
        from .model import EventType
    except ModuleNotFoundError:
        from src.database.model import EventType

    event_type = session.exec(select(EventType).where(EventType.name == name)).first()
    if event_type is not None:
        if event_type.id is None:
            raise RuntimeError("Event type to add to database has no id")
        return event_type.id

    event_type = EventType(name=name)
    session.add(event_type)
    session.flush()
    if event_type.id is None:
        raise RuntimeError("Could not get event type id after add and flush to database")
    return event_type.id

def _link_module_course(session: Session, module_id: int, course_id: int):
    """
    Create a link between a module and a course in the ModuleCourseLink association table, if it does not already exist.
    """
    link = session.exec(
        select(ModuleCourseLink)
        .where(ModuleCourseLink.module_id == module_id)
        .where(ModuleCourseLink.course_id == course_id)
    ).first()

    if link is None:
        session.add(ModuleCourseLink(module_id=module_id, course_id=course_id))

def _link_course_event(session: Session, course_id: int, event_id: int):
    """
    Create a link between a course and an event in the CourseEventLink association table, if it does not already exist.
    """
    link = session.exec(
        select(CourseEventLink)
        .where(CourseEventLink.course_id == course_id)
        .where(CourseEventLink.event_id == event_id)
    ).first()

    if link is None:
        session.add(CourseEventLink(course_id=course_id, event_id=event_id))

def _get_or_insert_module(session: Session, module_data: ModuleType) -> tuple[int, bool]:
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
    module = Module(
        name=module_data["name"],
        number=module_data["number"],
        language=module_data.get("language", ""),
        duration_semesters=module_data.get("duration_semesters", 0),
        credits=module_data.get("credits", 0),
        frequency=module_data.get("frequency", ""),
        goals=module_data.get("goals", ""),
        content=module_data.get("content", ""),
        exam_prerequisites=module_data.get("exam_prerequisites", ""),
        prerequisites=str(module_data.get("prerequisites", {})),
    ) # type: ignore
    # Add the module to the session and flush (save to DB) to get an ID assigned, which is needed for linking courses
    session.add(module)
    session.flush()
    if module.id is None:
        raise RuntimeError("Could not get module id after add and flush to database")
    return module.id, True


def _get_or_insert_course(session: Session, course_data: CourseType) -> tuple[int, bool]:
    """
    Look up a course belonging to the given module by name, number, type, and staff. If it does not exist, insert it.

    Returns a tuple of (course_id, was_inserted) where was_inserted is True if a new row was written and False if an existing one was reused.
    """

    # Check if a course of this module and with the same name, number, type, and staff already exists
    course = session.exec(
        select(Course)
        .where(Course.name == course_data["name"])
        .where(Course.number == course_data["number"])
        .where(Course.type == course_data["type"])
    ).first()

    if course is not None:
        if course.id is None:
            raise RuntimeError("Course to add to database has no id")
        return course.id, False

    # Unpacking of course_data into Course constructor, excluding "events" key for separate handling, because "events" is not a field of Course
    course = Course(
        name=course_data["name"],
        number=course_data["number"],
        type=course_data["type"],
        weekly_hours=course_data.get("weekly_hours", 0),
        language=course_data.get("language", ""),
        status=course_data.get("status", 0)
    )  # type: ignore
    # Add the course to the session and flush (save to DB) to get an ID assigned, which is needed for linking events
    session.add(course)
    session.flush()
    if course.id is None:
        raise RuntimeError("Could not get course id after add and flush to database")
    return course.id, True


def _insert_event_if_new(session: Session, event_data: EventType) -> tuple[int, bool]:
    """
    Insert a course event if no identical record (same course, number, date, time slot, location, and staff) already exists.

    Returns True if a new event was inserted, False if it was skipped as a duplicate.
    """

    # Check if an event of this course with the same number, date, time, location, and staff already exists
    event = session.exec(
        select(Event)
        .where(Event.number == event_data["number"])
        .where(Event.event_date == event_data["event_date"])
        .where(Event.start_time == event_data["start_time"])
        .where(Event.end_time == event_data["end_time"])
    ).first()

    if event is not None:
        if event.id is None:
            raise RuntimeError("Event to add to database has no id")
        return event.id, False

    # Unpacking of event_data into CourseEvent constructor, adding course_id for the foreign key relationship
    event = Event(
        number=event_data["number"],
        name=event_data.get("name", ""),
        start_time=event_data["start_time"],
        end_time=event_data["end_time"],
        event_date=event_data.get("event_date", None),
    )  # type: ignore
    session.add(event)
    session.flush()
    if event.id is None:
        raise RuntimeError("Could not get event id after add and flush to database")
    return event.id, True


def insert_module_graph(module_data: ModuleType) -> tuple[bool, dict]:
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
            if course_data is None:
                continue
            course_id, course_inserted = _get_or_insert_course(session, course_data)
            _link_module_course(session, module_id, course_id)
            if course_inserted:
                inserted_count["courses"] += 1
            inserted = inserted or course_inserted

            for event_data in course_data["events"]:
                if event_data is None:
                    continue
                # Insert each event if it does not already exist.
                event_id, event_inserted = _insert_event_if_new(session, event_data)
                _link_course_event(session, course_id, event_id)
                if event_inserted:
                    inserted_count["events"] += 1
                inserted = inserted or event_inserted

        # Commit all changes to the database at once after processing the entire module graph
        # This doesn't insert any record if any error occurs during the process, so all relationships are guaranteed to be consistent
        session.commit()

        return inserted, inserted_count
