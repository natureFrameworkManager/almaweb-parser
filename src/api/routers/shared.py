import csv
import io
import json
import re
from collections import defaultdict
from datetime import date as date_type, datetime, timedelta
from enum import Enum
from typing import Annotated, Any, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, Query, Request
from fastapi.responses import Response
from icalendar import Calendar, Event as ICalEvent, Alarm, Timezone, TimezoneStandard, TimezoneDaylight
from sqlalchemy.orm import selectinload
from sqlalchemy import inspect as sa_inspect
from sqlmodel import Session, func, select

from database.database import SessionDep
from schemas import Problem

# Reusable OpenAPI response definitions for RFC 9457 Problem Details.
# Include this in every APIRouter to document error responses uniformly.
PROBLEM_RESPONSES: dict = {
    400: {"model": Problem, "description": "Bad Request"},
    404: {"model": Problem, "description": "Not Found"},
    409: {"model": Problem, "description": "Conflict"},
    422: {"model": Problem, "description": "Unprocessable Content"},
}


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ExportFormats(str, Enum):
    json = "json"
    csv = "csv"

class EventExportFormats(str, Enum):
    json = "json"
    csv = "csv"
    ical = "ical"

class SortOrder(str, Enum):
    asc = "asc"
    desc = "desc"

class ICalTemplate(str, Enum):
    compact = "compact"
    detailed = "detailed"
    minimal = "minimal"
    custom = "custom"

class ICalBusyStatus(str, Enum):
    busy = "BUSY"
    free = "FREE"
    busy_tentative = "BUSY-TENTATIVE"
    busy_unavailable = "BUSY-UNAVAILABLE"


# ---------------------------------------------------------------------------
# Model introspection helpers
#
# These functions inspect SQLModel / SQLAlchemy metadata to discover columns,
# relationships, and foreign-key-derived "virtual" relations at runtime.
# ---------------------------------------------------------------------------

def _table_to_model_map(model_class: type) -> dict[str, type]:
    """Map DB table names -> mapped model classes for the whole registry."""
    return {
        m.local_table.name: m.class_
        for m in sa_inspect(model_class).registry.mappers
        if getattr(m.class_, "__table__", None) is not None
    }

def _model_column_fields(model_class: type) -> list[str]:
    """Return DB column key names for *model_class*."""
    return [c.key for c in sa_inspect(model_class).columns]

def model_field_enum(model_class: type, enum_name: str | None = None) -> type[Enum]:
    """Build a string Enum whose members are the model's field names (for FastAPI query docs)."""
    name = enum_name or f"{model_class.__name__}Field"
    return cast(type[Enum], Enum(name, {f: f for f in model_class.model_fields}, type=str))

def _dot_paths_enum(enum_name: str, values: list[str]) -> type[Enum]:
    """Build a string Enum from dot-notation paths (e.g. ``"course.faculty"``)."""
    members: dict[str, str] = {}
    for value in values:
        # Convert "course.faculty" -> "COURSE_FACULTY"
        base = re.sub(r"[^a-zA-Z0-9]", "_", value).upper()
        if not base:
            continue
        if base[0].isdigit():
            base = f"V_{base}"

        # Handle name collisions by appending a numeric suffix
        name, suffix = base, 2
        while name in members and members[name] != value:
            name = f"{base}_{suffix}"
            suffix += 1
        members[name] = value

    return cast(type[Enum], Enum(enum_name, members, type=str))


# ---------------------------------------------------------------------------
# Relation discovery
#
# Two sources of relations are considered for every model:
#   1. Explicit SQLAlchemy Relationship() fields.
#   2. Foreign-key columns (e.g. faculty_id) that point at another table but
#      have no corresponding Relationship – these are called "FK-only" or
#      "virtual" relations throughout this module.
# ---------------------------------------------------------------------------

def _model_relation_targets(model_class: type) -> list[tuple[str, type]]:
    """Return ``[(relation_name, target_model), ...]`` for *model_class*.

    Combines explicit relationships **and** FK-only virtual relations,
    deduplicating by relation name.
    """
    mapper = sa_inspect(model_class)
    tbl_map = _table_to_model_map(model_class)
    targets: list[tuple[str, type]] = []
    seen: set[str] = set()

    # 1) Explicit relationships declared on the model
    for rel in mapper.relationships.values():
        if rel.key not in seen:
            seen.add(rel.key)
            targets.append((rel.key, rel.entity.class_))

    # 2) FK columns whose target table has no explicit relationship yet
    for col in mapper.columns:
        for fk in col.foreign_keys:
            name = col.key[:-3] if col.key.endswith("_id") else col.key
            target = tbl_map.get(fk.column.table.name)
            if target and name not in seen:
                seen.add(name)
                targets.append((name, target))

    return targets


def _fk_relation_target(model_class: type, relation_name: str) -> tuple[type, str] | None:
    """Look up a FK-only relation by name -> ``(target_model, fk_column_key)`` or ``None``."""
    mapper = sa_inspect(model_class)
    tbl_map = _table_to_model_map(model_class)

    for col in mapper.columns:
        for fk in col.foreign_keys:
            candidate = col.key[:-3] if col.key.endswith("_id") else col.key
            if candidate != relation_name:
                continue
            if target := tbl_map.get(fk.column.table.name):
                return target, col.key
    return None


