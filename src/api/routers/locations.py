from typing import Annotated

from fastapi import APIRouter, Query, Depends
from sqlmodel import select
from sqlalchemy import or_

from database.database import SessionDep
from database.model import Location, Building, Event
from .shared import export_parameters, export_event_parameters, paging_parameters, page_query, sort_parameters, sort_query, filter_query, fields_parameters

location_router = APIRouter(prefix="/locations", tags=["Locations"])

@location_router.get("", summary="List all locations")
def get_locations(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Location))],
    fielding: Annotated[dict, Depends(fields_parameters(Location))],
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
):
    """Retrieve a list of all locations."""
    query = select(Location)

    if ids:
        query = query.where(or_(*[Location.id == value for value in ids])) # type: ignore
    if names:
        query = query.where(or_(*[Location.name.ilike(f"%{value}%") for value in names])) # type: ignore
    if external_ids:
        query = query.where(or_(*[Location.external_id.ilike(f"%{value}%") for value in external_ids])) # type: ignore
    if types:
        query = query.where(or_(*[Location.type.ilike(f"%{value}%") for value in types])) # type: ignore
    if seats_min is not None:
        query = query.where(Location.seats >= seats_min) # type: ignore
    if seats_max is not None:
        query = query.where(Location.seats <= seats_max) # type: ignore
    if size_min is not None:
        query = query.where(Location.size >= size_min) # type: ignore
    if size_max is not None:
        query = query.where(Location.size <= size_max) # type: ignore
    if building_ids:
        query = query.where(or_(*[Location.building_id == value for value in building_ids])) # type: ignore

    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Location)
    items = filter_query(session, query, fielding, Location)
    return {
        "count": data["count"],
        "page": data["page"],
        "limit": data["limit"],
        "total_pages": data["total_pages"],
        "items": items,
    }

@location_router.get("/{location_id}", summary="Get location details")
def get_location_details(
    session: SessionDep,
    fielding: Annotated[dict, Depends(fields_parameters(Location))],
    export: Annotated[dict, Depends(export_parameters)],
    location_id: int,
    include: list[str] | None = Query(None, description="Include related entities in the response. Possible values: 'courses'. Repeatable for multiple relations."),
):
    """Retrieve detailed information about a specific location by its ID."""
    query = select(Location).where(Location.id == location_id)
    items = filter_query(session, query, fielding, Location)
    return items[0] if items else None

@location_router.get("/{location_id}/events", summary="List events for a location")
def get_location_events(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Event))],
    fielding: Annotated[dict, Depends(fields_parameters(Event))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_event_parameters)],
    location_id: int,
    include: list[str] | None = Query(None, description="Include related entities in the response. Possible values: 'modules', 'staff'. Repeatable for multiple relations."),
):
    """Retrieve a list of events associated with a specific location."""
    query = select(Event).where(Event.location_id == location_id)
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Event)
    items = filter_query(session, query, fielding, Event)
    return {
        "count": data["count"],
        "page": data["page"],
        "limit": data["limit"],
        "total_pages": data["total_pages"],
        "items": items,
    }

@location_router.get("/{location_id}/building", summary="Get building details for a location")
def get_location_building(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Building))],
    fielding: Annotated[dict, Depends(fields_parameters(Building))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
    location_id: int,
    include: list[str] | None = Query(None, description="Include related entities in the response. Possible values: 'modules'. Repeatable for multiple relations."),
):
    """Retrieve building details for a specific location."""
    query = select(Building).where(Building.locations.any(Location.id == location_id))  # type: ignore
    items = filter_query(session, query, fielding, Building)
    return items[0] if items else None

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
    sorting: Annotated[dict, Depends(sort_parameters(Building))],
    fielding: Annotated[dict, Depends(fields_parameters(Building))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
    ids: list[int] | None = Query(None, description="Building ID values (repeatable; OR within this filter)."),
    names: list[str] | None = Query(None, description="Building name values (repeatable; case-insensitive, partial match; OR within this filter)."),
    short_names: list[str] | None = Query(None, description="Building short name values (repeatable; case-insensitive, partial match; OR within this filter)."),
    addresses: list[str] | None = Query(None, description="Building address values (repeatable; case-insensitive, partial match; OR within this filter)."),
    location_ids: list[int] | None = Query(None, description="Location ID values to filter buildings that contain specific locations (repeatable; OR within this filter)."),
):
    """Retrieve a list of all buildings."""
    query = select(Building)

    if ids:
        query = query.where(or_(*[Building.id == value for value in ids])) # type: ignore
    if names:
        query = query.where(or_(*[Building.name.ilike(f"%{value}%") for value in names])) # type: ignore
    if short_names:
        query = query.where(or_(*[Building.short_name.ilike(f"%{value}%") for value in short_names])) # type: ignore
    if addresses:
        query = query.where(or_(*[Building.address.ilike(f"%{value}%") for value in addresses])) # type: ignore
    if location_ids:
        query = query.join(Location).where(or_(*[Location.id == value for value in location_ids])) # type: ignore

    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Building)
    items = filter_query(session, query, fielding, Building)
    return {
        "count": data["count"],
        "page": data["page"],
        "limit": data["limit"],
        "total_pages": data["total_pages"],
        "items": items,
    }

@room_router.get("/{building_id}", summary="Get building details")
def get_building_details(
    session: SessionDep,
    export: Annotated[dict, Depends(export_parameters)],
    building_id: int,
    include: list[str] | None = Query(None, description="Include related entities in the response. Possible values: 'locations'. Repeatable for multiple relations."),
    fields: list[str] | None = Query(None, description="Comma-separated list of fields to include in the response. If not provided, all fields will be included."), # type: ignore
):
    """Retrieve detailed information about a specific building by its ID."""
    return session.exec(select(Building).where(Building.id == building_id)).first()

@room_router.get("/{building_id}/locations", summary="List locations for a building")
def get_building_locations(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Location))],
    fielding: Annotated[dict, Depends(fields_parameters(Location))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
    building_id: int,
    include: list[str] | None = Query(None, description="Include related entities in the response. Possible values: 'events'. Repeatable for multiple relations."),
):
    """Retrieve a list of locations associated with a specific building."""
    query = select(Location).where(Location.building_id == building_id)
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Location)
    items = filter_query(session, query, fielding, Location)
    return {
        "count": data["count"],
        "page": data["page"],
        "limit": data["limit"],
        "total_pages": data["total_pages"],
        "items": items,
    }

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