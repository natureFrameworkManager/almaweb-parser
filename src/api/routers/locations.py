from typing import Annotated

from fastapi import APIRouter, Query, Depends

from database.database import SessionDep
from .shared import export_parameters, paging_parameters

location_router = APIRouter(prefix="/locations", tags=["Locations"])

@location_router.get("", summary="List all locations")
def get_locations(
    session: SessionDep,
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
    ids: list[int] | None = Query(None, description="Location ID values (repeatable; OR within this filter)."),
    names: list[str] | None = Query(None, description="Location name values (repeatable; case-insensitive, partial match; OR within this filter)."),
    external_ids: list[str] | None = Query(None, description="External ID values (repeatable; OR within this filter)."),
    types: list[str] | None = Query(None, description="Location type values (repeatable; case-insensitive, partial match; OR within this filter)."),
    seats_min: int | None = Query(None, ge=0, description="Minimum number of seats (inclusive)."),
    seats_max: int | None = Query(None, ge=0, description="Maximum number of seats (inclusive)."),
    size_min: float | None = Query(None, ge=0, description="Minimum size in square meters (inclusive)."),
    size_max: float | None = Query(None, ge=0, description="Maximum size in square meters (inclusive)."),
    accessible: bool | None = Query(None, description="Whether the location is accessible (true or false)."),
    building_ids: list[int] | None = Query(None, description="Building ID values to filter locations within specific buildings (repeatable; OR within this filter)."),
    sort: str | None = Query(None, description="Sort order for the results. For example, 'name_asc' or 'id_desc'."),
):
    """Retrieve a list of all locations."""
    pass

@location_router.get("/{location_id}", summary="Get location details")
def get_location_details(
    session: SessionDep,
    export: Annotated[dict, Depends(export_parameters)],
    location_id: int,
    include: list[str] | None = Query(None, description="Include related entities in the response. Possible values: 'courses'. Repeatable for multiple relations."),
    fields: list[str] | None = Query(None, description="Comma-separated list of fields to include in the response. If not provided, all fields will be included."), # type: ignore
):
    """Retrieve detailed information about a specific location by its ID."""
    pass

@location_router.get("/{location_id}/events", summary="List events for a location")
def get_location_events(
    session: SessionDep,
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
    location_id: int,
    include: list[str] | None = Query(None, description="Include related entities in the response. Possible values: 'modules', 'staff'. Repeatable for multiple relations."),
    fields: list[str] | None = Query(None, description="Comma-separated list of fields to include in the response. If not provided, all fields will be included."), # type: ignore
    sort: str | None = Query(None, description="Sort order for the results. For example, 'name_asc' or 'start_time_desc'."),
):
    """Retrieve a list of events associated with a specific location."""
    pass

@location_router.get("/{location_id}/building", summary="Get building details for a location")
def get_location_building(
    session: SessionDep,
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
    location_id: int,
    include: list[str] | None = Query(None, description="Include related entities in the response. Possible values: 'modules'. Repeatable for multiple relations."),
    fields: list[str] | None = Query(None, description="Comma-separated list of fields to include in the response. If not provided, all fields will be included."), # type: ignore
    sort: str | None = Query(None, description="Sort order for the results. For example, 'name_asc' or 'credits_desc'."),
):
    """Retrieve building details for a specific location."""
    pass

@location_router.get("/distinct/{field_name}", summary="Get distinct values")
def get_location_distinct_field(
    session: SessionDep,
    field_name: str,
    sort: str | None = Query(None, description="Sort order for the results. For example, 'asc' or 'desc'."),
    format: str | None = Query(None, description="Response format (e.g., 'json', 'csv')."),
):
    """Retrieve distinct values for a specific field across all locations."""
    pass

@location_router.get("/changes", summary="Get location changelog")
def get_location_changes(
    session: SessionDep,
    paging: Annotated[dict, Depends(paging_parameters)],
    since: str = Query(..., description="Filter changes that occurred on or after this ISO 8601 datetime."),
    until: str | None = Query(None, description="Filter changes that occurred on or before this ISO 8601 datetime."),
    include_deleted: bool = Query(False, description="Whether to include deleted locations in the changelog."),
    sort: str | None = Query(None, description="Sort order for the results. For example, 'date_asc' or 'date_desc'."),
    format: str | None = Query(None, description="Response format (e.g., 'json', 'csv')."),
):
    """Retrieve a changelog of location modifications within a specified time range."""
    pass


room_router = APIRouter(prefix="/buildings", tags=["Buildings"])

@room_router.get("", summary="List all buildings")
def get_buildings(
    session: SessionDep,
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
    ids: list[int] | None = Query(None, description="Building ID values (repeatable; OR within this filter)."),
    names: list[str] | None = Query(None, description="Building name values (repeatable; case-insensitive, partial match; OR within this filter)."),
    short_names: list[str] | None = Query(None, description="Building short name values (repeatable; case-insensitive, partial match; OR within this filter)."),
    addresses: list[str] | None = Query(None, description="Building address values (repeatable; case-insensitive, partial match; OR within this filter)."),
    location_ids: list[int] | None = Query(None, description="Location ID values to filter buildings that contain specific locations (repeatable; OR within this filter)."),
    sort: str | None = Query(None, description="Sort order for the results. For example, 'name_asc' or 'id_desc'."),
):
    """Retrieve a list of all buildings."""
    pass

@room_router.get("/{building_id}", summary="Get building details")
def get_building_details(
    session: SessionDep,
    export: Annotated[dict, Depends(export_parameters)],
    building_id: int,
    include: list[str] | None = Query(None, description="Include related entities in the response. Possible values: 'locations'. Repeatable for multiple relations."),
    fields: list[str] | None = Query(None, description="Comma-separated list of fields to include in the response. If not provided, all fields will be included."), # type: ignore
):
    """Retrieve detailed information about a specific building by its ID."""
    pass

@room_router.get("/{building_id}/locations", summary="List locations for a building")
def get_building_locations(
    session: SessionDep,
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
    building_id: int,
    include: list[str] | None = Query(None, description="Include related entities in the response. Possible values: 'events'. Repeatable for multiple relations."),
    fields: list[str] | None = Query(None, description="Comma-separated list of fields to include in the response. If not provided, all fields will be included."), # type: ignore
    sort: str | None = Query(None, description="Sort order for the results. For example, 'name_asc' or 'seats_desc'."),
):
    """Retrieve a list of locations associated with a specific building."""
    pass

@room_router.get("/distinct/{field_name}", summary="Get distinct values")
def get_building_distinct_field(
    session: SessionDep,
    field_name: str,
    sort: str | None = Query(None, description="Sort order for the results. For example, 'asc' or 'desc'."),
    format: str | None = Query(None, description="Response format (e.g., 'json', 'csv')."),
):
    """Retrieve distinct values for a specific field across all buildings."""
    pass

@room_router.get("/changes", summary="Get building changelog")
def get_building_changes(
    session: SessionDep,
    paging: Annotated[dict, Depends(paging_parameters)],
    since: str = Query(..., description="Filter changes that occurred on or after this ISO 8601 datetime."),
    until: str | None = Query(None, description="Filter changes that occurred on or before this ISO 8601 datetime."),
    include_deleted: bool = Query(False, description="Whether to include deleted buildings in the changelog."),
    sort: str | None = Query(None, description="Sort order for the results. For example, 'date_asc' or 'date_desc'."),
    format: str | None = Query(None, description="Response format (e.g., 'json', 'csv')."),
):
    """Retrieve a changelog of building modifications within a specified time range."""
    pass