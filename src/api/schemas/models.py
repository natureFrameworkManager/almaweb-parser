from __future__ import annotations

from datetime import date, time

from pydantic import ConfigDict, Field

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
    exams: list[ExamRead] | None = None


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
    courses: list[CourseRead] | None = None
    events: list[EventRead] | None = None
    exams: list[ExamRead] | None = None


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
    url: str | None = Field(default=None, description="Source AlmaWeb page this record was parsed from.")
    # Relationships (populated via ?include=)
    locations: list[LocationRead] | None = None


class DegreeRead(ReadSchema):
    """Mirrors ``database.model.Degree``."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"examples": [{"id": 1, "name": "Informatik (Bachelor of Science)", "subject": "Informatik", "degree": "B.Sc.", "school_type": None, "ects": None, "version": "", "confidence": "high", "faculty_id": 1}]},
    )

    id: int | None = None
    name: str | None = None
    subject: str | None = None
    degree: str | None = None
    school_type: str | None = None
    ects: int | None = None
    version: str | None = None
    confidence: str | None = None
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
    description: str | None = Field(default=None, description="Free text; may contain `\\n` line breaks.")
    type: str | None = None
    seats: int | None = None
    size: float | None = None
    accessibility: str | None = None
    building_id: int | None = None
    url: str | None = Field(default=None, description="Source AlmaWeb page this record was parsed from (the room detail page, or the course page for name-only rooms).")
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
    url: str | None = Field(default=None, description="Source AlmaWeb page this record was parsed from.")
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
    url: str | None = Field(default=None, description="Source AlmaWeb page this record was parsed from (the course page of the event).")
    # Relationships (populated via ?include=)
    location: LocationRead | None = None
    staff: list[StaffRead] | None = None
    semesters: list[SemesterRead] | None = None
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
    url: str | None = Field(default=None, description="Source AlmaWeb module page this exam was parsed from.")
    # Relationships (populated via ?include=)
    staff: list[StaffRead] | None = None
    semesters: list[SemesterRead] | None = None
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
            "org_unit": "10-Institut für Informatik",
            "organisational": "Zielgruppe: B.Sc. Informatik\nPrüfungsleistungen sind laut Prüfungsordnung zu erbringen.",
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
    org_unit: str | None = None
    official_description: str | None = Field(default=None, description="Free text; see the top-level 'Data notes': may contain `\\n` line breaks.")
    organisational: str | None = Field(default=None, description="Free text; may contain `\\n` line breaks.")
    literature: str | None = Field(default=None, description="Free text; may contain `\\n` line breaks.")
    url: str | None = Field(default=None, description="Source AlmaWeb course page this record was parsed from.")
    # Relationships (populated via ?include=)
    staff: list[StaffRead] | None = None
    semesters: list[SemesterRead] | None = None
    modules: list[ModuleRead] | None = None
    events: list[EventRead] | None = None


class AchievementRead(ReadSchema):
    """Mirrors ``database.model.ModuleAchievement`` (a "Leistungen" row).

    These are the module's ``Modulabschlussleistungen`` (coursework/achievements),
    distinct from the final exams exposed by ``ExamRead``.
    """

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"examples": [{
            "id": 1,
            "name": "Portfolio (12 Wochen)",
            "required": True,
            "weight": 1.0,
            "combination": "Ja",
            "module_id": 1,
        }]},
    )

    id: int | None = None
    name: str | None = None
    required: bool | None = None
    weight: float | None = None
    combination: str | None = None
    module_id: int | None = None
    url: str | None = Field(default=None, description="Source AlmaWeb module page this achievement was parsed from.")
    # Relationships (populated via ?include=)
    module: ModuleRead | None = None


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
            "goals": "Grundlegende Kenntnisse über Algorithmen und Datenstrukturen\n- Sortierverfahren\n- Graphenalgorithmen",
            "content": "Sortieralgorithmen, Graphenalgorithmen, Bäume, Hashing",
            "exam_prerequisites": "Bestehen der Übungsaufgaben",
            "prerequisites": {
                "B.Sc. Informatik": "Grundlagen der Programmierung",
                "allgemein": "keine"
            },
            "faculty_id": 1,
            "path": [["Root", "Informatik", "Informatik (Bachelor of Science)", "Pflichtmodule"]],
        }]},
    )

    id: int | None = None
    name: str | None = None
    number: str | None = None
    language: str | None = Field(default=None, description="Deprecated: derived from the module's courses; prefer the course `language`.")
    duration_semesters: int | None = None
    credits: float | None = None
    frequency: str | None = None
    goals: str | None = Field(default=None, description="Free text; see the top-level 'Data notes': may contain `\\n` line breaks.")
    content: str | None = Field(default=None, description="Free text; may contain `\\n` line breaks.")
    exam_prerequisites: str | None = Field(default=None, description="Free text; may contain `\\n` line breaks.")
    prerequisites: dict[str, str] | None = Field(
        default=None,
        description="Requirement text per study-programme context. Keys are the study-programme names from AlmaWeb "
                    "(or the generic `allgemein`); values are the requirement text for that context.",
    )
    literature: str | None = Field(default=None, description="Free text; may contain `\\n` line breaks.")
    elective_course_count: int | None = None
    elective_prerequisites: str | None = Field(default=None, description="Free text; may contain `\\n` line breaks.")
    elective_classification: str | None = Field(default=None, description="Free text; may contain `\\n` line breaks.")
    grading_note: str | None = Field(default=None, description="Free text; may contain `\\n` line breaks.")
    faculty_id: int | None = None
    path: list[list[str]] | None = None
    url: str | None = Field(default=None, description="Source AlmaWeb module page this record was parsed from.")
    # Relationships (populated via ?include=)
    faculty: FacultyRead | None = None
    responsible_persons: list[StaffRead] | None = None
    start_semester: list[SemesterRead] | None = None
    semesters: list[SemesterRead] | None = None
    exams: list[ExamRead] | None = None
    achievements: list[AchievementRead] | None = None
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
AchievementRead.model_rebuild()
CourseRead.model_rebuild()
ModuleRead.model_rebuild()
