from datetime import datetime

from pydantic import BaseModel, ConfigDict


class LinkStats(BaseModel):
    """Counts for each many-to-many association table."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{
            "course_event": 512,
            "course_staff": 230,
            "event_staff": 480,
            "module_course": 310,
            "module_degree": 175,
            "module_semester": 290,
            "module_staff": 205,
        }]},
    )

    course_event: int
    course_staff: int
    event_staff: int
    module_course: int
    module_degree: int
    module_semester: int
    module_staff: int


class StatsResponse(BaseModel):
    """Response schema for ``GET /admin/stats``."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{
            "buildings": 42,
            "courses": 350,
            "degrees": 85,
            "events": 1200,
            "event_types": 6,
            "faculties": 14,
            "locations": 120,
            "modules": 280,
            "semesters": 4,
            "staff": 190,
            "statuses": 3,
            "links": {
                "course_event": 512,
                "course_staff": 230,
                "event_staff": 480,
                "module_course": 310,
                "module_degree": 175,
                "module_semester": 290,
                "module_staff": 205,
            },
        }]},
    )

    buildings: int
    courses: int
    degrees: int
    events: int
    event_types: int
    faculties: int
    locations: int
    modules: int
    semesters: int
    staff: int
    statuses: int
    links: LinkStats


class SyncRunRead(BaseModel):
    """Response schema for sync run endpoints."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"examples": [{
            "id": 1,
            "status": "completed",
            "started_at": "2026-05-23T10:00:00Z",
            "finished_at": "2026-05-23T10:05:42Z",
            "log": "2026-05-23 10:00:01 [scrapy.core.engine] INFO: Spider opened\n...",
            "error": "",
        }]},
    )

    id: int
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    log: str = ""
    error: str = ""
