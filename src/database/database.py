import re
from collections import Counter
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends
from sqlmodel import Session, SQLModel, create_engine, select
from sqlalchemy import event, null, text

try:
    from parser.types import CourseType, EventType, ModuleType, RoomType, BuildingType, ExamType
except ModuleNotFoundError:
    from src.parser.types import CourseType, EventType, ModuleType, RoomType, BuildingType, ExamType

try:
    from parser.utils import _is_multidimensional, log_warning
except ModuleNotFoundError:
    from src.parser.utils import _is_multidimensional, log_warning  # type: ignore

try:
    from .model import (Course, Event, Module, Faculty, ModuleExam, ModuleAchievement, Location, Staff, Status, Semester, Building, Degree,
                        ModuleStaffLink, CourseStaffLink, EventStaffLink,
                        ModuleCourseLink, CourseEventLink, ModuleExamStaffLink, CourseSemesterLink, EventSemesterLink, ModuleSemesterLink, ModuleExamSemesterLink, ModuleStartSemesterLink, ModuleDegreeLink)
except ModuleNotFoundError:
    from src.database.model import (Course, Event, Module, Faculty, ModuleExam, ModuleAchievement, Location, Staff, Status, Semester, Building, Degree,
                                    ModuleStaffLink, CourseStaffLink, EventStaffLink,
                                    ModuleCourseLink, CourseEventLink, ModuleExamStaffLink, CourseSemesterLink, EventSemesterLink, ModuleSemesterLink, ModuleExamSemesterLink, ModuleStartSemesterLink, ModuleDegreeLink)
DATABASE_URL = "sqlite:///database.db"

# SQLite is accessed from FastAPI's synchronous thread pool, so connections are shared across
# threads. ``check_same_thread=False`` allows that; the generous ``timeout`` lets readers wait
# for a writer instead of immediately raising "database is locked". The pool is intentionally
# larger than the SQLAlchemy default (5 + 10 overflow) so a burst of concurrent requests does
# not exhaust it while a slow query is still running.
engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False, "timeout": 30},
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
)