# ---------------------------------------------------------------------------
# Include tree
#
# An "include tree" is a nested structure that describes all reachable
# relations from a root model.  Example for a Course model:
#
#   {"Course": ["faculty", {"events": ["location"]}, "semester"]}
#
# Leaf strings are simple relations; dicts represent relations with their
# own sub-relations.  Cycles are broken per branch using an ancestor set.
# ---------------------------------------------------------------------------

def model_include_tree(model_class: type) -> dict[str, list[Any]]:
    """Build the full nested include tree rooted at *model_class*."""

    def _build(model: type, ancestors: set[type]) -> list[Any]:
        branch: list[Any] = []
        next_ancestors = ancestors | {model}
        for name, target in _model_relation_targets(model):
            if target in ancestors:
                continue  # break cycle
            subtree = _build(target, next_ancestors)
            branch.append({name: subtree} if subtree else name)
        return branch

    return {model_class.__name__: _build(model_class, set())}


def _flatten_include_tree(include_tree: dict[str, list[Any]]) -> list[str]:
    """Flatten a nested include tree into order-stable, deduplicated dot-paths."""
    paths: list[str] = []

    def _walk(nodes: list[Any], prefix: str = ""):
        for node in nodes:
            if isinstance(node, str):
                paths.append(f"{prefix}.{node}" if prefix else node)
            elif isinstance(node, dict):
                for name, children in node.items():
                    path = f"{prefix}.{name}" if prefix else name
                    paths.append(path)
                    if isinstance(children, list):
                        _walk(children, path)

    _walk(next(iter(include_tree.values()), []))
    return list(dict.fromkeys(paths))  # deduplicate, keep insertion order


# ---------------------------------------------------------------------------
# Dot-path field / relation utilities
#
# Many features (field selection, relation eager-loading, projection) work
# with dot-separated paths like "events.location.name".  The helpers below
# resolve, validate, and walk those paths.
# ---------------------------------------------------------------------------

def _related_field_paths(model_class: type) -> list[str]:
    """Build all reachable dot-paths: ``relation``, ``relation.field``, deeply nested."""
    paths: list[str] = []

    def _walk(model: type, prefix: str = "", ancestors: set[type] | None = None):
        anc = ancestors or set()
        next_anc = anc | {model}
        for rel_name, target in _model_relation_targets(model):
            if target in anc:
                continue
            rel_path = f"{prefix}.{rel_name}" if prefix else rel_name
            paths.append(rel_path)
            # Append each scalar field of the related model
            paths.extend(f"{rel_path}.{f}" for f in target.model_fields)
            _walk(target, rel_path, next_anc)

    _walk(model_class)
    return list(dict.fromkeys(paths))


def _resolve_dot_path_value(obj: Any, path: str) -> Any:
    """Walk *obj* (SQLModel / dict / list) along a dot-path and return the leaf value."""
    current = obj
    for i, part in enumerate(path.split(".")):
        if current is None:
            return None
        # Lists: fan out the remaining path across every element
        if isinstance(current, list):
            remaining = ".".join(path.split(".")[i:])
            return [_resolve_dot_path_value(item, remaining) for item in current]
        # Dicts vs model attribute access
        current = current.get(part) if isinstance(current, dict) else getattr(current, part, None)
    return current


def _relation_chain_from_path(model_class: type, path: str) -> list[str]:
    """Extract the leading relation-name segments from a dot-path.

    Stops at the first token that is neither an explicit relationship nor
    a FK-only relation (i.e. it's a scalar field).
    """
    chain: list[str] = []
    model = model_class
    for token in path.split("."):
        rels = sa_inspect(model).relationships
        if token in rels:
            chain.append(token)
            model = rels[token].entity.class_
        elif (fk := _fk_relation_target(model, token)):
            chain.append(token)
            model = fk[0]
        else:
            break  # reached a scalar field
    return chain


def _relation_chains(model_class: type, include_paths: list[str], field_paths: list[str]) -> list[list[str]]:
    """Collect unique relation chains needed for eager loading."""
    seen: set[tuple[str, ...]] = set()
    chains: list[list[str]] = []
    for path in include_paths + field_paths:
        if (chain := _relation_chain_from_path(model_class, path)):
            key = tuple(chain)
            if key not in seen:
                seen.add(key)
                chains.append(chain)
    return chains


# ---------------------------------------------------------------------------
# Query manipulation: eager-loading, projection, serialization
#
# The overall flow for a list endpoint is:
#   1. _relation_chains()            – figure out which relations are needed
#   2. _query_with_relation_loads()  – attach selectinload() to the query
#   3. _projection_for_response()    – build a tree describing which fields
#                                      and sub-relations to include in JSON
#   4. _serialize_with_projection()  – walk each row and emit a plain dict
# ---------------------------------------------------------------------------

