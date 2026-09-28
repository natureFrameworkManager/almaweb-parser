from datetime import datetime, time, date, timezone

from sqlalchemy import Column, JSON
from sqlmodel import Field, Relationship, SQLModel

# NOTE on association-table indexes:
# Every link table below uses a composite primary key ``(a_id, b_id)`` which SQLite backs
# with an automatic index whose leading column is ``a_id``. Reverse lookups – i.e. the
# ``b -> a`` direction used by ``<Model>.any(...)`` filters and relationship loads – cannot
# use that autoindex and previously fell back to a full table scan. Combined with a
# correlated ``EXISTS`` that is evaluated once per outer row this produced O(N*M) plans and
# request timeouts (see ``ix_courseeventlink_event_id``). The second column of each link
# table therefore carries an explicit ``index=True``.
class ModuleStaffLink(SQLModel, table=True):
    """
    Association table for the many-to-many relationship between Module and Staff.
    """

    module_id: int = Field(foreign_key="module.id", primary_key=True)
    staff_id: int = Field(foreign_key="staff.id", primary_key=True, index=True)

class ModuleSemesterLink(SQLModel, table=True):
    """
    Association table for the many-to-many relationship between Module and Semesters.
    """

    module_id: int = Field(foreign_key="module.id", primary_key=True)
    semester_id: int = Field(foreign_key="semester.id", primary_key=True, index=True)

class ModuleStartSemesterLink(SQLModel, table=True):
    """
    Association table for the many-to-many relationship between Module and the starting Semester.
    """

    module_id: int = Field(foreign_key="module.id", primary_key=True)
    semester_id: int = Field(foreign_key="semester.id", primary_key=True, index=True)

class ModuleCourseLink(SQLModel, table=True):
    """
    Association table for the many-to-many relationship between Module and Course.
    """

    module_id: int = Field(foreign_key="module.id", primary_key=True)
    course_id: int = Field(foreign_key="course.id", primary_key=True, index=True)

class ModuleDegreeLink(SQLModel, table=True):
    """
    Association table for the many-to-many relationship between Module and Degree.
    """

    module_id: int = Field(foreign_key="module.id", primary_key=True)
    degree_id: int = Field(foreign_key="degree.id", primary_key=True, index=True)

class CourseEventLink(SQLModel, table=True):
    """
    Association table for the many-to-many relationship between Course and Event.
    """

    course_id: int = Field(foreign_key="course.id", primary_key=True)
    event_id: int = Field(foreign_key="event.id", primary_key=True, index=True)

class CourseStaffLink(SQLModel, table=True):
    """
    Association table for the many-to-many relationship between Course and Staff.
    """

    course_id: int = Field(foreign_key="course.id", primary_key=True)
    staff_id: int = Field(foreign_key="staff.id", primary_key=True, index=True)

class CourseSemesterLink(SQLModel, table=True):
    """
    Association table for the many-to-many relationship between Course and Semester.
    """

    course_id: int = Field(foreign_key="course.id", primary_key=True)
    semester_id: int = Field(foreign_key="semester.id", primary_key=True, index=True)

class EventStaffLink(SQLModel, table=True):
    """
    Association table for the many-to-many relationship between Event and Staff.
    """

    event_id: int = Field(foreign_key="event.id", primary_key=True)
    staff_id: int = Field(foreign_key="staff.id", primary_key=True, index=True)

class EventSemesterLink(SQLModel, table=True):
    """
    Association table for the many-to-many relationship between Event and Semester.
    """

    event_id: int = Field(foreign_key="event.id", primary_key=True)
    semester_id: int = Field(foreign_key="semester.id", primary_key=True, index=True)

class ModuleExamStaffLink(SQLModel, table=True):
    """
    Association table for the many-to-many relationship between ModuleExam and Staff.
    """

    module_exam_id: int = Field(foreign_key="moduleexam.id", primary_key=True)
    staff_id: int = Field(foreign_key="staff.id", primary_key=True, index=True)

class ModuleExamSemesterLink(SQLModel, table=True):
    """
    Association table for the many-to-many relationship between ModuleExam and Semester.
    """

    module_exam_id: int = Field(foreign_key="moduleexam.id", primary_key=True)
    semester_id: int = Field(foreign_key="semester.id", primary_key=True, index=True)

