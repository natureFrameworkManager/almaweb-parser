from typing import Annotated

from fastapi import APIRouter, Query, Depends
from sqlmodel import select
from sqlalchemy import or_

from database.model import Location, Building, Event, Module
from .shared import SessionDep, export_parameters, export_event_parameters, paging_parameters, page_query, sort_parameters, sort_query, filter_query, fields_parameters, include_parameters, build_list_response, build_event_list_response, get_or_404, distinct_parameters
from schemas import PaginatedResponse, LocationRead, BuildingRead, EventRead

location_router = APIRouter(prefix="/locations", tags=["Locations"])

@location_router.get("", summary="List all locations", response_model=PaginatedResponse[LocationRead], response_model_exclude_unset=True)
def get_locations(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Location))],
    including: Annotated[dict, Depends(include_parameters(Location))],
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
    event_id: list[int] | None = Query(None, description="Event ID values to filter locations associated with specific events (repeatable; OR within this filter)."),
    has_events: bool | None = Query(None, description="Filter by whether a location has at least one event (true) or none (false)."),
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
    if event_id:
        query = query.where(or_(*[Location.events.any(Event.id == value) for value in event_id]))  # type: ignore
    if has_events is not None:
        exists_expr = Location.events.any()  # type: ignore
        query = query.where(exists_expr if has_events else ~exists_expr)

    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Location)
    items = filter_query(session, query, fielding, Location, including)
    return build_list_response(data, items, export)

@location_router.get("/{location_id}", summary="Get location details", response_model=LocationRead, response_model_exclude_unset=True)
def get_location_details(
    session: SessionDep,
    including: Annotated[dict, Depends(include_parameters(Location))],
    fielding: Annotated[dict, Depends(fields_parameters(Location))],
    export: Annotated[dict, Depends(export_parameters)],
    location_id: int,
):
    """Retrieve detailed information about a specific location by its ID."""
    get_or_404(session, Location, location_id, "Location")
    query = select(Location).where(Location.id == location_id)
    items = filter_query(session, query, fielding, Location, including)
    return items[0] if items else None

@location_router.get("/{location_id}/events", summary="List events for a location", response_model=PaginatedResponse[EventRead], response_model_exclude_unset=True)
def get_location_events(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Event))],
    including: Annotated[dict, Depends(include_parameters(Event))],
    fielding: Annotated[dict, Depends(fields_parameters(Event))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_event_parameters)],
    location_id: int,
):
    """Retrieve a list of events associated with a specific location."""
    query = select(Event).where(Event.location_id == location_id)
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Event)
    items = filter_query(session, query, fielding, Event, including)
    return build_event_list_response(data, items, export)

@location_router.get("/{location_id}/building", summary="Get building details for a location", response_model=BuildingRead, response_model_exclude_unset=True)
def get_location_building(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Building))],
    including: Annotated[dict, Depends(include_parameters(Building))],
    fielding: Annotated[dict, Depends(fields_parameters(Building))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
    location_id: int,
):
    """Retrieve building details for a specific location."""
    query = select(Building).where(Building.locations.any(Location.id == location_id))  # type: ignore
    items = filter_query(session, query, fielding, Building, including)
    return items[0] if items else None

@location_router.get("/distinct/fields", summary="Get distinct values")
def get_location_distinct_field(
    session: SessionDep,
    field_name: Annotated[dict, Depends(distinct_parameters(Location))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
):
    """Retrieve distinct values for a specific field across all locations."""
    field = field_name.get("field")
    order = field_name.get("order")
    query = select(getattr(Location, field)).distinct()  # type: ignore
    if order:
        sort_column = getattr(Location, field)  # type: ignore
        query = query.order_by(sort_column.asc() if order.lower() == "asc" else sort_column.desc())
    data, query = page_query(session, query, paging)
    items = [{field: value} for value in session.exec(query).all()]
    return build_list_response(data, items, export)


room_router = APIRouter(prefix="/buildings", tags=["Buildings"])

@room_router.get("", summary="List all buildings", response_model=PaginatedResponse[BuildingRead], response_model_exclude_unset=True)
def get_buildings(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Building))],
    including: Annotated[dict, Depends(include_parameters(Building))],
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
    items = filter_query(session, query, fielding, Building, including)
    return build_list_response(data, items, export)

@room_router.get("/{building_id}", summary="Get building details", response_model=BuildingRead, response_model_exclude_unset=True)
def get_building_details(
    session: SessionDep,
    including: Annotated[dict, Depends(include_parameters(Building))],
    fielding: Annotated[dict, Depends(fields_parameters(Building))],
    export: Annotated[dict, Depends(export_parameters)],
    building_id: int,
):
    """Retrieve detailed information about a specific building by its ID."""
    get_or_404(session, Building, building_id, "Building")
    query = select(Building).where(Building.id == building_id)
    items = filter_query(session, query, fielding, Building, including)
    return items[0] if items else None

@room_router.get("/{building_id}/locations", summary="List locations for a building", response_model=PaginatedResponse[LocationRead], response_model_exclude_unset=True)
def get_building_locations(
    session: SessionDep,
    sorting: Annotated[dict, Depends(sort_parameters(Location))],
    including: Annotated[dict, Depends(include_parameters(Location))],
    fielding: Annotated[dict, Depends(fields_parameters(Location))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
    building_id: int,
):
    """Retrieve a list of locations associated with a specific building."""
    query = select(Location).where(Location.building_id == building_id)
    data, query = page_query(session, query, paging)
    query = sort_query(query, sorting, Location)
    items = filter_query(session, query, fielding, Location, including)
    return build_list_response(data, items, export)

@room_router.get("/distinct/fields", summary="Get distinct values")
def get_building_distinct_field(
    session: SessionDep,
    field_name: Annotated[dict, Depends(distinct_parameters(Building))],
    paging: Annotated[dict, Depends(paging_parameters)],
    export: Annotated[dict, Depends(export_parameters)],
):
    """Retrieve distinct values for a specific field across all buildings."""
    field = field_name.get("field")
    order = field_name.get("order")
    query = select(getattr(Building, field)).distinct()  # type: ignore
    if order:
        sort_column = getattr(Building, field)  # type: ignore
        query = query.order_by(sort_column.asc() if order.lower() == "asc" else sort_column.desc())
    data, query = page_query(session, query, paging)
    items = [{field: value} for value in session.exec(query).all()]
    return build_list_response(data, items, export)
