from enum import Enum
from typing import Annotated
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