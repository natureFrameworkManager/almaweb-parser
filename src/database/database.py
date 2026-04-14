import re
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends
from sqlmodel import Session, SQLModel, create_engine, select

try:
    from parser.types import CourseType, EventType, ModuleType, RoomType, BuildingType
except ModuleNotFoundError:
    from src.parser.types import CourseType, EventType, ModuleType, RoomType, BuildingType

try:
    from .model import Course, Event, Module, ModuleCourseLink, CourseEventLink, Faculty
except ModuleNotFoundError:
    from src.database.model import Course, Event, Module, ModuleCourseLink, CourseEventLink, Faculty

#DATABASE_URL = "sqlite:///database.db"
DATABASE_URL = "mariadb+pymysql://root:notSecureChangeMe@localhost:3306/almaweb_parser"

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

def _get_or_insert_status(session: Session, name: str) -> int:
    """
    Look up a course status by name. If it does not exist, insert it.

    Returns the course status ID.
    """

    try:
        from .model import Status
    except ModuleNotFoundError:
        from src.database.model import Status

    status = session.exec(select(Status).where(Status.name == name)).first()
    if status is not None:
        if status.id is None:
            raise RuntimeError("Course status to add to database has no id")
        return status.id

    status = Status(name=name)
    session.add(status)
    session.flush()
    if status.id is None:
        raise RuntimeError("Could not get course status id after add and flush to database")
    return status.id

def _get_or_insert_staff(session: Session, name: str) -> int:
    """
    Look up a staff member by name. If they do not exist, insert them.

    Returns the staff member ID.
    """

    try:
        from .model import Staff
    except ModuleNotFoundError:
        from src.database.model import Staff

    staff = session.exec(select(Staff).where(Staff.name == name)).first()
    if staff is not None:
        if staff.id is None:
            raise RuntimeError("Staff member to add to database has no id")
        return staff.id

    staff = Staff(name=name)
    session.add(staff)
    session.flush()
    if staff.id is None:
        raise RuntimeError("Could not get staff member id after add and flush to database")
    return staff.id

def _get_or_insert_building(session: Session, building_data: BuildingType) -> int:
    """
    Look up a building by its name, short name, and address. If it does not exist, insert it.

    Returns the building ID.
    """

    try:
        from .model import Building
    except ModuleNotFoundError:
        from src.database.model import Building

    building = session.exec(
        select(Building)
        .where(Building.name == building_data["name"])
        .where(Building.short_name == building_data["short_name"])
        .where(Building.address == building_data["address"])
    ).first()

    if building is not None:
        if building.id is None:
            raise RuntimeError("Building to add to database has no id")
        return building.id

    building = Building(
        name=building_data["name"],
        short_name=building_data["short_name"],
        address=building_data["address"]
    )
    session.add(building)
    session.flush()
    if building.id is None:
        raise RuntimeError("Could not get building id after add and flush to database")
    return building.id

def _get_or_insert_location(session: Session, room_data: RoomType) -> int:
    """
    Look up a location (room) by its external ID. If it does not exist, insert it.

    Returns the location ID.
    """

    try:
        from .model import Location
    except ModuleNotFoundError:
        from src.database.model import Location

    location = session.exec(select(Location).where(Location.external_id == room_data["external_id"])).first()
    if location is not None:
        if location.id is None:
            raise RuntimeError("Location to add to database has no id")
        return location.id
    
    building_id = _get_or_insert_building(session, room_data["building"])

    location = Location(
        name=room_data["name"],
        external_id=room_data["external_id"],
        description=room_data.get("description", ""),
        type=room_data.get("type", ""),
        seats=room_data.get("seats"),
        size=room_data.get("size"),
        accessibility=room_data.get("accessibility", ""),
        building_id=building_id
    )
    session.add(location)
    session.flush()
    if location.id is None:
        raise RuntimeError("Could not get location id after add and flush to database")
    return location.id

def get_or_insert_faculty(session: Session, name: str, prefix: int) -> int:
    """
    Look up a faculty by name. If it does not exist, insert it.

    Returns the faculty ID.
    """

    try:
        from .model import Faculty
    except ModuleNotFoundError:
        from src.database.model import Faculty

    faculty = session.exec(select(Faculty).where(Faculty.name == name)).first()
    if faculty is not None:
        if faculty.id is None:
            raise RuntimeError("Faculty to add to database has no id")
        return faculty.id

    faculty = Faculty(name=name, prefix=prefix)
    session.add(faculty)
    session.flush()
    if faculty.id is None:
        raise RuntimeError("Could not get faculty id after add and flush to database")
    return faculty.id

