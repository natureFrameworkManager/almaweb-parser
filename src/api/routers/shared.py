from enum import Enum
from typing import cast
from fastapi import Query
from sqlmodel import func, select
from database.database import SessionDep

class ExportFormats(str, Enum):
    json = "json"
    csv = "csv"

class EventExportFormats(str, Enum):
    json = "json"
    csv = "csv"
    ical = "ical"

def model_field_enum(model_class: type, enum_name: str | None = None) -> type[Enum]:
    """
    Build a string Enum from a SQLModel class fields for use in query parameters.

    This allows FastAPI docs to present the model columns as selectable enum values.
    """
    name = enum_name or f"{model_class.__name__}Field"
    return cast(type[Enum], Enum(name, {field: field for field in model_class.model_fields}, type=str))


class SortOrder(str, Enum):
    asc = "asc"
    desc = "desc"


def sort_parameters(model_class: type):
    """
    Build a FastAPI dependency for generic model sorting.

    Returns a dependency function with:
    - sort: enum of model columns
    - order: asc | desc
    """
    SortField = model_field_enum(model_class, f"{model_class.__name__}SortField")
    sort_values = [str(field.value) for field in SortField.__members__.values()]

    def _sort_parameters(
        sort: str | None = Query(None, description="Column to sort by.", enum=sort_values),
        order: SortOrder = Query(SortOrder.asc, description="Sort direction: asc or desc."),
    ):
        return {
            "sort": sort,
            "order": order.value,
        }

    return _sort_parameters

def fields_parameters(model_class: type):
    """
    Build a FastAPI dependency for generic field selection.

    Returns a dependency function with:
    - fields: list of model columns to include in the response
    """
    FieldEnum = model_field_enum(model_class, f"{model_class.__name__}Field")

    def _fields_parameters(
        fields: list[FieldEnum] | None = Query(None, description="Comma-separated list of fields to include in the response. If not provided, all fields will be included."), # type: ignore
    ):
        return {
            "fields": fields,
        }

    return _fields_parameters

def export_parameters(
    format: ExportFormats | None = Query(None, description="Response format."),
):
    return {
        "format": format,
        }

def export_event_parameters(
    format: EventExportFormats | None = Query(None, description="Response format."),
    ical_title_format: str | None = Query(None, description="Custom title format for iCal output, using placeholders like {name} and {number}. Ignored if format is not 'ical'."),
    ical_location_format: str | None = Query(None, description="Custom location format for iCal output, using placeholders like {name} and {number}. Ignored if format is not 'ical'."),
    ical_description_format: str | None = Query(None, description="Custom description format for iCal output, using placeholders like {name} and {number}. Ignored if format is not 'ical'."),
    ical_reminder_minutes: int | None = Query(None, description="Number of minutes before the event to set an iCal reminder. Ignored if format is not 'ical'."),
):
        
    return {
        "format": format,
        "ical_title_format": ical_title_format,
        "ical_location_format": ical_location_format,
        "ical_description_format": ical_description_format,
        "ical_reminder_minutes": ical_reminder_minutes,
        }

def paging_parameters(
    page: int | None = Query(None, ge=1, description="Page number (starts at 1). If omitted together with limit, pagination is disabled."),
    page_size: int | None = Query(None, ge=1, description="Number of modules returned per page. If omitted together with page, pagination is disabled."),
):
    return {
        "page": page,
        "page_size": page_size,
    }

def page_query(session: SessionDep, query, paging: dict):
    page = paging.get("page") or 1
    page_size = paging.get("page_size")
    
    count = session.exec(select(func.count()).select_from(query.subquery())).one()
    if page_size is not None:
        offset = (page - 1) * page_size
        return {
            "count": count,
            "page": page,
            "limit": page_size,
            "total_pages": (count + page_size - 1) // page_size,
        }, query.offset(offset).limit(page_size)
    else:
        return {
        "count": count,
        "page": 1,
        "limit": count,
        "total_pages": 1,
        }, query
    
def filter_query(session: SessionDep, query, filtering: dict, model_class: type):
    # Verify that filtering keys are valid model fields
    valid_fields = set(model_class.model_fields.keys())
    for key in filtering["fields"] or []:
        if key not in valid_fields:
            raise ValueError(f"Invalid filter field: {key}. Valid fields are: {', '.join(valid_fields)}")

    # Get unfiltered items to apply field selection
    unfiltered_items = session.exec(query).all()
    # Fallback
    selected_fields = sorted(filtering["fields"] or valid_fields)
    # Apply filters to the query and return only the selected fields
    items = [
        {
            field: module.model_dump().get(field)
            for field in selected_fields
        }
        for module in unfiltered_items
    ]
    return items

def sort_query(query, sorting: dict, model_class: type):
    """Apply sorting to the query based on the provided sorting parameters."""
    sort_field = sorting.get("sort")
    if sort_field:
        sort_column = getattr(model_class, sort_field, None)
        if sort_column is not None:
            if sorting.get("order") == "desc":
                return query.order_by(sort_column.desc())
            else:
                return query.order_by(sort_column.asc())
    return query