class Module(SQLModel, table=True):
    """
    A university module (Lehrveranstaltung) as listed in AlmaWeb.

    One module groups one or more :class:`Course` (event type) instances and carries the authoritative academic metadata such as credits, prerequisites, and the curriculum path.
    """

    id: int | None = Field(default=None, primary_key=True) # Primary key, auto-incremented by the database
    name: str
    number: str = Field(index=True)
    language: str = ""
    duration_semesters: int = 0
    credits: float = 0.0
    frequency: str = ""
    goals: str = ""
    content: str = ""
    exam_prerequisites: str = ""
    prerequisites: dict[str, str] = Field(sa_column=Column(JSON))
    faculty_id: int | None = Field(foreign_key="faculty.id", index=True) # The faculty to which the module belongs, if known

    faculty: "Faculty" = Relationship(back_populates="modules")
    path: list[str] | list[list[str]] = Field(sa_column=Column(JSON)) # The path in the original navigation structure, e.g. ["Root","Informatik","Informatik (Bachelor of Science)","Pflichtmodule (empfohlen für das 6. Fachsemester)"]
    responsible_persons: list["Staff"] = Relationship(back_populates="modules", link_model=ModuleStaffLink)
    start_semester: list["Semester"] = Relationship(back_populates="modules", link_model=ModuleStartSemesterLink)
    semesters: list["Semester"] = Relationship(back_populates="modules", link_model=ModuleSemesterLink)
    degrees: list["Degree"] = Relationship(back_populates="modules", link_model=ModuleDegreeLink)
    courses: list["Course"] = Relationship(back_populates="modules", link_model=ModuleCourseLink)
    exams: list["ModuleExam"] = Relationship(back_populates="module")

class Course(SQLModel, table=True):
    """
    A single course within a :class:`Module`.  
    It is more similar to a single event type or group of module with contains multiple scheduled occurrences, e.g. a lecture with multiple weekly sessions.

    A course is the schedulable unit: it has a type, a weekly hour count, a language, and zero or more concrete :class:`CourseEvent` occurrences.
    """

    id: int | None = Field(default=None, primary_key=True)
    name: str = ""
    number: str = ""
    type: int = Field(foreign_key="eventtype.id")
    weekday: int | None = None # 1=Monday, 2=Tuesday, ..., 7=Sunday. This is not always available in the source data, so it can be None.
    weekly_hours: int = 0
    language: str = ""
    status: int = Field(foreign_key="status.id")

    staff: list["Staff"] = Relationship(back_populates="courses", link_model=CourseStaffLink)
    semesters: list["Semester"] = Relationship(back_populates="courses", link_model=CourseSemesterLink)
    modules: list["Module"] = Relationship(back_populates="courses", link_model=ModuleCourseLink)
    events: list["Event"] = Relationship(back_populates="courses", link_model=CourseEventLink)


class Event(SQLModel, table=True):
    """
    A single scheduled occurrence of a :class:`Course`.

    Each event represents one entry in the timetable: a specific date, time slot, room, and set of staff members.
    """

    id: int | None = Field(default=None, primary_key=True)
    number: str = ""
    name: str = ""
    start_time: time
    end_time: time
    event_date: date = Field(index=True) # Indexed: date-range filters (/schedule/daily|weekly|monthly, /events) scan this column
    location_id: int | None = Field(foreign_key="location.id", index=True) # TODO: Remove None

    location: "Location" = Relationship(back_populates="events")
    staff: list["Staff"] = Relationship(back_populates="events", link_model=EventStaffLink)
    semesters: list["Semester"] = Relationship(back_populates="events", link_model=EventSemesterLink)
    courses: list["Course"] = Relationship(back_populates="events", link_model=CourseEventLink)

class Location(SQLModel, table=True):
    """
    A location (room) where events take place.
    """

    id: int | None = Field(default=None, primary_key=True)
    name: str = ""
    external_id: str = "" # The original room identifier as used in the source data, e.g. "Hörsaal 1" or "Online"
    description: str = "" # Additional information about the location, e.g. "Hörsaal 1 im Hauptgebäude" or "Online-Veranstaltung über Zoom"
    type: str = "" # The type of location, e.g. "Hörsaal", "Seminarraum", "Online", etc.
    seats: int | None = None # The number of seats available in the location, if known
    size: float | None = None # The size of the location in square meters, if known
    accessibility: str = "" # Information about the accessibility of the location, e.g. "barrierefrei", "nicht barrierefrei", etc.
    building_id: int | None = Field(foreign_key="building.id", index=True) # The building where the location is situated, if known

    building: "Building" = Relationship(back_populates="locations")
    events: list["Event"] = Relationship(back_populates="location")

class Building(SQLModel, table=True):
    """
    A building where locations (rooms) are situated.
    """

    id: int | None = Field(default=None, primary_key=True)
    name: str = ""
    short_name: str = "" # A short name or code for the building, e.g. "Hauptgebäude", "Informatik-Gebäude", etc.
    address: str = "" # The address of the building, e.g. "Musterstraße 1, 12345 Musterstadt"

    locations: list["Location"] = Relationship(back_populates="building")