def _get_or_insert_semester(session: Session, name: str, year: int, term: str) -> int:
    """
    Look up a semester by name. If it does not exist, insert it.

    Returns the semester ID.
    """

    try:
        from .model import Semester
    except ModuleNotFoundError:
        from src.database.model import Semester

    semester = session.exec(select(Semester).where(Semester.name == name)).first()
    if semester is not None:
        if semester.id is None:
            raise RuntimeError("Semester to add to database has no id")
        return semester.id

    semester = Semester(name=name, year=year, term=term)
    session.add(semester)
    session.flush()
    if semester.id is None:
        raise RuntimeError("Could not get semester id after add and flush to database")
    return semester.id

def _find_faculty_by_prefix(session: Session, prefix: int) -> Faculty | None:
    """
    Look up a faculty by its prefix (short code). Returns the Faculty object if found, or None if no faculty with the given prefix exists.
    """

    try:
        from .model import Faculty
    except ModuleNotFoundError:
        from src.database.model import Faculty

    faculty = session.exec(select(Faculty).where(Faculty.prefix == prefix)).first()
    return faculty

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

def _link_module_semester(session: Session, module_id: int, semester_id: int):
    """
    Create a link between a module and a semester in the ModuleSemesterLink association table, if it does not already exist.
    """
    try:
        from .model import ModuleSemesterLink
    except ModuleNotFoundError:
        from src.database.model import ModuleSemesterLink

    link = session.exec(
        select(ModuleSemesterLink)
        .where(ModuleSemesterLink.module_id == module_id)
        .where(ModuleSemesterLink.semester_id == semester_id)
    ).first()

    if link is None:
        session.add(ModuleSemesterLink(module_id=module_id, semester_id=semester_id))

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

def _link_module_responsible_person(session: Session, module_id: int, staff_id: int):
    """
    Create a link between a module and its responsible person in the ModuleStaffLink association table, if it does not already exist.
    """
    try:
        from .model import ModuleStaffLink
    except ModuleNotFoundError:
        from src.database.model import ModuleStaffLink

    link = session.exec(
        select(ModuleStaffLink)
        .where(ModuleStaffLink.module_id == module_id)
        .where(ModuleStaffLink.staff_id == staff_id)
    ).first()

    if link is None:
        session.add(ModuleStaffLink(module_id=module_id, staff_id=staff_id))

def _link_course_staff(session: Session, course_id: int, staff_id: int):
    """
    Create a link between a course and a staff member in the CourseStaffLink association table, if it does not already exist.
    """
    try:
        from .model import CourseStaffLink
    except ModuleNotFoundError:
        from src.database.model import CourseStaffLink

    link = session.exec(
        select(CourseStaffLink)
        .where(CourseStaffLink.course_id == course_id)
        .where(CourseStaffLink.staff_id == staff_id)
    ).first()

    if link is None:
        session.add(CourseStaffLink(course_id=course_id, staff_id=staff_id))

