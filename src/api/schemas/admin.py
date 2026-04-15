from pydantic import BaseModel


class LinkStats(BaseModel):
    """Counts for each many-to-many association table."""

    course_event: int
    course_staff: int
    event_staff: int
    module_course: int
    module_degree: int
    module_semester: int
    module_staff: int


class StatsResponse(BaseModel):
    """Response schema for ``GET /admin/stats``."""

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
