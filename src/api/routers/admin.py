from fastapi import APIRouter
from sqlmodel import select, func

from .shared import SessionDep
from schemas import StatsResponse
from database.model import Building, Course, Degree, Event, EventType, Faculty, Location, Module, Semester, Staff, Status, CourseEventLink, CourseStaffLink, EventStaffLink, ModuleCourseLink, ModuleDegreeLink, ModuleSemesterLink, ModuleStaffLink

router = APIRouter(prefix="/admin", tags=["Admin"])

@router.get("/health", summary="Check system health")
def get_health():
    """Retrieve the health status of the system."""
    pass

@router.get("/stats", summary="Get system statistics", response_model=StatsResponse)
def get_stats(
    session: SessionDep,
):
    """Retrieve various statistics about the system."""
    counts = {
        "buildings": session.exec(select(func.count()).select_from(Building)).one(),
        "courses": session.exec(select(func.count()).select_from(Course)).one(),
        "degrees": session.exec(select(func.count()).select_from(Degree)).one(),
        "events": session.exec(select(func.count()).select_from(Event)).one(),
        "event_types": session.exec(select(func.count()).select_from(EventType)).one(),
        "faculties": session.exec(select(func.count()).select_from(Faculty)).one(),
        "locations": session.exec(select(func.count()).select_from(Location)).one(),
        "modules": session.exec(select(func.count()).select_from(Module)).one(),
        "semesters": session.exec(select(func.count()).select_from(Semester)).one(),
        "staff": session.exec(select(func.count()).select_from(Staff)).one(),
        "statuses": session.exec(select(func.count()).select_from(Status)).one(),
        "links": {
            "course_event": session.exec(select(func.count()).select_from(CourseEventLink)).one(),
            "course_staff": session.exec(select(func.count()).select_from(CourseStaffLink)).one(),
            "event_staff": session.exec(select(func.count()).select_from(EventStaffLink)).one(),
            "module_course": session.exec(select(func.count()).select_from(ModuleCourseLink)).one(),
            "module_degree": session.exec(select(func.count()).select_from(ModuleDegreeLink)).one(),
            "module_semester": session.exec(select(func.count()).select_from(ModuleSemesterLink)).one(),
            "module_staff": session.exec(select(func.count()).select_from(ModuleStaffLink)).one(),
        }
    }
    return counts

@router.get("/sync", summary="List ingestion runs")
def list_ingestion_runs():
    """Retrieve a list of all ingestion runs."""
    pass

@router.post("/sync", summary="Trigger data ingestion")
def trigger_data_ingestion():
    """Trigger a new data ingestion process."""
    pass