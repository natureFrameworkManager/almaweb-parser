from typing import Annotated

from fastapi import APIRouter, Query, Depends

from database.database import SessionDep
from .shared import export_parameters, paging_parameters

router = APIRouter(prefix="/schedule", tags=["Schedule"])

@router.get("/weekly", summary="Get generic weekly schedule")
def get_weekly_schedule(
    session: SessionDep,
    export: Annotated[dict, Depends(export_parameters)],
    semester_id: int = Query(..., description="ID of the semester to retrieve the schedule for."),
    faculty_ids: list[int] | None = Query(None, description="Filter schedule by faculty IDs (repeatable; OR within this filter)."),
    degree_ids: list[int] | None = Query(None, description="Filter schedule by degree IDs (repeatable; OR within this filter)."),
    course_ids: list[int] | None = Query(None, description="Filter schedule by course IDs (repeatable; OR within this filter)."),
    module_ids: list[int] | None = Query(None, description="Filter schedule by module IDs (repeatable; OR within this filter)."),
    staff_ids: list[int] | None = Query(None, description="Filter schedule by staff IDs (repeatable; OR within this filter)."),
    location_ids: list[int] | None = Query(None, description="Filter schedule by location IDs (repeatable; OR within this filter)."),
    building_ids: list[int] | None = Query(None, description="Filter schedule by building IDs (repeatable; OR within this filter)."),
    weekdays: list[int] | None = Query(None, description="Filter schedule by weekday IDs (0=Monday, 6=Sunday; repeatable; OR within this filter)."),
    split_by_day: bool = Query(False, description="Whether to split the schedule by day of the week in the response."),
    sort: str | None = Query(None, description="Sort order for the results. For example, 'start_time_asc' or 'end_time_desc'."),
):
    """Retrieve a generic weekly schedule."""
    pass