def _query_with_relation_loads(query, model_class: type, chains: list[list[str]]):
    """Attach ``selectinload`` options for every chain of explicit relationships.

    FK-only relations (no Relationship() field) are skipped – they are
    resolved lazily in ``_relation_value`` instead.
    """
    options = []
    for chain in chains:
        model, loader, valid = model_class, None, True
        for name in chain:
            rels = sa_inspect(model).relationships
            if name not in rels:
                valid = False  # FK-only – cannot eager-load
                break
            attr = getattr(model, name)
            loader = selectinload(attr) if loader is None else loader.selectinload(attr)
            model = rels[name].entity.class_
        if valid and loader:
            options.append(loader)

    return query.options(*options) if options else query


def _new_projection_node() -> dict[str, Any]:
    """Empty projection node: no fields selected, no sub-relations."""
    return {"__all__": False, "__fields__": set(), "__relations__": {}}


def _projection_for_response(
    model_class: type,
    selected_fields: list[str] | None,
    include_paths: list[str],
) -> dict[str, Any]:
    """Build a projection tree that controls which fields/relations appear in the JSON output.

    * When *selected_fields* is given, only those exact paths are emitted.
    * Otherwise all own columns are emitted, plus any relations from *include_paths*
      (each expanded with all their columns).
    """
    projection = _new_projection_node()

    def _ensure(node: dict[str, Any], name: str) -> dict[str, Any]:
        """Get or create a child relation node."""
        rels = node["__relations__"]
        if name not in rels:
            rels[name] = _new_projection_node()
        return rels[name]

    def _walk_token(token: str, model: type, node: dict[str, Any], is_last: bool) -> tuple[type, dict[str, Any]] | None:
        """Advance one token; returns (next_model, next_node) or None if it's a leaf field."""
        rels = sa_inspect(model).relationships
        fk = _fk_relation_target(model, token)

        # Token is a relationship (explicit or FK-only)
        if token in rels:
            child = _ensure(node, token)
            if is_last:
                child["__all__"] = True
            return rels[token].entity.class_, child
        if fk:
            child = _ensure(node, token)
            if is_last:
                child["__all__"] = True
            return fk[0], child

        # Token is a scalar field
        if is_last:
            node["__fields__"].add(token)
        return None

    if selected_fields:
        # Explicit field selection: only emit the requested paths
        for path in selected_fields:
            tokens = path.split(".")
            model, node = model_class, projection
            for idx, token in enumerate(tokens):
                result = _walk_token(token, model, node, idx == len(tokens) - 1)
                if result is None:
                    break
                model, node = result
    else:
        # No field selection: emit all own columns + requested includes with all their columns
        projection["__all__"] = True
        for inc_path in include_paths:
            model, node = model_class, projection
            for token in inc_path.split("."):
                result = _walk_token(token, model, node, is_last=True)
                if result is None:
                    break
                model, node = result

    return projection


def _relation_value(
    session: SessionDep, item: Any, model_class: type, relation_name: str,
) -> tuple[Any, type | None, bool]:
    """Load a single relation value from *item*.

    Returns ``(value, target_model, is_many)``.
    For FK-only relations the target row is fetched via ``session.get()``.
    """
    rels = sa_inspect(model_class).relationships

    # Explicit relationship – already loaded (eager or lazy)
    if relation_name in rels:
        rel = rels[relation_name]
        return getattr(item, relation_name, None), rel.entity.class_, bool(rel.uselist)

    # FK-only: look up the target row by its primary key
    if fk := _fk_relation_target(model_class, relation_name):
        target_model, fk_col = fk
        target_id = getattr(item, fk_col, None)
        value = session.get(target_model, target_id) if target_id is not None else None
        return value, target_model, False

    return None, None, False


def _serialize_with_projection(
    session: SessionDep, item: Any, model_class: type, projection: dict[str, Any],
) -> dict[str, Any]:
    """Serialize one SQLModel row into a plain dict according to *projection*."""
    # Select field names: all DB columns or only the explicitly requested ones
    fields = _model_column_fields(model_class) if projection["__all__"] else sorted(projection["__fields__"])
    result = {f: getattr(item, f, None) for f in fields}

    # Recursively serialize each requested sub-relation
    for rel_name, rel_proj in projection["__relations__"].items():
        value, target, is_many = _relation_value(session, item, model_class, rel_name)
        if target is None:
            continue
        if is_many:
            result[rel_name] = [
                _serialize_with_projection(session, child, target, rel_proj)
                for child in (value or [])
            ]
        else:
            result[rel_name] = (
                _serialize_with_projection(session, value, target, rel_proj) if value is not None else None
            )

    return result


# ---------------------------------------------------------------------------
# FastAPI dependency factories
#
# Each ``*_parameters`` function returns a FastAPI ``Depends()``-compatible
# callable that injects parsed query parameters as a dict.
# ---------------------------------------------------------------------------

def sort_parameters(model_class: type):
    """Dependency: ``?sort=<column>&order=asc|desc``."""
    SortField = model_field_enum(model_class, f"{model_class.__name__}SortField")
    sort_values = [str(f.value) for f in SortField.__members__.values()]

    def _dep(
        sort: str | None = Query(None, description="Column to sort by.", enum=sort_values),
        order: SortOrder = Query(SortOrder.asc, description="Sort direction: asc or desc."),
    ):
        return {"sort": sort, "order": order.value}

    return _dep


