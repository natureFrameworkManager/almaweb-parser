import csv
import io
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, cast

from fastapi import HTTPException, Query
from fastapi.responses import Response
from icalendar import Calendar, Event as ICalEvent, Alarm
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


def build_event_list_response(data: dict, items: list[dict], export: dict):
    """Like ``build_list_response`` but additionally supports iCal export."""
    fmt = export.get("format")
    if fmt is not None and fmt.value == "ical":
        return _build_ical_response(items, export)
    return build_list_response(data, items, export)


def _build_ical_response(items: list[dict], export: dict) -> Response:
    """Convert event dicts into an iCalendar file response."""
    title_fmt = export.get("ical_title_format") or "{name}"
    loc_fmt = export.get("ical_location_format")
    desc_fmt = export.get("ical_description_format")
    reminder_min = export.get("ical_reminder_minutes")

    cal = Calendar()
    cal.add("prodid", "-//Almaweb Parser//EN")
    cal.add("version", "2.0")

    for item in items:
        # defaultdict ensures missing placeholders resolve to "" instead of raising
        safe = defaultdict(str, {k: (v if v is not None else "") for k, v in item.items()})

        ev = ICalEvent()
        ev.add("uid", f"event-{item.get('id', 'unknown')}@almaweb-parser")
        ev.add("summary", title_fmt.format_map(safe))

        date, t_start, t_end = item.get("event_date"), item.get("start_time"), item.get("end_time")
        if date and t_start:
            ev.add("dtstart", datetime.combine(date, t_start))
        if date and t_end:
            ev.add("dtend", datetime.combine(date, t_end))

        # Location: custom format > raw field
        if loc_fmt:
            ev.add("location", loc_fmt.format_map(safe))
        elif item.get("location"):
            ev.add("location", str(item["location"]))

        if desc_fmt:
            ev.add("description", desc_fmt.format_map(safe))

        # Optional pre-event reminder alarm
        if reminder_min is not None:
            alarm = Alarm()
            alarm.add("action", "DISPLAY")
            alarm.add("trigger", timedelta(minutes=-reminder_min))
            alarm.add("description", "Event reminder")
            ev.add_component(alarm)

        cal.add_component(ev)

    return Response(
        content=cal.to_ical(),
        media_type="text/calendar",
        headers={"Content-Disposition": "attachment; filename=events.ics"},
    )