def _link_event_staff(session: Session, event_id: int, staff_id: int):
    """
    Create a link between an event and a staff member in the EventStaffLink association table, if it does not already exist.
    """
    try:
        from .model import EventStaffLink
    except ModuleNotFoundError:
        from src.database.model import EventStaffLink

    link = session.exec(
        select(EventStaffLink)
        .where(EventStaffLink.event_id == event_id)
        .where(EventStaffLink.staff_id == staff_id)
    ).first()

    if link is None:
        session.add(EventStaffLink(event_id=event_id, staff_id=staff_id))

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
    
    faculty_id = None
    module_number_prefix_match = re.match(r"^A?(\d{2})", module_data["number"])
    if module_number_prefix_match:
        faculty = _find_faculty_by_prefix(session, int(module_number_prefix_match.group(1)))
        if faculty is not None:
            faculty_id = faculty.id

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
        prerequisites=module_data.get("prerequisites", {}),
        path=module_data.get("path", []),
        faculty_id=faculty_id
    ) # type: ignore
    # Add the module to the session and flush (save to DB) to get an ID assigned, which is needed for linking courses
    session.add(module)
    session.flush()
    if module.id is None:
        raise RuntimeError("Could not get module id after add and flush to database")
    # Link module responsible person to the module, inserting them if they do not already exist
    responsible_person_name = module_data.get("responsible_person", "")
    if responsible_person_name:
        staff_id = _get_or_insert_staff(session, responsible_person_name)
        _link_module_responsible_person(session, module.id, staff_id)
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
        .where(Course.type == _get_or_insert_event_type(session, course_data["type"]))
        .where(Course.language == course_data.get("language", ""))
    ).first()

    if course is not None:
        if course.id is None:
            raise RuntimeError("Course to add to database has no id")
        return course.id, False

    # Unpacking of course_data into Course constructor, excluding "events" key for separate handling, because "events" is not a field of Course
    course = Course(
        name=course_data["name"],
        number=course_data["number"],
        type=_get_or_insert_event_type(session, course_data["type"]),
        weekly_hours=course_data.get("weekly_hours", 0),
        language=course_data.get("language", ""),
        status=_get_or_insert_status(session, course_data.get("status", ""))
    )  # type: ignore
    # Add the course to the session and flush (save to DB) to get an ID assigned, which is needed for linking events
    session.add(course)
    session.flush()
    if course.id is None:
        raise RuntimeError("Could not get course id after add and flush to database")
    
    # Link staff members to the course, inserting them if they do not already exist
    for staff_name in course_data.get("staff", []):
        staff_id = _get_or_insert_staff(session, staff_name)
        _link_course_staff(session, course.id, staff_id)

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
    
    location_id = None
    if event_data["location"] is not None:
        location_id = _get_or_insert_location(session, event_data["location"])

    # Unpacking of event_data into CourseEvent constructor, adding course_id for the foreign key relationship
    event = Event(
        number=event_data["number"],
        name=event_data.get("name", ""),
        start_time=event_data["start_time"],
        end_time=event_data["end_time"],
        event_date=event_data.get("event_date", None),
        location_id=location_id
    )  # type: ignore
    session.add(event)
    session.flush()
    if event.id is None:
        raise RuntimeError("Could not get event id after add and flush to database")

    # Link staff members to the event, inserting them if they do not already exist
    for staff_name in event_data.get("staff", []):
        staff_id = _get_or_insert_staff(session, staff_name)
        _link_event_staff(session, event.id, staff_id)

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
        faculty_name = None
        faculty_prefix = None
        if len(module_data["path"]) > 0:
            # Fakultät started mit "(A)[0-9][0-9] - ...", z.B. "A10 - Fakultät für Mathematik und Informatik" or "A07 - Wirtschaftswissenschaftliche Fakultät"
            # We extract the faculty name from the navigation path, which is needed for the foreign key relationship. If no faculty can be identified, we leave it null.
            # The faculty name is usually the third element in the path, but we check all elements to be safe, because the structure is not perfectly consistent. We look for an element that starts with a pattern like "A10 - Fakultät für Mathematik und Informatik" and extract the faculty name from it.
            for path_element in module_data["path"]:
                match = re.match(r"^(?:A?)(\d{2}) - ", path_element)
                if match:
                    faculty_prefix = int(match.group(1)) # The prefix is the number before the " - "
                    faculty_name = path_element
                    break
        if faculty_name and faculty_prefix is not None:
            get_or_insert_faculty(session, faculty_name, faculty_prefix)

        semester_name = None
        semester_year = None
        semester_term = None
        if len(module_data["path"]) > 0:
            # We also try to extract the semester from the navigation path, looking for an element that starts with "SoSe" or "WiSe"
            for path_element in module_data["path"]:
                if path_element.startswith("SoSe") or path_element.startswith("WiSe"):
                    semester_name = path_element
                    if path_element.startswith("SoSe"):
                        semester_term = "SoSe"
                    elif path_element.startswith("WiSe"):
                        semester_term = "WiSe"
                    year_match = re.search(r"\d{2,4}", path_element)
                    if year_match:
                        semester_year = int(year_match.group(0))
                    break
        semester_id = None
        if semester_name and semester_year and semester_term:
            semester_id = _get_or_insert_semester(session, semester_name, semester_year, semester_term)

        # Get or insert the module, and get its ID for linking courses
        module_id, inserted = _get_or_insert_module(session, module_data)
        if inserted:
            inserted_count["modules"] += 1
        if semester_id is not None:
            _link_module_semester(session, module_id, semester_id)

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

        print(f"Finished inserting module {module_data['number']} - {module_data['name']}. Inserted {inserted_count['modules']} new modules, {inserted_count['courses']} new courses, and {inserted_count['events']} new events.")
        return inserted, inserted_count