def fields_parameters(model_class: type):
    """Dependency: ``?fields=id&fields=name&fields=course.title`` (repeatable)."""
    all_fields = list(dict.fromkeys(list(model_class.model_fields) + _related_field_paths(model_class)))
    FieldEnum = _dot_paths_enum(f"{model_class.__name__}Field", all_fields)

    def _dep(
        fields: list[FieldEnum] | None = Query(None, description="Fields to include in the response. If omitted, all fields are returned."),  # type: ignore
    ):
        return {"fields": [str(v.value) for v in fields] if fields else None}

    return _dep


def include_parameters(model_class: type):
    """Dependency: ``?include=events&include=faculty`` (repeatable).

    Auto-discovers relations from the model; *virtual_includes* adds extra
    names that are handled by custom router logic.
    """
    include_values = _flatten_include_tree(model_include_tree(model_class))

    IncludeEnum = _dot_paths_enum(f"{model_class.__name__}IncludeField", include_values)

    def _dep(
        include: list[IncludeEnum] | None = Query(None, description="Related data to include. Repeatable."),  # type: ignore
    ):
        return {"include": [str(v.value) for v in include] if include else None}

    return _dep


def export_parameters(
    format: ExportFormats | None = Query(None, description="Response format."),
):
    return {"format": format}


def export_event_parameters(
    request: Request,
    format: EventExportFormats | None = Query(None, description="Response format."),
    ical_title_format: str | None = Query(None, description="iCal SUMMARY template. Supports placeholders: {name}, {number}, {course_name}, {module_name}, {staff_names}, {location_name}, {building_name}, {course_number}, {module_number}, {course_type}. Overrides auto-title when set."),
    ical_location_format: str | None = Query(None, description="iCal LOCATION template. Same placeholders as ical_title_format."),
    ical_description_format: str | None = Query(None, description="iCal DESCRIPTION template. Same placeholders as ical_title_format."),
    ical_reminder_minutes: list[int] | None = Query(None, ge=0, le=10080, description="Minutes before event for VALARM reminders. Repeatable for multiple reminders (e.g. ?ical_reminder_minutes=15&ical_reminder_minutes=60). Must be 0–10080 (1 week)."),
    ical_organizer: str | None = Query(None, description="ORGANIZER property value, e.g. 'MAILTO:registrar@uni-example.de'."),
    ical_categories: str | None = Query(None, description="CATEGORIES value. Supports placeholders. E.g. 'University,{course_type}'."),
    ical_filename: str = Query("events.ics", description="Filename for the Content-Disposition header."),
    ical_calendar_name: str | None = Query(None, description="X-WR-CALNAME: calendar display name in calendar apps."),
    ical_timezone: str = Query("Europe/Berlin", description="TZID for event datetimes, e.g. 'Europe/Berlin' or 'America/New_York'."),
    ical_template: ICalTemplate | None = Query(None, description="Named preset that sets title/description/location formats at once. compact={course_name}; detailed={module_name} – {course_name} with description; minimal={name}; custom=use individual ical_*_format params."),
    ical_color: str | None = Query(None, description="COLOR property (RFC 7986) for event tinting, e.g. '#3B82F6' or 'tomato'. Supported by Apple Calendar and Thunderbird."),
    ical_busy_status: ICalBusyStatus | None = Query(None, description="TRANSP property: FREE → TRANSPARENT, others → OPAQUE. Controls free/busy visibility in Outlook/Google Calendar."),
    ical_collapse_recurring: bool = Query(False, description="Collapse weekly-recurring events into a single VEVENT with RRULE:FREQ=WEEKLY. Requires courses to be included."),
    ical_map: str | None = Query(None, description="JSON object mapping event IDs to module/course IDs for per-event title override. E.g. '{\"42\":7,\"43\":7}'. See ical_map_type."),
    ical_map_type: str | None = Query("module", description="Whether ical_map values are module IDs ('module') or course IDs ('course').", enum=["module", "course"]),
    ical_multi_value_separator: str = Query(" / ", description="Separator used when joining multiple course/module names in placeholders."),
):
    # Validate timezone
    tz_str = ical_timezone or "Europe/Berlin"
    try:
        ZoneInfo(tz_str)
    except (ZoneInfoNotFoundError, KeyError):
        raise HTTPException(status_code=422, detail=f"Unknown timezone: '{tz_str}'. Use a valid IANA timezone name.")

    # Fix 11: parse ical_event_title[{id}] bracket params from raw query string
    per_event_titles: dict[int, str] = {}
    for key, val in request.query_params.items():
        m = re.match(r"^ical_event_title\[(\d+)\]$", key)
        if m:
            per_event_titles[int(m.group(1))] = val

    return {
        "format": format,
        "ical_title_format": ical_title_format,
        "ical_location_format": ical_location_format,
        "ical_description_format": ical_description_format,
        "ical_reminder_minutes": ical_reminder_minutes,
        "ical_organizer": ical_organizer,
        "ical_categories": ical_categories,
        "ical_filename": ical_filename,
        "ical_calendar_name": ical_calendar_name,
        "ical_timezone": tz_str,
        "ical_template": ical_template,
        "ical_color": ical_color,
        "ical_busy_status": ical_busy_status,
        "ical_collapse_recurring": ical_collapse_recurring,
        "ical_map": ical_map,
        "ical_map_type": ical_map_type or "module",
        "ical_multi_value_separator": ical_multi_value_separator,
        "ical_event_titles_map": per_event_titles,
    }


