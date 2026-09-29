from typing import TypedDict
from datetime import date, time

class BuildingType(TypedDict):
    name: str
    short_name: str
    address: str

class RoomType(TypedDict):
    name: str
    external_id: str
    description: str
    type: str
    seats: int | None
    size: float | None
    accessibility: str
    building: BuildingType

class EventType(TypedDict):
    number: str
    event_date: date
    start_time: time
    end_time: time
    location: RoomType | None
    staff: list[str]

class CourseType(TypedDict):
    name: str
    number: str
    staff: list[str]
    type: str
    weekly_hours: int
    language: str
    events: list[EventType]
    status: str
    org_unit: str
    official_description: str
    organisational: str
    literature: str

class ExamType(TypedDict):
    name: str
    date: date
    start_time: time
    end_time: time
    staff: list[str]
    required: bool

class AchievementType(TypedDict):
    """A ``Modulabschlussleistung`` / achievement row from the "Leistungen" table.

    The source table has no separate column for staff, so this carries only the
    achievement name, the compulsory flag, the weighting and the raw
    ``Leistungskombination`` value.
    """

    name: str
    required: bool
    weight: float | None
    combination: str

class ModuleType(TypedDict):
    name: str
    number: str
    # Canonical navigation-path shape: a list of path groups (``list[list[str]]``).
    # Flat paths are normalised into a single group on insert.
    path: list[list[str]]
    responsible_person: str
    duration_semesters: int
    credits: float
    start_semester: str
    frequency: str
    goals: str
    content: str
    exam_prerequisites: str
    prerequisites: dict[str, str]
    literature: str
    elective_course_count: int
    elective_prerequisites: str
    elective_classification: str
    grading_note: str
    courses: list[CourseType | None]
    exams: list[ExamType]
    achievements: list[AchievementType]