@event.listens_for(engine, "connect")
def _configure_sqlite(dbapi_connection, connection_record):
    """
    Tune each new SQLite connection.

    WAL journaling lets reads proceed while the parser is writing, ``busy_timeout`` makes
    lock contention wait instead of erroring, and ``synchronous=NORMAL`` is the recommended
    durability level for WAL mode.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
    finally:
        cursor.close()


def create_db_and_tables():
    """
    Create all database tables defined in the SQLModel metadata, if they do not already exist.

    Also applies the lightweight ``degree`` column and index migrations so that databases
    created before those changes keep working (``create_all`` never alters existing tables).
    """
    SQLModel.metadata.create_all(engine)
    _migrate_degree_columns()
    _migrate_module_columns()
    _migrate_course_columns()
    _migrate_source_url_columns()
    _migrate_indexes()


def _migrate_degree_columns():
    """
    Add the structured degree columns to an existing ``degree`` table if they are missing.

    SQLModel.metadata.create_all() only creates missing tables; it never alters an existing one.
    Databases created before the path-parser integration therefore lack the new columns, so we
    add them here via SQLite ``ALTER TABLE ADD COLUMN``. New databases already have them.
    """
    new_columns = {
        "subject": "VARCHAR DEFAULT ''",
        "degree": "VARCHAR DEFAULT ''",
        "school_type": "VARCHAR DEFAULT ''",
        "ects": "INTEGER",
        "version": "VARCHAR DEFAULT ''",
        "confidence": "VARCHAR DEFAULT ''",
    }
    with engine.begin() as connection:
        existing = {row[1] for row in connection.execute(text("PRAGMA table_info(degree)"))}
        if not existing:
            return  # table does not exist yet; create_all() created it with all columns
        for name, ddl in new_columns.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE degree ADD COLUMN {name} {ddl}"))


def _add_columns_if_missing(table: str, new_columns: dict[str, str]) -> None:
    """Add ``new_columns`` (name -> SQLite type/default) to an existing table.

    ``SQLModel.metadata.create_all()`` never alters an existing table, so columns
    introduced after a database was created must be backfilled explicitly.
    """
    with engine.begin() as connection:
        existing = {row[1] for row in connection.execute(text(f"PRAGMA table_info({table})"))}
        if not existing:
            return  # table does not exist yet; create_all() created it with all columns
        for name, ddl in new_columns.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def _migrate_module_columns():
    """Backfill the module columns introduced with the parser fix (literature, elective fields, grading note)."""
    _add_columns_if_missing("module", {
        "literature": "VARCHAR DEFAULT ''",
        "elective_course_count": "INTEGER DEFAULT 0",
        "elective_prerequisites": "VARCHAR DEFAULT ''",
        "elective_classification": "VARCHAR DEFAULT ''",
        "grading_note": "VARCHAR DEFAULT ''",
    })


def _migrate_course_columns():
    """Backfill the course columns introduced with the parser fix (org unit, free-text sections)."""
    _add_columns_if_missing("course", {
        "org_unit": "VARCHAR DEFAULT ''",
        "official_description": "VARCHAR DEFAULT ''",
        "organisational": "VARCHAR DEFAULT ''",
        "literature": "VARCHAR DEFAULT ''",
    })


# Data tables that carry the ``url`` (source AlmaWeb page) column.
_SOURCE_URL_TABLES = (
    "module", "course", "event", "location", "building",
    "moduleexam", "moduleachievement",
)


def _migrate_source_url_columns():
    """Backfill the ``url`` (source page) column on every data table.

    The column is set by the parser so a stored record can be traced back to the
    exact AlmaWeb page it was parsed from.
    """
    for table in _SOURCE_URL_TABLES:
        _add_columns_if_missing(table, {"url": "VARCHAR DEFAULT ''"})


# Indexes introduced after the initial schema. ``SQLModel.metadata.create_all()`` only creates
# missing tables and never adds indexes to existing ones, so any missing index is created here
# explicitly. These keep the reverse (``b -> a``) lookups used by ``<Model>.any(...)`` filters
# and relationship loads from degrading into full table scans.
_PERFORMANCE_INDEXES: dict[str, list[str]] = {
    "modulestafflink": ["staff_id"],
    "modulesemesterlink": ["semester_id"],
    "modulestartsemesterlink": ["semester_id"],
    "modulecourselink": ["course_id"],
    "moduledegreelink": ["degree_id"],
    "courseeventlink": ["event_id"],
    "coursestafflink": ["staff_id"],
    "coursesemesterlink": ["semester_id"],
    "eventstafflink": ["staff_id"],
    "eventsemesterlink": ["semester_id"],
    "moduleexamstafflink": ["staff_id"],
    "moduleexamsemesterlink": ["semester_id"],
    "event": ["event_date", "location_id"],
    "moduleexam": ["module_id"],
    "moduleachievement": ["module_id"],
    "location": ["building_id"],
    "module": ["faculty_id"],
    "degree": ["faculty_id"],
}


def _migrate_indexes():
    """
    Create the performance indexes on an existing database if they are missing.

    New databases get them automatically from ``create_all()``; this only backfills databases
    that were created before the indexes were declared on the models.
    """
    with engine.begin() as connection:
        existing_tables = {
            row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        }
        for table, columns in _PERFORMANCE_INDEXES.items():
            if table not in existing_tables:
                continue
            existing_indexes = {
                row[1] for row in connection.execute(text(f"PRAGMA index_list({table})"))
            }
            for column in columns:
                index_name = f"ix_{table}_{column}"
                if index_name in existing_indexes:
                    continue
                connection.execute(
                    text(f'CREATE INDEX IF NOT EXISTS "{index_name}" ON "{table}" ("{column}")')
                )



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
        if not building.url and building_data.get("url"):
            building.url = building_data["url"]
            session.add(building)
        return building.id

    building = Building(
        name=building_data["name"],
        short_name=building_data["short_name"],
        address=building_data["address"],
        url=building_data.get("url", ""),
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
        if not location.url and room_data.get("url"):
            location.url = room_data["url"]
            session.add(location)
        return location.id

    location = Location(
        name=room_data["name"],
        external_id=room_data["external_id"],
        description=room_data.get("description", ""),
        type=room_data.get("type", ""),
        seats=room_data.get("seats"),
        size=room_data.get("size"),
        accessibility=room_data.get("accessibility", ""),
        building_id=building_id,
        url=room_data.get("url", ""),
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

def _get_or_insert_degree(session: Session, degree_data: dict) -> int:
    """
    Look up a degree by its harmonized name and faculty. If it does not exist, insert it.

    ``degree_data`` carries the structured fields produced by the path-parser
    (``name``, ``subject``, ``degree``, ``school_type``, ``ects``, ``version``, ``confidence``,
    ``faculty_id``). Returns the degree ID.
    """
    name = degree_data.get("name") or ""
    faculty_id = degree_data.get("faculty_id")
    degree = session.exec(
        select(Degree)
        .where(Degree.name == name)
        .where(Degree.faculty_id == faculty_id)
    ).first()
    if degree is not None:
        if degree.id is None:
            raise RuntimeError("Degree to add to database has no id")
        return degree.id

    degree = Degree(
        name=name,
        subject=degree_data.get("subject") or "",
        degree=degree_data.get("degree") or "",
        school_type=degree_data.get("school_type") or "",
        ects=degree_data.get("ects"),
        version=degree_data.get("version") or "",
        confidence=degree_data.get("confidence") or "",
        faculty_id=faculty_id,
    )  # type: ignore
    session.add(degree)
    session.flush()
    if degree.id is None:
        raise RuntimeError("Could not get degree id after add and flush to database")
    return degree.id

def _link_module_degree(session: Session, module_id: int, degree_id: int):
    """
    Create a link between a module and a degree in the ModuleDegreeLink association table, if it does not already exist.
    """
    link = session.exec(
        select(ModuleDegreeLink)
        .where(ModuleDegreeLink.module_id == module_id)
        .where(ModuleDegreeLink.degree_id == degree_id)
    ).first()
    if link is not None:
        return
    session.add(ModuleDegreeLink(module_id=module_id, degree_id=degree_id))
    session.flush()

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

def _normalise_path_groups(path) -> list[list[str]]:
    """Normalise a module path (flat ``list[str]`` or ``list[list[str]]``) to ``list[list[str]]``."""
    if not path:
        return []
    if any(isinstance(node, list) for node in path):
        return [[str(node) for node in group] for group in path if group]
    return [[str(node) for node in path]]


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
        # Normalise both the incoming and the stored path to list[list[str]].
        new_paths = _normalise_path_groups(module_data["path"])
        existing_normalised = _normalise_path_groups(module.path)

        # Reassign instead of mutating in place: SQLAlchemy does not track in-place
        # mutations of a Column(JSON), so an append would silently never persist.
        merged = [list(group) for group in existing_normalised]
        for new_path in new_paths:
            if new_path not in merged:
                merged.append(list(new_path))
        module.path = merged

        # Backfill scalar fields that are still empty (a later page may carry a
        # value an earlier one lacked). Never overwrite a non-empty value.
        for field, value in (
            ("frequency", module_data.get("frequency", "")),
            ("goals", module_data.get("goals", "")),
            ("content", module_data.get("content", "")),
            ("exam_prerequisites", module_data.get("exam_prerequisites", "")),
            ("literature", module_data.get("literature", "")),
            ("elective_prerequisites", module_data.get("elective_prerequisites", "")),
            ("elective_classification", module_data.get("elective_classification", "")),
            ("grading_note", module_data.get("grading_note", "")),
        ):
            if value and not getattr(module, field):
                setattr(module, field, value)
        if module_data.get("credits") and not module.credits:
            module.credits = module_data["credits"]
        if module_data.get("duration_semesters") and not module.duration_semesters:
            module.duration_semesters = module_data["duration_semesters"]
        if module_data.get("elective_course_count") and not module.elective_course_count:
            module.elective_course_count = module_data["elective_course_count"]
        if module_data.get("prerequisites") and not module.prerequisites:
            module.prerequisites = module_data["prerequisites"]
        if not module.url and module_data.get("url"):
            module.url = module_data["url"]
        session.add(module)
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
        # ``language`` is derived from the module's courses after insertion; it is
        # not present in the module page data.
        language=module_data.get("language", ""),
        duration_semesters=module_data.get("duration_semesters", 0),
        credits=module_data.get("credits", 0),
        frequency=module_data.get("frequency", ""),
        goals=module_data.get("goals", ""),
        content=module_data.get("content", ""),
        exam_prerequisites=module_data.get("exam_prerequisites", ""),
        prerequisites=module_data.get("prerequisites", {}),
        literature=module_data.get("literature", ""),
        elective_course_count=module_data.get("elective_course_count", 0),
        elective_prerequisites=module_data.get("elective_prerequisites", ""),
        elective_classification=module_data.get("elective_classification", ""),
        grading_note=module_data.get("grading_note", ""),
        path=_normalise_path_groups(module_data.get("path", [])),
        faculty_id=faculty_id,
        url=module_data.get("url", ""),
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
        # Link any staff this occurrence carries that earlier ones did not. The old
        # code returned early and silently dropped them.
        for staff_name in course_data.get("staff", []):
            if staff_name:
                staff_id = _get_or_insert_staff(session, staff_name)
                _link_course_staff(session, course.id, staff_id)
        # Backfill scalar fields that are still empty. Never overwrite a value.
        for field, value in (
            ("language", course_data.get("language", "")),
            ("org_unit", course_data.get("org_unit", "")),
            ("official_description", course_data.get("official_description", "")),
            ("organisational", course_data.get("organisational", "")),
            ("literature", course_data.get("literature", "")),
        ):
            if value and not getattr(course, field):
                setattr(course, field, value)
        if course_data.get("weekly_hours") and not course.weekly_hours:
            course.weekly_hours = course_data["weekly_hours"]
        if not course.url and course_data.get("url"):
            course.url = course_data["url"]
        session.add(course)
        return course.id, False

    # Unpacking of course_data into Course constructor, excluding "events" key for separate handling, because "events" is not a field of Course
    course = Course(
        name=course_data["name"],
        number=course_data["number"],
        type=_get_or_insert_event_type(session, course_data["type"]),
        weekly_hours=course_data.get("weekly_hours", 0),
        language=course_data.get("language", ""),
        status=_get_or_insert_status(session, course_data.get("status", "")),
        org_unit=course_data.get("org_unit", ""),
        official_description=course_data.get("official_description", ""),
        organisational=course_data.get("organisational", ""),
        literature=course_data.get("literature", ""),
        url=course_data.get("url", ""),
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
        if not exam.url and exam_data.get("url"):
            exam.url = exam_data["url"]
            session.add(exam)
        return exam.id, False

    # Unpacking of exam_data into ModuleExam constructor
    exam = ModuleExam(
        module_id=module_id,
        name=exam_data["name"],
        start_time=exam_data["start_time"],
        end_time=exam_data["end_time"],
        exam_date=exam_data["date"],
        required=exam_data["required"],
        url=exam_data.get("url", ""),
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

def _insert_achievement_if_new(session: Session, module_id: int, achievement_data) -> tuple[int, bool]:
    """Insert a module achievement ("Leistungen" row) if an identical one does not exist."""
    if achievement_data.get("weight") is None:
        weight_condition = ModuleAchievement.weight == null()
    else:
        weight_condition = ModuleAchievement.weight == achievement_data["weight"]

    achievement = session.exec(
        select(ModuleAchievement)
        .where(ModuleAchievement.module_id == module_id)
        .where(ModuleAchievement.name == achievement_data["name"])
        .where(ModuleAchievement.required == achievement_data["required"])
        .where(weight_condition)
    ).first()

    if achievement is not None:
        if achievement.id is None:
            raise RuntimeError("Achievement to add to database has no id")
        if not achievement.url and achievement_data.get("url"):
            achievement.url = achievement_data["url"]
            session.add(achievement)
        return achievement.id, False

    achievement = ModuleAchievement(
        module_id=module_id,
        name=achievement_data["name"],
        required=achievement_data["required"],
        weight=achievement_data["weight"],
        combination=achievement_data.get("combination", ""),
        url=achievement_data.get("url", ""),
    )  # type: ignore
    session.add(achievement)
    session.flush()
    if achievement.id is None:
        raise RuntimeError("Could not get achievement id after add and flush to database")
    return achievement.id, True


def _set_course_weekday(session: Session, course_id: int, weekday: int) -> None:
    """Set ``Course.weekday`` if it is not set yet (derived; see the model note)."""
    course = session.get(Course, course_id)
    if course is not None and course.weekday is None:
        course.weekday = weekday
        session.add(course)


def _set_module_language(session: Session, module_id: int, language: str) -> None:
    """Set ``Module.language`` if it is not set yet (derived; see the model note)."""
    module = session.get(Module, module_id)
    if module is not None and not module.language:
        module.language = language
        session.add(module)


def _insert_event_if_new(session: Session, event_data: EventType, course_id: int) -> tuple[int, bool]:
    """
    Insert a course event if no identical record already exists.

    Two sessions are only treated as one physical event when they share the same
    room, date and time slot. When the room is **unknown** the dedup is scoped to
    ``course_id``: without a room a shared slot is not evidence of a shared
    session, and merging there used to fuse unrelated courses into one event.
    If a matching event is found, any staff from event_data not yet linked to it
    are added.

    Returns True if a new event was inserted, False if an existing one was reused.
    """

    # Resolve the location first so it can be used in the dedup query
    location_id = None
    if event_data["location"] is not None:
        location_id = _get_or_insert_location(session, event_data["location"])

    # The per-course sequential number is intentionally excluded: it is not a global identifier.
    query = (
        select(Event)
        .where(Event.event_date == event_data["event_date"])
        .where(Event.start_time == event_data["start_time"])
        .where(Event.end_time == event_data["end_time"])
        .where(Event.location_id == location_id)
    )
    if location_id is None:
        # No room: only reuse an event already linked to this same course.
        query = query.where(
            Event.id.in_(
                select(CourseEventLink.event_id).where(CourseEventLink.course_id == course_id)
            )
        )

    event = session.exec(query).first()

    if event is not None:
        if event.id is None:
            raise RuntimeError("Event to add to database has no id")
        # Merge staff: add any staff from this event_data not yet linked to the existing event
        for staff_name in event_data.get("staff", []):
            staff_id = _get_or_insert_staff(session, staff_name)
            _link_event_staff(session, event.id, staff_id)
        if not event.url and event_data.get("url"):
            event.url = event_data["url"]
            session.add(event)
        return event.id, False

    # Unpacking of event_data into CourseEvent constructor, adding course_id for the foreign key relationship
    event = Event(
        number=event_data["number"],
        name=event_data.get("name", ""),
        start_time=event_data["start_time"],
        end_time=event_data["end_time"],
        event_date=event_data["event_date"],
        location_id=location_id,
        url=event_data.get("url", ""),
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

        # Collect every semester referenced by the module's navigation paths. A
        # module offered in several semesters must be linked to all of them; the
        # old code linked only the first one it found.
        semester_ids: list[int] = []
        semester_id = None
        for path_group in _normalise_path_groups(module_data["path"]):
            for path_element in path_group:
                if not (path_element.startswith("SoSe") or path_element.startswith("WiSe")):
                    continue
                term = "SoSe" if path_element.startswith("SoSe") else "WiSe"
                year_match = re.search(r"\d{2,4}", path_element)
                if not year_match:
                    continue
                sem_id = _get_or_insert_semester(session, path_element, int(year_match.group(0)), term)
                if sem_id not in semester_ids:
                    semester_ids.append(sem_id)
                if semester_id is None:
                    semester_id = sem_id

        # Get or insert the module, and get its ID for linking courses
        module_id, inserted = _get_or_insert_module(session, module_data)
        if inserted:
            inserted_count["modules"] += 1
        for sem_id in semester_ids:
            _link_module_semester(session, module_id, sem_id)
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

        # Module achievements ("Leistungen" table): weighting, combination, etc.
        for achievement_data in module_data.get("achievements", []):
            _insert_achievement_if_new(session, module_id, achievement_data)

        course_languages: list[str] = []
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
            if course_data.get("language"):
                course_languages.append(course_data["language"])

            event_weekdays: list[int] = []
            for event_data in course_data["events"]:
                if event_data is None:
                    continue
                # Insert each event if it does not already exist. The course id scopes
                # the dedup for sessions without a known room.
                event_id, event_inserted = _insert_event_if_new(session, event_data, course_id)
                _link_course_event(session, course_id, event_id)
                if semester_id is not None:
                    _link_event_semester(session, event_id, semester_id)
                if event_inserted:
                    inserted_count["events"] += 1
                inserted = inserted or event_inserted
                if event_data.get("event_date") is not None:
                    event_weekdays.append(event_data["event_date"].isoweekday())

            # Course.weekday is derived from its events (deprecated as a stored column).
            if event_weekdays:
                _set_course_weekday(session, course_id, Counter(event_weekdays).most_common(1)[0][0])

        # Module.language is derived from its courses (deprecated as a stored column).
        if course_languages:
            _set_module_language(session, module_id, Counter(course_languages).most_common(1)[0][0])

        # Commit all changes to the database at once after processing the entire module graph
        # This doesn't insert any record if any error occurs during the process, so all relationships are guaranteed to be consistent
        session.commit()

        print(f"Finished inserting module {module_data['number']} - {module_data['name']}. Inserted {inserted_count['modules']} new modules, {inserted_count['courses']} new courses, and {inserted_count['events']} new events.")
        return inserted, inserted_count