def paging_parameters(
    page: int | None = Query(None, ge=1, description="Page number (starts at 1). If omitted together with limit, pagination is disabled."),
    page_size: int | None = Query(None, ge=1, description="Items per page. If omitted together with page, pagination is disabled."),
):
    return {"page": page, "page_size": page_size}


def distinct_parameters(
    model_class: type,
):
    DistinctField = model_field_enum(model_class, f"{model_class.__name__}DistinctField")
    field_values = [str(f.value) for f in DistinctField.__members__.values()]

    def _dep(
        field: str = Query(..., description="Column name.", enum=field_values),
        order: SortOrder = Query(SortOrder.asc, description="Sort direction: asc or desc."),
    ):
        return {"field": field, "order": order.value}

    return _dep


# ---------------------------------------------------------------------------
# Query helpers – paging, sorting, filtering, single-item lookup
# ---------------------------------------------------------------------------

def page_query(session: SessionDep, query, paging: dict):
    """Apply pagination to *query* and return ``(meta_dict, paginated_query)``."""
    page = paging.get("page") or 1
    page_size = paging.get("page_size")
    count = session.exec(select(func.count()).select_from(query.subquery())).one()

    if page_size is not None:
        offset = (page - 1) * page_size
        meta = {"count": count, "page": page, "limit": page_size, "total_pages": (count + page_size - 1) // page_size}
        return meta, query.offset(offset).limit(page_size)

    return {"count": count, "page": 1, "limit": count, "total_pages": 1}, query


def sort_query(query, sorting: dict, model_class: type):
    """Apply ``ORDER BY`` to *query* from the sorting parameter dict."""
    if (field := sorting.get("sort")) and (col := getattr(model_class, field, None)):
        return query.order_by(col.desc() if sorting.get("order") == "desc" else col.asc())
    return query


def filter_query(session: SessionDep, query, filtering: dict, model_class: type, including: dict | None = None):
    """Apply field selection + relation includes, then execute and serialize the query.

    Steps:
      1. Validate requested fields against the model schema.
      2. Eager-load the needed relation chains on the query (``selectinload``).
      3. Execute the query.
      4. Serialize each row through the projection tree.
    """
    include_values = (including.get("include") if including else None) or []
    selected_fields = filtering.get("fields")

    # Validate field names
    valid_fields = set(model_class.model_fields) | set(_related_field_paths(model_class))
    for key in filtering["fields"] or []:
        if key not in valid_fields:
            raise ValueError(f"Invalid filter field: {key}. Valid fields are: {', '.join(valid_fields)}")

    # Eager-load relations, execute, and project
    chains = _relation_chains(model_class, include_values, selected_fields or [])
    query = _query_with_relation_loads(query, model_class, chains)
    rows = session.exec(query).all()

    projection = _projection_for_response(model_class, selected_fields, include_values)
    return [_serialize_with_projection(session, row, model_class, projection) for row in rows]


def get_or_404(session: Session, model_class: type, id: int, label: str = "Resource"):
    """Fetch a single row by PK or raise 404."""
    if (item := session.get(model_class, id)) is None:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return item


def _ical_augment_including(including: dict, export: dict) -> dict:
    """When format=ical, auto-include courses, modules, staff and location so placeholders work."""
    fmt = export.get("format")
    if fmt is None or fmt.value != "ical":
        return including
    force = ["courses", "courses.modules", "courses.staff", "location", "location.building"]
    current = list(including.get("include") or [])
    augmented = current + [p for p in force if p not in current]
    return {**including, "include": augmented}


def _build_event_placeholders(item: dict, separator: str) -> defaultdict:
    """Build expanded iCal placeholder dict from a serialized event item.

    Populates direct scalar fields plus derived keys:
      {course_name}, {course_number}, {course_type},
      {module_name}, {module_number},
      {staff_names}, {location_name}, {building_name}

    Fix 12: if event.number starts with a course.number, that course is put first
    (overriding id-sorted order) so singular placeholders reflect the owning course.
    Fix 9/6: all names joined with *separator* for multi-value placeholders.
    """
    safe: defaultdict = defaultdict(str)
    for k, v in item.items():
        if not isinstance(v, (dict, list)):
            safe[k] = str(v) if v is not None else ""

    courses: list[dict] = sorted(item.get("courses") or [], key=lambda c: c.get("id") or 0)

    # Fix 12: prefer course whose number is a non-empty prefix of event.number
    event_number: str = item.get("number") or ""
    preferred_course: dict | None = None
    if event_number:
        for c in courses:
            cn = c.get("number") or ""
            if cn and event_number.startswith(cn):
                preferred_course = c
                break
    if preferred_course is not None:
        # Reorder: preferred first, rest id-sorted
        courses = [preferred_course] + [c for c in courses if c.get("id") != preferred_course.get("id")]

    # Course placeholders (Fix 9/6 join, Fix 12 ordering)
    safe["course_name"] = separator.join(c.get("name") or "" for c in courses if c.get("name"))
    if courses:
        safe["course_number"] = courses[0].get("number") or ""
        safe["course_type"] = str(courses[0].get("type") or "")

    # Module placeholders: collect from all courses in order, deduped by id.
    # Fix 12 module level: within the preferred course, prefer the module whose
    # number is a non-empty prefix of that course's number.
    preferred_module: dict | None = None
    if preferred_course is not None:
        pc_number: str = preferred_course.get("number") or ""
        if pc_number:
            for m in sorted(preferred_course.get("modules") or [], key=lambda m: m.get("id") or 0):
                mn = m.get("number") or ""
                if mn and pc_number.startswith(mn):
                    preferred_module = m
                    break
    all_modules: list[dict] = []
    seen_module_ids: set = set()
    for c in courses:
        mods = sorted(c.get("modules") or [], key=lambda m: m.get("id") or 0)
        if preferred_module is not None and c.get("id") == (preferred_course or {}).get("id"):
            mods = [preferred_module] + [m for m in mods if m.get("id") != preferred_module.get("id")]
        for m in mods:
            mid = m.get("id")
            if mid not in seen_module_ids:
                seen_module_ids.add(mid)
                all_modules.append(m)
    safe["module_name"] = separator.join(m.get("name") or "" for m in all_modules if m.get("name"))
    if all_modules:
        safe["module_number"] = all_modules[0].get("number") or ""

    # Staff names: event-level staff first, fall back to preferred course staff
    staff_list: list[dict] = item.get("staff") or []
    if not staff_list and courses:
        staff_list = courses[0].get("staff") or []
    safe["staff_names"] = ", ".join(s.get("name") or "" for s in staff_list if s.get("name"))

    # Location
    loc = item.get("location")
    if isinstance(loc, dict):
        safe["location_name"] = loc.get("name") or ""
        building = loc.get("building")
        if isinstance(building, dict):
            safe["building_name"] = building.get("name") or ""

    return safe


def _resolve_event_title(
    item: dict,
    export: dict,
    placeholders: defaultdict,
    ical_map_names: dict[int, str],
) -> str:
    """6-layer title resolution (highest-priority first).

    1. Fix 11 – per-event inline ``ical_event_title[id]`` query param
    2. Fix 8  – ``ical_map`` bulk-resolved module/course name
    3.          ``ical_title_format`` user template with expanded placeholders
    4. Fix 4  – filter-derived context (``_filter_module_name`` / ``_filter_course_name``)
    5. Fix 9/6– joined module names → joined course names
    6.          ``event.name`` → ``"Event #{id}"``
    """
    event_id: int | None = item.get("id")

    # Layer 1: Fix 11
    per_event_map: dict = export.get("ical_event_titles_map") or {}
    if event_id is not None and event_id in per_event_map:
        return per_event_map[event_id]

    # Layer 2: Fix 8
    if event_id is not None and event_id in ical_map_names:
        return ical_map_names[event_id]

    # Layer 3: user-provided title template
    title_fmt: str | None = export.get("ical_title_format")
    if title_fmt:
        return title_fmt.format_map(placeholders)

    # Layer 4: Fix 4 – filter-derived context
    filter_module = export.get("_filter_module_name") or ""
    filter_course = export.get("_filter_course_name") or ""
    context_name = filter_module or filter_course
    if context_name:
        event_name = item.get("name") or ""
        return f"{context_name} – {event_name}" if event_name else context_name

    # Layer 5: Fix 9/6 joined names
    module_names: str = placeholders["module_name"]
    if module_names:
        return module_names
    course_names: str = placeholders["course_name"]
    if course_names:
        return course_names

    # Layer 6: fallback
    name: str = item.get("name") or ""
    return name if name else f"Event #{event_id or 'unknown'}"


def _collapse_recurring_to_rrule(items: list[dict]) -> list[list[dict]]:
    """Group items into recurring sets for RRULE collapsing.

    Returns a list of groups. Each group is a list of event dicts that share
    the same (course_ids, weekday, start_time, end_time, location_id) signature
    and occur at strictly weekly intervals.  Groups whose inter-event gaps are
    not exactly 7 days are left as individual single-item groups.
    """
    def _sig(item: dict) -> tuple:
        course_ids = frozenset(c.get("id") for c in (item.get("courses") or []))
        d: date_type | None = item.get("event_date")
        weekday = d.isoweekday() if d else None
        return (course_ids, weekday, item.get("start_time"), item.get("end_time"), item.get("location_id"))

    buckets: dict[tuple, list[dict]] = {}
    for item in items:
        sig = _sig(item)
        buckets.setdefault(sig, []).append(item)

    result: list[list[dict]] = []
    for group in buckets.values():
        if len(group) == 1:
            result.append(group)
            continue
        group_sorted = sorted(group, key=lambda x: x.get("event_date") or date_type.min)
        # Accept groups where all inter-event gaps are multiples of 7 days.
        # Gaps exactly 7 days → no EXDATEs; larger multiples (e.g. a skipped
        # holiday week) produce EXDATE entries in the VEVENT.
        all_weekly_multiples = all(
            (group_sorted[i + 1]["event_date"] - group_sorted[i]["event_date"]).days % 7 == 0
            for i in range(len(group_sorted) - 1)
        )
        if all_weekly_multiples:
            result.append(group_sorted)
        else:
            # Emit each occurrence individually
            result.extend([[item] for item in group_sorted])
    return result


# ---------------------------------------------------------------------------
# Response builders – JSON / CSV / iCal
# ---------------------------------------------------------------------------

def build_list_response(data: dict, items: list[dict], export: dict):
    """Wrap *items* in a paged JSON envelope, or export as CSV if requested."""
    fmt = export.get("format")

    # CSV export
    if fmt is not None and fmt.value == "csv":
        if not items:
            return Response(content="", media_type="text/csv",
                            headers={"Content-Disposition": "attachment; filename=export.csv"})
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=items[0].keys())
        writer.writeheader()
        for item in items:
            writer.writerow({k: json.dumps(v, default=str) if isinstance(v, (dict, list)) else v for k, v in item.items()})
        return Response(content=buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": "attachment; filename=export.csv"})

    # Default: JSON envelope
    return {**{k: data[k] for k in ("count", "page", "limit", "total_pages")}, "items": items}


def build_event_list_response(session: Session, data: dict, items: list[dict], export: dict):
    """Like ``build_list_response`` but additionally supports iCal export."""
    fmt = export.get("format")
    if fmt is not None and fmt.value == "ical":
        return _build_ical_response(session, items, export)
    return build_list_response(data, items, export)


def _build_vtimezone(tz_str: str, tz: ZoneInfo) -> Timezone:
    """Build a VTIMEZONE component for the given IANA timezone (RFC 5545 §3.6.5).

    Probes the current year's DST transitions via binary search to populate
    STANDARD and DAYLIGHT sub-components.  Timezones without DST get a single
    STANDARD component.
    """
    from datetime import timezone as _utc

    year = datetime.now().year
    jan = datetime(year, 1, 15, 12, 0, tzinfo=tz)
    jul = datetime(year, 7, 15, 12, 0, tzinfo=tz)
    std_offset = jan.utcoffset()
    dst_offset = jul.utcoffset()

    vtz = Timezone()
    vtz.add("TZID", tz_str)

    if std_offset == dst_offset:
        # No daylight-saving transitions
        comp = TimezoneStandard()
        comp.add("DTSTART", datetime(1970, 1, 1, 0, 0, 0))
        comp.add("TZOFFSETFROM", std_offset)
        comp.add("TZOFFSETTO", std_offset)
        comp.add("TZNAME", jan.tzname())
        vtz.add_component(comp)
    else:
        def _find_transition(start_month: int, end_month: int) -> datetime:
            """Binary-search for the first hour-boundary DST transition."""
            low = datetime(year, start_month, 1, tzinfo=_utc.utc)
            high = datetime(year, end_month, 28, tzinfo=_utc.utc)
            while (high - low).total_seconds() > 3600:
                mid = low + (high - low) / 2
                if mid.astimezone(tz).utcoffset() != low.astimezone(tz).utcoffset():
                    high = mid
                else:
                    low = mid
            return high.astimezone(tz).replace(tzinfo=None)

        spring = _find_transition(2, 4)   # std→dst (clocks forward)
        fall = _find_transition(9, 11)    # dst→std (clocks back)

        dst_comp = TimezoneDaylight()
        dst_comp.add("DTSTART", spring)
        dst_comp.add("TZOFFSETFROM", std_offset)
        dst_comp.add("TZOFFSETTO", dst_offset)
        dst_comp.add("TZNAME", jul.tzname())
        vtz.add_component(dst_comp)

        std_comp = TimezoneStandard()
        std_comp.add("DTSTART", fall)
        std_comp.add("TZOFFSETFROM", dst_offset)
        std_comp.add("TZOFFSETTO", std_offset)
        std_comp.add("TZNAME", jan.tzname())
        vtz.add_component(std_comp)

    return vtz


def _build_ical_response(session: Session, items: list[dict], export: dict):
    """Convert event dicts into an iCalendar (.ics) file response.

    Title resolution uses a 6-layer strategy (Fixes 4, 8, 9/6, 11, 12).
    Supports: VCALENDAR name/timezone, per-event COLOR/TRANSP/ORGANIZER/CATEGORIES,
    multiple VALARMs, RRULE collapsing, and custom filename.
    """
    # ------------------------------------------------------------------ #
    # Apply ical_template preset (overrides individual format params)      #
    # ------------------------------------------------------------------ #
    template = export.get("ical_template")
    if template is not None:
        tval = template.value if hasattr(template, "value") else str(template)
        if tval == "compact":
            export = {**export, "ical_title_format": "{course_name}", "ical_description_format": None, "ical_location_format": None}
        elif tval == "detailed":
            export = {**export, "ical_title_format": "{module_name} – {course_name}", "ical_description_format": "{name}\n{staff_names}"}
        elif tval == "minimal":
            export = {**export, "ical_title_format": "{name}", "ical_description_format": None, "ical_location_format": None}
        # "custom" leaves individual params untouched

    loc_fmt: str | None = export.get("ical_location_format")
    desc_fmt: str | None = export.get("ical_description_format")
    reminder_mins: list[int] = export.get("ical_reminder_minutes") or []
    separator: str = export.get("ical_multi_value_separator") or " / "
    tz_str: str = export.get("ical_timezone") or "Europe/Berlin"
    filename: str = export.get("ical_filename") or "events.ics"
    ical_color: str | None = export.get("ical_color")
    busy_status = export.get("ical_busy_status")
    organizer: str | None = export.get("ical_organizer")
    categories: str | None = export.get("ical_categories")
    collapse: bool = bool(export.get("ical_collapse_recurring"))

    try:
        tz = ZoneInfo(tz_str)
    except (ZoneInfoNotFoundError, KeyError):
        tz = ZoneInfo("Europe/Berlin")

    # ------------------------------------------------------------------ #
    # Fix 8: pre-resolve ical_map → {event_id: name} dict                 #
    # ------------------------------------------------------------------ #
    ical_map_names: dict[int, str] = {}
    raw_map: str | None = export.get("ical_map")
    if raw_map:
        try:
            map_data: dict = json.loads(raw_map)
            map_type: str = export.get("ical_map_type") or "module"
            target_ids = set(int(v) for v in map_data.values())
            if map_type == "course":
                from database.model import Course as _Course
                rows = session.exec(select(_Course).where(_Course.id.in_(target_ids))).all()  # type: ignore
            else:
                from database.model import Module as _Module
                rows = session.exec(select(_Module).where(_Module.id.in_(target_ids))).all()  # type: ignore
            id_to_name = {r.id: r.name for r in rows}
            for eid_str, mid in map_data.items():
                name = id_to_name.get(int(mid)) or ""
                if name:
                    ical_map_names[int(eid_str)] = name
        except (json.JSONDecodeError, ValueError):
            pass  # Malformed map; silently skip

    # ------------------------------------------------------------------ #
    # VCALENDAR                                                            #
    # ------------------------------------------------------------------ #
    cal = Calendar()
    cal.add("prodid", "-//Almaweb Parser//EN")
    cal.add("version", "2.0")
    if cal_name := export.get("ical_calendar_name"):
        cal.add("x-wr-calname", cal_name)
    cal.add("x-wr-timezone", tz_str)
    cal.add_component(_build_vtimezone(tz_str, tz))

    # ------------------------------------------------------------------ #
    # Determine groups (collapse recurring or 1:1)                        #
    # ------------------------------------------------------------------ #
    print(f"Exporting {len(items)} events with collapse={collapse}")
    groups: list[list[dict]] = _collapse_recurring_to_rrule(items) if collapse else [[item] for item in items]

    for group in groups:
        representative = group[0]
        placeholders = _build_event_placeholders(representative, separator)
        summary = _resolve_event_title(representative, export, placeholders, ical_map_names)
        print(f"Processing event ID {representative.get('id')} with summary '{summary}' and {len(group)} occurrence(s)")

        ev = ICalEvent()
        ev.add("uid", f"event-{representative.get('id', 'unknown')}@almaweb-parser")
        ev.add("summary", summary)

        # Timestamps
        d: date_type | None = representative.get("event_date")
        t_start = representative.get("start_time")
        t_end = representative.get("end_time")
        if d and t_start:
            ev.add("dtstart", datetime.combine(d, t_start, tzinfo=tz))
        if d and t_end:
            ev.add("dtend", datetime.combine(d, t_end, tzinfo=tz))

        # RRULE + EXDATE for recurring groups
        if len(group) > 1:
            d_first: date_type = group[0]["event_date"]
            d_last: date_type = group[-1]["event_date"]
            total_weeks: int = (d_last - d_first).days // 7 + 1
            ev.add("rrule", {"FREQ": "WEEKLY", "COUNT": total_weeks})
            # Dates that would occur in a strict weekly series from d_first
            all_expected = {d_first + timedelta(weeks=i) for i in range(total_weeks)}
            actual_dates = {item.get("event_date") for item in group}
            skipped = sorted(all_expected - actual_dates)
            if skipped and t_start:
                ev.add("exdate", [datetime.combine(sk, t_start, tzinfo=tz) for sk in skipped])

        # Location: custom format > location.name from included relation
        if loc_fmt:
            loc_str = loc_fmt.format_map(placeholders)
            if loc_str:
                ev.add("location", loc_str)
        elif placeholders["location_name"]:
            ev.add("location", placeholders["location_name"])

        # Description
        if desc_fmt:
            desc_str = desc_fmt.format_map(placeholders)
            if desc_str:
                ev.add("description", desc_str)

        # Optional properties
        if ical_color:
            ev.add("color", ical_color)
        if busy_status is not None:
            bs_val = busy_status.value if hasattr(busy_status, "value") else str(busy_status)
            ev.add("transp", "TRANSPARENT" if bs_val == "FREE" else "OPAQUE")
        if organizer:
            ev.add("organizer", organizer)
        if categories:
            cats = categories.format_map(placeholders)
            if cats:
                ev.add("categories", cats)

        # VALARM components (one per reminder minute)
        for mins in reminder_mins:
            alarm = Alarm()
            alarm.add("action", "DISPLAY")
            alarm.add("trigger", timedelta(minutes=-mins))
            alarm.add("description", "Event reminder")
            ev.add_component(alarm)

        cal.add_component(ev)

    return Response(
        content=cal.to_ical(),
        media_type="text/calendar",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )