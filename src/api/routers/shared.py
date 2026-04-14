import csv
import io
from collections import defaultdict
from datetime import datetime, timedelta
from enum import Enum
from typing import cast

from fastapi import HTTPException, Query
from fastapi.responses import Response
from icalendar import Calendar, Event as ICalEvent, Alarm
from sqlmodel import Session, func, select

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

# TODO: Real implementation
def distinct_parameters(
    sort: str | None = Query(None, description="Sort order for the results. For example, 'asc' or 'desc'."),
    format: str | None = Query(None, description="Response format (e.g., 'json', 'csv')."),
):
    return {
        "sort": sort,
        "format": format,
    }

def get_or_404(session: Session, model_class: type, id: int, label: str = "Resource"):
    item = session.get(model_class, id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return item

def build_list_response(data: dict, items: list[dict], export: dict):
    fmt = export.get("format")
    if fmt is not None and fmt.value == "csv":
        if not items:
            return Response(
                content="", media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=export.csv"},
            )
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=items[0].keys())
        writer.writeheader()
        writer.writerows(items)
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=export.csv"},
        )
    return {
        "count": data["count"],
        "page": data["page"],
        "limit": data["limit"],
        "total_pages": data["total_pages"],
        "items": items,
    }

def build_event_list_response(data: dict, items: list[dict], export: dict):
    fmt = export.get("format")
    if fmt is not None and fmt.value == "ical":
        title_format = export.get("ical_title_format") or "{name}"
        location_format = export.get("ical_location_format")
        description_format = export.get("ical_description_format")
        reminder_minutes = export.get("ical_reminder_minutes")

        cal = Calendar()
        cal.add("prodid", "-//Almaweb Parser//EN")
        cal.add("version", "2.0")

        for item in items:
            safe_item = defaultdict(str, {k: (v if v is not None else "") for k, v in item.items()})

            ical_event = ICalEvent()
            ical_event.add("uid", f"event-{item.get('id', 'unknown')}@almaweb-parser")
            ical_event.add("summary", title_format.format_map(safe_item))

            event_date = item.get("event_date")
            start_time = item.get("start_time")
            end_time = item.get("end_time")
            if event_date and start_time:
                ical_event.add("dtstart", datetime.combine(event_date, start_time))
            if event_date and end_time:
                ical_event.add("dtend", datetime.combine(event_date, end_time))

            if location_format:
                ical_event.add("location", location_format.format_map(safe_item))
            elif item.get("location"):
                ical_event.add("location", str(item["location"]))

            if description_format:
                ical_event.add("description", description_format.format_map(safe_item))

            if reminder_minutes is not None:
                alarm = Alarm()
                alarm.add("action", "DISPLAY")
                alarm.add("trigger", timedelta(minutes=-reminder_minutes))
                alarm.add("description", "Event reminder")
                ical_event.add_component(alarm)

            cal.add_component(ical_event)

        return Response(
            content=cal.to_ical(),
            media_type="text/calendar",
            headers={"Content-Disposition": "attachment; filename=events.ics"},
        )
    return build_list_response(data, items, export)