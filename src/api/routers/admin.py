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
    couts = {
        "buildings": len(session.exec(select(Building)).all()),
        "courses": len(session.exec(select(Course)).all()),
        "degrees": len(session.exec(select(Degree)).all()),
        "events": len(session.exec(select(Event)).all()),
        "event_types": len(session.exec(select(EventType)).all()),
        "faculties": len(session.exec(select(Faculty)).all()),
        "locations": len(session.exec(select(Location)).all()),
        "modules": len(session.exec(select(Module)).all()),
        "semesters": len(session.exec(select(Semester)).all()),
        "staff": len(session.exec(select(Staff)).all()),
        "statuses": len(session.exec(select(Status)).all()),
        "links": {
            "course_event": len(session.exec(select(CourseEventLink)).all()),
            "course_staff": len(session.exec(select(CourseStaffLink)).all()),
            "event_staff": len(session.exec(select(EventStaffLink)).all()),
            "module_course": len(session.exec(select(ModuleCourseLink)).all()),
            "module_degree": len(session.exec(select(ModuleDegreeLink)).all()),
            "module_semester": len(session.exec(select(ModuleSemesterLink)).all()),
            "module_staff": len(session.exec(select(ModuleStaffLink)).all()),
        }
    }
    return couts

@router.get("/sync", summary="List ingestion runs")
def list_ingestion_runs():
    """Retrieve a list of all ingestion runs."""
    pass

@router.post("/sync", summary="Trigger data ingestion")
def trigger_data_ingestion():
    """Trigger a new data ingestion process."""
    pass