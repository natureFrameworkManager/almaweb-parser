from __future__ import annotations

from datetime import date, time

from pydantic import ConfigDict

from .shared import ReadSchema


# ---------------------------------------------------------------------------
# Simple catalog schemas (no relationships)
# ---------------------------------------------------------------------------

class EventTypeRead(ReadSchema):
    """Mirrors ``database.model.EventType``."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"examples": [{"id": 1, "name": "Vorlesung"}]},
    )

    id: int | None = None
    name: str | None = None


class StatusRead(ReadSchema):
    """Mirrors ``database.model.Status``."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"examples": [{"id": 1, "name": "almawe "}, {"id": 2, "name": "ok"}, {"id": 3, "name": "tok"}]},
    )

    id: int | None = None
    name: str | None = None


# ---------------------------------------------------------------------------
# Entity schemas – forward references resolved via model_rebuild() at EOF
# ---------------------------------------------------------------------------

class StaffRead(ReadSchema):
    """Mirrors ``database.model.Staff``."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"examples": [{"id": 1, "name": "Prof. Dr. Max Mustermann"}]},
    )

    id: int | None = None
    name: str | None = None
    # Relationships (populated via ?include=)
    modules: list[ModuleRead] | None = None
    courses: list[CourseRead] | None = None
    events: list[EventRead] | None = None


class SemesterRead(ReadSchema):
    """Mirrors ``database.model.Semester``."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"examples": [{"id": 1, "name": "WiSe 2025/26", "year": 2025, "term": "WiSe"}]},
    )

    id: int | None = None
    name: str | None = None
    year: int | None = None
    term: str | None = None
    # Relationships (populated via ?include=)
    modules: list[ModuleRead] | None = None


class FacultyRead(ReadSchema):
    """Mirrors ``database.model.Faculty``."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"examples": [{"id": 1, "name": "Fakultät für Mathematik und Informatik", "prefix": 10}]},
    )

    id: int | None = None
    name: str | None = None
    prefix: int | None = None
    # Relationships (populated via ?include=)
    modules: list[ModuleRead] | None = None
    degrees: list[DegreeRead] | None = None


class BuildingRead(ReadSchema):
    """Mirrors ``database.model.Building``."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"examples": [{
            "id": 1,
            "name": "Augusteum",
            "short_name": "AUG",
            "address": "Augustusplatz 10, 04109 Leipzig",
        }]},
    )

    id: int | None = None
    name: str | None = None
    short_name: str | None = None
    address: str | None = None
    # Relationships (populated via ?include=)
    locations: list[LocationRead] | None = None


class DegreeRead(ReadSchema):
    """Mirrors ``database.model.Degree``."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"examples": [{"id": 1, "name": "Informatik (Bachelor of Science)", "faculty_id": 1}]},
    )

    id: int | None = None
    name: str | None = None
    faculty_id: int | None = None
    # Relationships (populated via ?include=)
    faculty: FacultyRead | None = None
    modules: list[ModuleRead] | None = None


class LocationRead(ReadSchema):
    """Mirrors ``database.model.Location``."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"examples": [{
            "id": 1,
            "name": "Hörsaal 1",
            "external_id": "AUG-HS1",
            "description": "Großer Hörsaal im Augusteum",
            "type": "Hörsaal",
            "seats": 300,
            "size": 450.0,
            "accessibility": "barrierefrei",
            "building_id": 1,
        }]},
    )

    id: int | None = None
    name: str | None = None
    external_id: str | None = None
    description: str | None = None
    type: str | None = None
    seats: int | None = None
    size: float | None = None
    accessibility: str | None = None
    building_id: int | None = None
    # Relationships (populated via ?include=)
    building: BuildingRead | None = None
    events: list[EventRead] | None = None


