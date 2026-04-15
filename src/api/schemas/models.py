from __future__ import annotations

from datetime import date, time

from .shared import ReadSchema


# ---------------------------------------------------------------------------
# Simple catalog schemas (no relationships)
# ---------------------------------------------------------------------------

class EventTypeRead(ReadSchema):
    """Mirrors ``database.model.EventType``."""

    id: int | None = None
    name: str | None = None


class StatusRead(ReadSchema):
    """Mirrors ``database.model.Status``."""

    id: int | None = None
    name: str | None = None


# ---------------------------------------------------------------------------
# Entity schemas – forward references resolved via model_rebuild() at EOF
# ---------------------------------------------------------------------------

class StaffRead(ReadSchema):
    """Mirrors ``database.model.Staff``."""

    id: int | None = None
    name: str | None = None
    # Relationships (populated via ?include=)
    modules: list[ModuleRead] | None = None
    courses: list[CourseRead] | None = None
    events: list[EventRead] | None = None


class SemesterRead(ReadSchema):
    """Mirrors ``database.model.Semester``."""

    id: int | None = None
    name: str | None = None
    year: int | None = None
    term: str | None = None
    # Relationships (populated via ?include=)
    modules: list[ModuleRead] | None = None


class FacultyRead(ReadSchema):
    """Mirrors ``database.model.Faculty``."""

    id: int | None = None
    name: str | None = None
    prefix: int | None = None
    # Relationships (populated via ?include=)
    modules: list[ModuleRead] | None = None
    degrees: list[DegreeRead] | None = None


class BuildingRead(ReadSchema):
    """Mirrors ``database.model.Building``."""

    id: int | None = None
    name: str | None = None
    short_name: str | None = None
    address: str | None = None
    # Relationships (populated via ?include=)
    locations: list[LocationRead] | None = None


class DegreeRead(ReadSchema):
    """Mirrors ``database.model.Degree``."""

    id: int | None = None
    name: str | None = None
    faculty_id: int | None = None
    # Relationships (populated via ?include=)
    faculty: FacultyRead | None = None
    modules: list[ModuleRead] | None = None


class LocationRead(ReadSchema):
    """Mirrors ``database.model.Location``."""

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


class EventRead(ReadSchema):
    """Mirrors ``database.model.Event``."""

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


class CourseRead(ReadSchema):
    """Mirrors ``database.model.Course``.

    The ``type`` and ``status`` columns are FK integer values by default.
    When the corresponding relation is included via ``?include=type`` or
    ``?include=status``, the integer is replaced by the nested object.
    """

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
EventRead.model_rebuild()
CourseRead.model_rebuild()
ModuleRead.model_rebuild()
