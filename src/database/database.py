import re
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends
from sqlmodel import Session, SQLModel, create_engine, select
from sqlalchemy import null

try:
    from parser.types import CourseType, EventType, ModuleType, RoomType, BuildingType, ExamType
except ModuleNotFoundError:
    from src.parser.types import CourseType, EventType, ModuleType, RoomType, BuildingType, ExamType

try:
    from parser.utils import _is_multidimensional
except ModuleNotFoundError:
    from src.parser.utils import _is_multidimensional

try:
    from .model import (Course, Event, Module, Faculty, ModuleExam, Location, Staff, Status, Semester, Building, 
                        ModuleStaffLink, CourseStaffLink, EventStaffLink,
                        ModuleCourseLink, CourseEventLink, ModuleExamStaffLink, CourseSemesterLink, EventSemesterLink, ModuleSemesterLink, ModuleExamSemesterLink, ModuleStartSemesterLink)
except ModuleNotFoundError:
    from src.database.model import (Course, Event, Module, Faculty, ModuleExam, Location, Staff, Status, Semester, Building, 
                                    ModuleStaffLink, CourseStaffLink, EventStaffLink,
                                    ModuleCourseLink, CourseEventLink, ModuleExamStaffLink, CourseSemesterLink, EventSemesterLink, ModuleSemesterLink, ModuleExamSemesterLink, ModuleStartSemesterLink)
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

def _get_or_insert_status(session: Session, name: str) -> int:
    """
    Look up a course status by name. If it does not exist, insert it.

    Returns the course status ID.
    """
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
    Look up a location (room) by its external ID, name, and building ID. If it does not exist, insert it.

    Returns the location ID.
    """    
    building_id = _get_or_insert_building(session, room_data["building"])

    location = session.exec(
        select(Location)
        .where(Location.name == room_data["name"])
        .where(Location.external_id == room_data["external_id"])
        .where(Location.building_id == building_id)
    ).first()
    if location is not None:
        if location.id is None:
            raise RuntimeError("Location to add to database has no id")
        return location.id

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
    link = session.exec(
        select(ModuleSemesterLink)
        .where(ModuleSemesterLink.module_id == module_id)
        .where(ModuleSemesterLink.semester_id == semester_id)
    ).first()

    if link is None:
        session.add(ModuleSemesterLink(module_id=module_id, semester_id=semester_id))

def _link_module_start_semester(session: Session, module_id: int, semester_id: int):
    """
    Create a link between a module and its starting semester in the ModuleStartSemesterLink association table, if it does not already exist.
    """
    link = session.exec(
        select(ModuleStartSemesterLink)
        .where(ModuleStartSemesterLink.module_id == module_id)
        .where(ModuleStartSemesterLink.semester_id == semester_id)
    ).first()

    if link is None:
        session.add(ModuleStartSemesterLink(module_id=module_id, semester_id=semester_id))

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

def _link_course_semester(session: Session, course_id: int, semester_id: int):
    """
    Create a link between a course and a semester in the CourseSemesterLink association table, if it does not already exist.
    """
    link = session.exec(
        select(CourseSemesterLink)
        .where(CourseSemesterLink.course_id == course_id)
        .where(CourseSemesterLink.semester_id == semester_id)
    ).first()

    if link is None:
        session.add(CourseSemesterLink(course_id=course_id, semester_id=semester_id))

def _link_module_responsible_person(session: Session, module_id: int, staff_id: int):
    """
    Create a link between a module and its responsible person in the ModuleStaffLink association table, if it does not already exist.
    """
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
    link = session.exec(
        select(EventStaffLink)
        .where(EventStaffLink.event_id == event_id)
        .where(EventStaffLink.staff_id == staff_id)
    ).first()

    if link is None:
        session.add(EventStaffLink(event_id=event_id, staff_id=staff_id))

def _link_event_semester(session: Session, event_id: int, semester_id: int):
    """
    Create a link between an event and a semester in the EventSemesterLink association table, if it does not already exist.
    """
    link = session.exec(
        select(EventSemesterLink)
        .where(EventSemesterLink.event_id == event_id)
        .where(EventSemesterLink.semester_id == semester_id)
    ).first()

    if link is None:
        session.add(EventSemesterLink(event_id=event_id, semester_id=semester_id))

def _link_module_exam_staff(session: Session, exam_id: int, staff_id: int):
    """
    Create a link between a module exam and a staff member in the ModuleExamStaffLink association table, if it does not already exist.
    """
    link = session.exec(
        select(ModuleExamStaffLink)
        .where(ModuleExamStaffLink.module_exam_id == exam_id)
        .where(ModuleExamStaffLink.staff_id == staff_id)
    ).first()

    if link is None:
        session.add(ModuleExamStaffLink(module_exam_id=exam_id, staff_id=staff_id))

def _link_module_exam_semester(session: Session, exam_id: int, semester_id: int):
    """
    Create a link between a module exam and a semester in the ModuleExamSemesterLink association table, if it does not already exist.
    """
    link = session.exec(
        select(ModuleExamSemesterLink)
        .where(ModuleExamSemesterLink.module_exam_id == exam_id)
        .where(ModuleExamSemesterLink.semester_id == semester_id)
    ).first()

    if link is None:
        session.add(ModuleExamSemesterLink(module_exam_id=exam_id, semester_id=semester_id))

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
    # Link module responsible persons to the module, inserting them if they do not already exist.
    # The raw field may contain multiple names separated by ";" or ",".
    for responsible_person_name in re.split(r"[;,]", module_data.get("responsible_person", "")):
        responsible_person_name = responsible_person_name.strip()
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

def _insert_exam_if_new(session: Session, module_id: int, exam_data: ExamType) -> tuple[int, bool]:
    """
    Insert an exam if no identical record (same date, time slot, and name) already exists.
    If a matching exam is found, any staff from exam_data not yet linked to it are added.

    Returns True if a new exam was inserted, False if an existing one was reused.
    """

    # Two exams are the same physical session when they share the same name, date, and time slot.
    if exam_data["date"] is None:
        date_condition = ModuleExam.exam_date == null()
    else:
        date_condition = ModuleExam.exam_date == exam_data["date"]
    
    exam = session.exec(
        select(ModuleExam)
        .where(ModuleExam.module_id == module_id)
        .where(ModuleExam.name == exam_data["name"])
        .where(ModuleExam.required == exam_data["required"])
        .where(date_condition)
    ).first()

    if exam is not None:
        if exam.id is None:
            raise RuntimeError("Exam to add to database has no id")
        # Merge staff: add any staff from this exam_data not yet linked to the existing exam
        for staff_name in exam_data.get("staff", []):
            staff_id = _get_or_insert_staff(session, staff_name)
            _link_module_exam_staff(session, exam.id, staff_id)
        return exam.id, False

    # Unpacking of exam_data into ModuleExam constructor
    exam = ModuleExam(
        module_id=module_id,
        name=exam_data["name"],
        start_time=exam_data["start_time"],
        end_time=exam_data["end_time"],
        exam_date=exam_data["date"],
        required=exam_data["required"]
    )  # type: ignore
    session.add(exam)
    session.flush()
    if exam.id is None:
        raise RuntimeError("Could not get exam id after add and flush to database")

    # Link staff members to the exam, inserting them if they do not already exist
    for staff_name in exam_data.get("staff", []):
        staff_id = _get_or_insert_staff(session, staff_name)
        _link_module_exam_staff(session, exam.id, staff_id)

    return exam.id, True

def _insert_event_if_new(session: Session, event_data: EventType) -> tuple[int, bool]:
    """
    Insert a course event if no identical record (same date, time slot, and location) already exists.
    If a matching event is found, any staff from event_data not yet linked to it are added.

    Returns True if a new event was inserted, False if an existing one was reused.
    """

    # Resolve the location first so it can be used in the dedup query
    location_id = None
    if event_data["location"] is not None:
        location_id = _get_or_insert_location(session, event_data["location"])

    # Two events are the same physical session when they share the same room, date, and time slot.
    # The per-course sequential number is intentionally excluded: it is not a global identifier.
    event = session.exec(
        select(Event)
        .where(Event.event_date == event_data["event_date"])
        .where(Event.start_time == event_data["start_time"])
        .where(Event.end_time == event_data["end_time"])
        .where(Event.location_id == location_id)
    ).first()

    if event is not None:
        if event.id is None:
            raise RuntimeError("Event to add to database has no id")
        # Merge staff: add any staff from this event_data not yet linked to the existing event
        for staff_name in event_data.get("staff", []):
            staff_id = _get_or_insert_staff(session, staff_name)
            _link_event_staff(session, event.id, staff_id)
        return event.id, False

    # Unpacking of event_data into CourseEvent constructor, adding course_id for the foreign key relationship
    event = Event(
        number=event_data["number"],
        name=event_data.get("name", ""),
        start_time=event_data["start_time"],
        end_time=event_data["end_time"],
        event_date=event_data["event_date"],
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
        faculty_name: str | None = None
        faculty_prefix: int | None = None
        if len(module_data["path"]) > 0:
            # Fakultät started mit "(A)[0-9][0-9] - ...", z.B. "A10 - Fakultät für Mathematik und Informatik" or "A07 - Wirtschaftswissenschaftliche Fakultät"
            # We extract the faculty name from the navigation path, which is needed for the foreign key relationship. If no faculty can be identified, we leave it null.
            # The faculty name is usually the third element in the path, but we check all elements to be safe, because the structure is not perfectly consistent. We look for an element that starts with a pattern like "A10 - Fakultät für Mathematik und Informatik" and extract the faculty name from it.
            path_obj: list[list[str]] = []
            if _is_multidimensional(module_data["path"]):
                path_obj = module_data["path"] # type: ignore
            else:
                path_obj = [module_data["path"]] # type: ignore
            for path_group in path_obj:
                for path_element in path_group:
                    match = re.match(r"^(?:A?)(\d{2}) - ", path_element)
                    if match:
                        faculty_prefix = int(match.group(1)) # The prefix is the number before the " - "
                        # check that the faculty prefix is the same as the module number prefix, if the module number has a prefix
                        module_number_prefix_match = re.match(r"^A?(\d{2})", module_data["number"])
                        if module_number_prefix_match:
                            module_number_prefix = int(module_number_prefix_match.group(1))
                            if faculty_prefix != module_number_prefix:
                                continue # Skip this path element if the faculty prefix does not match the module number prefix
                        faculty_name = path_element
                        break
                if faculty_name:
                    break
        if faculty_name and faculty_prefix is not None:
            get_or_insert_faculty(session, faculty_name, faculty_prefix)

        semester_name = None
        semester_year = None
        semester_term = None
        if len(module_data["path"]) > 0:
            # We also try to extract the semester from the navigation path, looking for an element that starts with "SoSe" or "WiSe"
            path_obj: list[list[str]] = []
            if _is_multidimensional(module_data["path"]):
                path_obj = module_data["path"] # type: ignore
            else:
                path_obj = [module_data["path"]] # type: ignore
            
            for path_group in path_obj:
                for path_element in path_group:
                    if path_element.startswith("SoSe") or path_element.startswith("WiSe"):
                        if semester_name is not None and semester_name != path_element:
                            print(f"Warning: Multiple semester names found in module path for module {module_data['number']}: {semester_name} and {path_element}. Using the first one.")
                            print(f"Module path: {module_data['path']}")
                            break
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
        if module_data.get("start_semester"):
            start_semester_name = module_data["start_semester"]
            start_semester_year = None
            start_semester_term = None
            if start_semester_name.startswith("SoSe"):
                start_semester_term = "SoSe"
            elif start_semester_name.startswith("WiSe"):
                start_semester_term = "WiSe"
            year_match = re.search(r"\d{2,4}", start_semester_name)
            if year_match:
                start_semester_year = int(year_match.group(0))
            if start_semester_year and start_semester_term:
                start_semester_id = _get_or_insert_semester(session, start_semester_name, start_semester_year, start_semester_term)
                _link_module_start_semester(session, module_id, start_semester_id)
        for exam_data in module_data["exams"]:
            # Insert each exam if it does not already exist.
            exam_id, exam_inserted = _insert_exam_if_new(session, module_id, exam_data)
            if exam_inserted:
                inserted_count["events"] += 1
            inserted = inserted or exam_inserted
            if semester_id is not None:
                _link_module_exam_semester(session, exam_id, semester_id)

        for course_data in module_data["courses"]:
            # Get or insert each course, and get its corresponding ID for linking the events
            if course_data is None:
                continue
            course_id, course_inserted = _get_or_insert_course(session, course_data)
            _link_module_course(session, module_id, course_id)
            if semester_id is not None:
                _link_course_semester(session, course_id, semester_id)
            if course_inserted:
                inserted_count["courses"] += 1
            inserted = inserted or course_inserted

            for event_data in course_data["events"]:
                if event_data is None:
                    continue
                # Insert each event if it does not already exist.
                event_id, event_inserted = _insert_event_if_new(session, event_data)
                _link_course_event(session, course_id, event_id)
                if semester_id is not None:
                    _link_event_semester(session, event_id, semester_id)
                if event_inserted:
                    inserted_count["events"] += 1
                inserted = inserted or event_inserted

        # Commit all changes to the database at once after processing the entire module graph
        # This doesn't insert any record if any error occurs during the process, so all relationships are guaranteed to be consistent
        session.commit()

        print(f"Finished inserting module {module_data['number']} - {module_data['name']}. Inserted {inserted_count['modules']} new modules, {inserted_count['courses']} new courses, and {inserted_count['events']} new events.")
        return inserted, inserted_count