class Degree(SQLModel, table=True):
    """
    A degree program, e.g. "Informatik (Bachelor of Science)", "Informatik (Master of Science)", etc.

    The ``name`` is the harmonized display name produced by the path-parser
    (``subject (degree, school_type, ects LP, version)``) and acts as the dedup identity
    together with ``faculty_id``. The remaining columns preserve the structured fields the
    extractor derived from the navigation path.
    """

    id: int | None = Field(default=None, primary_key=True)
    name: str = ""
    subject: str = "" # The subject/program name without degree, school type, version or ECTS
    degree: str = "" # "B.A.", "B.Sc.", "M.A.", "M.Sc.", "Bachelor", "Master", "Lehramt", "Staatsexamen", "Diplom", "Wahlfach"
    school_type: str = "" # Only for teaching degrees: "Grundschule", "Oberschule", "Gymnasium", "Sonderpädagogik", "Berufsbildende Schulen"
    ects: int | None = None # ECTS from the name, e.g. 60 for "Wahlfach 60 LP"
    version: str = "" # Prüfungsordnung / Immatrikulationsangabe, e.g. "PO 2017", "ab WiSe 2024/25"
    confidence: str = "" # Extractor confidence: "high", "medium", "low", "none"
    faculty_id: int | None = Field(foreign_key="faculty.id", index=True) # The faculty to which the degree program belongs, if known

    faculty: "Faculty" = Relationship(back_populates="degrees")
    modules: list["Module"] = Relationship(back_populates="degrees", link_model=ModuleDegreeLink)

class Faculty(SQLModel, table=True):
    """
    A faculty within the university, e.g. "Fakultät für Informatik", "Fakultät für Mathematik", etc.
    """

    id: int | None = Field(default=None, primary_key=True)
    name: str = ""
    prefix: int | None = None # A short prefix or code for the faculty, e.g. "INF", "MATH", etc.

    modules: list["Module"] = Relationship(back_populates="faculty")
    degrees: list["Degree"] = Relationship(back_populates="faculty")

class Semester(SQLModel, table=True):
    """
    A semester, e.g. "SS 2024", "WS 2024/25", etc.
    """

    id: int | None = Field(default=None, primary_key=True)
    name: str = ""
    year: int = 0
    term: str = "" # "SoSe" for summer semester, "WiSe" for winter semester, etc.

    modules: list["Module"] = Relationship(back_populates="start_semester", link_model=ModuleSemesterLink)
    courses: list["Course"] = Relationship(back_populates="semesters", link_model=CourseSemesterLink)
    events: list["Event"] = Relationship(back_populates="semesters", link_model=EventSemesterLink)
    exams: list["ModuleExam"] = Relationship(back_populates="semesters", link_model=ModuleExamSemesterLink)

class Staff(SQLModel, table=True):
    """
    A staff member involved in teaching or organizing courses and events.
    """

    id: int | None = Field(default=None, primary_key=True)
    name: str = ""

    modules: list["Module"] = Relationship(back_populates="responsible_persons", link_model=ModuleStaffLink)
    courses: list["Course"] = Relationship(back_populates="staff", link_model=CourseStaffLink)
    events: list["Event"] = Relationship(back_populates="staff", link_model=EventStaffLink)
    exams: list["ModuleExam"] = Relationship(back_populates="staff", link_model=ModuleExamStaffLink)

class Status(SQLModel, table=True):
    """
    Status of a course, e.g. "offered", "not offered", "planned", etc.
    """

    id: int | None = Field(default=None, primary_key=True)
    name: str = ""

class EventType(SQLModel, table=True):
    """
    Type of an event, e.g. "lecture", "exercise", "lab", etc.
    """

    id: int | None = Field(default=None, primary_key=True)
    name: str = ""

class ModuleExam(SQLModel, table=True):
    """
    An exam associated with a module.
    """

    id: int | None = Field(default=None, primary_key=True)
    module_id: int = Field(foreign_key="module.id", index=True)
    name: str = ""
    exam_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    required: bool = False # Whether the exam is required for passing the module

    staff: list["Staff"] = Relationship(back_populates="exams", link_model=ModuleExamStaffLink)
    semesters: list["Semester"] = Relationship(back_populates="exams", link_model=ModuleExamSemesterLink)
    module: "Module" = Relationship(back_populates="exams")


class SyncRun(SQLModel, table=True):
    """
    A record of a single data ingestion (crawl) run.

    Tracks the lifecycle of a Scrapy crawl triggered via the API, including its
    current status, process ID (for cancellation), timing, and captured output.
    """

    id: int | None = Field(default=None, primary_key=True)
    status: str = "pending"  # pending | running | completed | failed | cancelled
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    pid: int | None = None  # OS process ID; None once the process has ended
    log: str = ""  # Captured stdout + stderr from the crawl process
    error: str = ""  # Error detail when status is "failed"
