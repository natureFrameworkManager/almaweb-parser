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

class ModuleType(TypedDict):
    name: str
    number: str
    path: list[str]
    responsible_person: str
    duration_semesters: int
    credits: float
    start_semester: str
    frequency: str
    goals: str
    content: str
    exam_prerequisites: str
    prerequisites: dict[str, str]
    courses: list[CourseType | None]