class WeeklyRead(ReadSchema):
    """Mirrors ``database.model.Event``."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"examples": [{
            "id": 1,
            "number": "10-INF-B-001-V",
            "name": "Algorithmen und Datenstrukturen",
            "start_time": "09:15:00",
            "end_time": "10:45:00",
            "weekday": 1,
            "location_id": 1,
        }]},
    )

    id: int | None = None
    number: str | None = None
    name: str | None = None
    start_time: time | None = None
    end_time: time | None = None
    weekday: int
    location_id: int | None = None
    # Relationships (populated via ?include=)
    location: LocationRead | None = None
    staff: list[StaffRead] | None = None
    courses: list[CourseRead] | None = None


class EventRead(ReadSchema):
    """Mirrors ``database.model.Event``."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"examples": [{
            "id": 1,
            "number": "10-INF-B-001-V",
            "name": "Algorithmen und Datenstrukturen",
            "start_time": "09:15:00",
            "end_time": "10:45:00",
            "event_date": "2025-11-03",
            "location_id": 1,
        }]},
    )

    id: int | None = None
    number: str | None = None
    name: str | None = None
    start_time: time | None = None
    end_time: time | None = None
    event_date: date | None = None
    location_id: int | None = None
    # Relationships (populated via ?include=)
    location: LocationRead | None = None
    staff: list[StaffRead] | None = None
    courses: list[CourseRead] | None = None


class ExamRead(ReadSchema):
    """Mirrors ``database.model.Exam``.

    The ``module_id`` column is a FK integer value by default.
    When the corresponding relation is included via ``?include=module"``, the corresponding object is included.
    """

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"examples": [{
            "id": 1,
            "name": "1 Praktikumsbericht",
            "exam_date": "2025-11-03",
            "start_time": "09:15:00",
            "end_time": "10:45:00",
            "required": True,
            "module_id": 1
        }]},
    )

    id: int | None = None
    name: str | None = None
    exam_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    required: bool | None = None
    module_id: int | None = None
    # Relationships (populated via ?include=)
    staff: list[StaffRead] | None = None
    module: ModuleRead | None = None


class CourseRead(ReadSchema):
    """Mirrors ``database.model.Course``.

    The ``type`` and ``status`` columns are FK integer values by default.
    When the corresponding relation is included via ``?include=type`` or
    ``?include=status``, the integer is replaced by the nested object.
    """

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"examples": [{
            "id": 1,
            "name": "Algorithmen und Datenstrukturen",
            "number": "10-INF-B-001",
            "type": 1,
            "weekday": 1,
            "weekly_hours": 4,
            "language": "Deutsch",
            "status": 1,
        }]},
    )

    id: int | None = None
    name: str | None = None
    number: str | None = None
    type: int | EventTypeRead | None = None
    weekday: int | None = None
    weekly_hours: int | None = None
    language: str | None = None
    status: int | StatusRead | None = None
    # Relationships (populated via ?include=)
    staff: list[StaffRead] | None = None
    modules: list[ModuleRead] | None = None
    events: list[EventRead] | None = None


class ModuleRead(ReadSchema):
    """Mirrors ``database.model.Module``."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"examples": [{
            "id": 1,
            "name": "Algorithmen und Datenstrukturen 1",
            "number": "10-201-2011",
            "language": "Deutsch",
            "duration_semesters": 1,
            "credits": 10.0,
            "frequency": "jedes Wintersemester",
            "goals": "Grundlegende Kenntnisse über Algorithmen und Datenstrukturen",
            "content": "Sortieralgorithmen, Graphenalgorithmen, Bäume, Hashing",
            "exam_prerequisites": "Bestehen der Übungsaufgaben",
            "prerequisites": {"mandatory": "Grundlagen der Programmierung"},
            "faculty_id": 1,
            "path": ["Root", "Informatik", "Informatik (Bachelor of Science)", "Pflichtmodule"],
        }]},
    )

    id: int | None = None
    name: str | None = None
    number: str | None = None
    language: str | None = None
    duration_semesters: int | None = None
    credits: float | None = None
    frequency: str | None = None
    goals: str | None = None
    content: str | None = None
    exam_prerequisites: str | None = None
    prerequisites: dict[str, str] | None = None
    faculty_id: int | None = None
    path: list[str] | None = None
    # Relationships (populated via ?include=)
    faculty: FacultyRead | None = None
    responsible_persons: list[StaffRead] | None = None
    start_semester: list[SemesterRead] | None = None
    degrees: list[DegreeRead] | None = None
    courses: list[CourseRead] | None = None


# ---------------------------------------------------------------------------
# Resolve forward references for circular relationships
# ---------------------------------------------------------------------------
StaffRead.model_rebuild()
SemesterRead.model_rebuild()
FacultyRead.model_rebuild()
BuildingRead.model_rebuild()
DegreeRead.model_rebuild()
LocationRead.model_rebuild()
WeeklyRead.model_rebuild()
EventRead.model_rebuild()
ExamRead.model_rebuild()
CourseRead.model_rebuild()
ModuleRead.model_rebuild()
