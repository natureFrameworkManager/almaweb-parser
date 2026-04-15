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

def model_include_tree(model_class: type) -> dict[str, list[Any]]:
    """
    Build a nested relation tree for a SQLModel class.

    The tree is based on SQLAlchemy relationships plus foreign key targets
    that do not have an explicit SQLModel Relationship field yet.

    Cycles are prevented per traversal branch so bidirectional links do not
    recurse forever.
    """
    mapper = sa_inspect(model_class)
    table_to_model = {
        m.local_table.name: m.class_
        for m in mapper.registry.mappers
        if getattr(m.class_, "__table__", None) is not None
    }

    def _relation_targets(current_model: type) -> list[tuple[str, type]]:
        current_mapper = sa_inspect(current_model)
        targets: list[tuple[str, type]] = []
        seen_names: set[str] = set()

        # 1) Explicit relationships declared on the model.
        for relation in current_mapper.relationships.values():
            relation_name = relation.key
            target_model = relation.entity.class_
            if relation_name not in seen_names:
                seen_names.add(relation_name)
                targets.append((relation_name, target_model))

        # 2) Foreign-key targets for fields without explicit relationships.
        for column in current_mapper.columns:
            for fk in column.foreign_keys:
                relation_name = column.key[:-3] if column.key.endswith("_id") else column.key
                target_model = table_to_model.get(fk.column.table.name)
                if target_model is None or relation_name in seen_names:
                    continue
                seen_names.add(relation_name)
                targets.append((relation_name, target_model))

        return targets

    def _build_tree(current_model: type, ancestors: set[type]) -> list[Any]:
        branch: list[Any] = []
        next_ancestors = ancestors | {current_model}

        for relation_name, target_model in _relation_targets(current_model):
            if target_model in ancestors:
                continue

            subtree = _build_tree(target_model, next_ancestors)
            if subtree:
                branch.append({relation_name: subtree})
            else:
                branch.append(relation_name)

        return branch

    return {model_class.__name__: _build_tree(model_class, set())}


def _model_relation_targets(model_class: type) -> list[tuple[str, type]]:
    """Return direct relation name -> model pairs for a SQLModel class."""
    mapper = sa_inspect(model_class)
    table_to_model = {
        m.local_table.name: m.class_
        for m in mapper.registry.mappers
        if getattr(m.class_, "__table__", None) is not None
    }

    targets: list[tuple[str, type]] = []
    seen_names: set[str] = set()

    for relation in mapper.relationships.values():
        relation_name = relation.key
        target_model = relation.entity.class_
        if relation_name not in seen_names:
            seen_names.add(relation_name)
            targets.append((relation_name, target_model))

    for column in mapper.columns:
        for fk in column.foreign_keys:
            relation_name = column.key[:-3] if column.key.endswith("_id") else column.key
            target_model = table_to_model.get(fk.column.table.name)
            if target_model is None or relation_name in seen_names:
                continue
            seen_names.add(relation_name)
            targets.append((relation_name, target_model))

    return targets

def _flatten_include_tree(include_tree: dict[str, list[Any]]) -> list[str]:
    """Flatten a nested include tree into dot-notation paths."""
    include_paths: list[str] = []

    def _walk(nodes: list[Any], prefix: str = ""):
        for node in nodes:
            if isinstance(node, str):
                path = f"{prefix}.{node}" if prefix else node
                include_paths.append(path)
                continue

            if isinstance(node, dict):
                for name, children in node.items():
                    path = f"{prefix}.{name}" if prefix else name
                    include_paths.append(path)
                    if isinstance(children, list):
                        _walk(children, path)

    root_children = next(iter(include_tree.values()), [])
    _walk(root_children)

    # Keep order stable while deduplicating.
    return list(dict.fromkeys(include_paths))


def _dot_paths_enum(enum_name: str, values: list[str]) -> type[Enum]:
    """Build a stable string Enum from dot-notation include paths."""
    members: dict[str, str] = {}
    for value in values:
        base_name = re.sub(r"[^a-zA-Z0-9]", "_", value).upper()
        if not base_name:
            continue
        if base_name[0].isdigit():
            base_name = f"V_{base_name}"

        name = base_name
        suffix = 2
        while name in members and members[name] != value:
            name = f"{base_name}_{suffix}"
            suffix += 1

        members[name] = value

    return cast(type[Enum], Enum(enum_name, members, type=str))


def _related_field_paths(model_class: type) -> list[str]:
    """Build dot-notation field paths for related models recursively."""
    field_paths: list[str] = []

    def _walk(current_model: type, prefix: str = "", ancestors: set[type] | None = None):
        parent_ancestors = ancestors or set()
        next_ancestors = parent_ancestors | {current_model}

        for relation_name, target_model in _model_relation_targets(current_model):
            if target_model in parent_ancestors:
                continue

            relation_prefix = f"{prefix}.{relation_name}" if prefix else relation_name
            field_paths.append(relation_prefix)

            for target_field in target_model.model_fields.keys():
                field_paths.append(f"{relation_prefix}.{target_field}")

            _walk(target_model, relation_prefix, next_ancestors)

    _walk(model_class)
    return list(dict.fromkeys(field_paths))


def _resolve_dot_path_value(obj: Any, path: str) -> Any:
    """Resolve a dot-notation path on SQLModel objects, dicts, and lists."""
    current: Any = obj
    parts = path.split(".")

    for index, part in enumerate(parts):
        if current is None:
            return None

        if isinstance(current, list):
            remaining = ".".join(parts[index:])
            return [_resolve_dot_path_value(item, remaining) for item in current]

        if isinstance(current, dict):
            current = current.get(part)
            continue

        current = getattr(current, part, None)

    return current


def _model_column_fields(model_class: type) -> list[str]:
    """Return DB column names for a model class."""
    return [column.key for column in sa_inspect(model_class).columns]


def _fk_relation_target(model_class: type, relation_name: str) -> tuple[type, str] | None:
    """Resolve a foreign-key-derived relation name to (target_model, fk_column)."""
    mapper = sa_inspect(model_class)
    table_to_model = {
        m.local_table.name: m.class_
        for m in mapper.registry.mappers
        if getattr(m.class_, "__table__", None) is not None
    }

    for column in mapper.columns:
        for fk in column.foreign_keys:
            candidate = column.key[:-3] if column.key.endswith("_id") else column.key
            if candidate != relation_name:
                continue
            target_model = table_to_model.get(fk.column.table.name)
            if target_model is not None:
                return target_model, column.key
    return None


def _relation_chain_from_path(model_class: type, path: str) -> list[str]:
    """Extract the relation segment chain from a dot path."""
    chain: list[str] = []
    current_model = model_class

    for token in path.split("."):
        relationships = sa_inspect(current_model).relationships
        if token in relationships:
            chain.append(token)
            current_model = relationships[token].entity.class_
            continue

        fk_target = _fk_relation_target(current_model, token)
        if fk_target is not None:
            chain.append(token)
            current_model = fk_target[0]
            continue

        break

    return chain


def _relation_chains(model_class: type, include_paths: list[str], field_paths: list[str]) -> list[list[str]]:
    """Collect unique relation chains from include and field selections."""
    chains: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()

    for path in include_paths + field_paths:
        chain = _relation_chain_from_path(model_class, path)
        if not chain:
            continue
        key = tuple(chain)
        if key in seen:
            continue
        seen.add(key)
        chains.append(chain)

    return chains


def _query_with_relation_loads(query, model_class: type, chains: list[list[str]]):
    """Attach selectinload options for explicit SQLAlchemy relationships."""
    options = []

    for chain in chains:
        current_model = model_class
        loader = None
        valid = True

        for relation_name in chain:
            relationships = sa_inspect(current_model).relationships
            if relation_name not in relationships:
                # FK-only relations (without Relationship field) cannot be eager-loaded here.
                valid = False
                break

            relation_attr = getattr(current_model, relation_name)
            loader = selectinload(relation_attr) if loader is None else loader.selectinload(relation_attr)
            current_model = relationships[relation_name].entity.class_

        if valid and loader is not None:
            options.append(loader)

    if not options:
        return query
    return query.options(*options)


def _new_projection_node() -> dict[str, Any]:
    return {"__all__": False, "__fields__": set(), "__relations__": {}}


def _projection_for_response(
    model_class: type,
    selected_fields: list[str] | None,
    include_paths: list[str],
) -> dict[str, Any]:
    """Build a projection tree for final response serialization."""
    projection = _new_projection_node()

    def _ensure_relation_node(node: dict[str, Any], relation_name: str) -> dict[str, Any]:
        relations = node["__relations__"]
        if relation_name not in relations:
            relations[relation_name] = _new_projection_node()
        return relations[relation_name]

    if selected_fields:
        for path in selected_fields:
            tokens = path.split(".")
            current_model = model_class
            current_node = projection

            for idx, token in enumerate(tokens):
                relationships = sa_inspect(current_model).relationships
                fk_target = _fk_relation_target(current_model, token)

                if token in relationships:
                    current_node = _ensure_relation_node(current_node, token)
                    current_model = relationships[token].entity.class_
                    if idx == len(tokens) - 1:
                        current_node["__all__"] = True
                    continue

                if fk_target is not None:
                    current_node = _ensure_relation_node(current_node, token)
                    current_model = fk_target[0]
                    if idx == len(tokens) - 1:
                        current_node["__all__"] = True
                    continue

                if idx == len(tokens) - 1:
                    current_node["__fields__"].add(token)
                break
    else:
        projection["__all__"] = True

        for include_path in include_paths:
            tokens = include_path.split(".")
            current_model = model_class
            current_node = projection

            for token in tokens:
                relationships = sa_inspect(current_model).relationships
                fk_target = _fk_relation_target(current_model, token)

                if token in relationships:
                    current_node = _ensure_relation_node(current_node, token)
                    current_node["__all__"] = True
                    current_model = relationships[token].entity.class_
                    continue

                if fk_target is not None:
                    current_node = _ensure_relation_node(current_node, token)
                    current_node["__all__"] = True
                    current_model = fk_target[0]
                    continue

                break

    return projection


def _relation_value(
    session: SessionDep,
    item: Any,
    model_class: type,
    relation_name: str,
) -> tuple[Any, type | None, bool]:
    """Get relation value plus metadata, supporting FK-only relations."""
    relationships = sa_inspect(model_class).relationships
    if relation_name in relationships:
        relation = relationships[relation_name]
        return getattr(item, relation_name, None), relation.entity.class_, bool(relation.uselist)

    fk_target = _fk_relation_target(model_class, relation_name)
    if fk_target is not None:
        target_model, fk_column = fk_target
        target_id = getattr(item, fk_column, None)
        if target_id is None:
            return None, target_model, False
        return session.get(target_model, target_id), target_model, False

    return None, None, False


def _serialize_with_projection(
    session: SessionDep,
    item: Any,
    model_class: type,
    projection: dict[str, Any],
) -> dict[str, Any]:
    """Serialize one SQLModel item according to a projection tree."""
    result: dict[str, Any] = {}

    if projection["__all__"]:
        field_names = _model_column_fields(model_class)
    else:
        field_names = sorted(projection["__fields__"])

    for field_name in field_names:
        result[field_name] = getattr(item, field_name, None)

    for relation_name, relation_projection in projection["__relations__"].items():
        relation_value, target_model, is_many = _relation_value(session, item, model_class, relation_name)
        if target_model is None:
            continue

        if is_many:
            if relation_value is None:
                result[relation_name] = []
            else:
                result[relation_name] = [
                    _serialize_with_projection(session, child, target_model, relation_projection)
                    for child in relation_value
                ]
        else:
            result[relation_name] = (
                _serialize_with_projection(session, relation_value, target_model, relation_projection)
                if relation_value is not None
                else None
            )

    return result

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
    root_fields = list(model_class.model_fields.keys())
    related_fields = _related_field_paths(model_class)
    field_values = list(dict.fromkeys(root_fields + related_fields))

    FieldEnum = _dot_paths_enum(f"{model_class.__name__}Field", field_values)

    def _fields_parameters(
        fields: list[FieldEnum] | None = Query(None, description="Comma-separated list of fields to include in the response. If not provided, all fields will be included."), # type: ignore
    ):
        return {
            "fields": [str(v.value) for v in fields] if fields else None,
        }

    return _fields_parameters


def include_parameters(model_class: type, virtual_includes: dict[str, type] | None = None):
    """
    Build a FastAPI dependency for the include parameter.

    Auto-discovers relationship names from the model and optionally adds virtual includes.
    """

    include_tree = model_include_tree(model_class)
    include_values = _flatten_include_tree(include_tree)
    if virtual_includes:
        include_values.extend([key for key in virtual_includes.keys() if key not in include_values])

    IncludeEnum = _dot_paths_enum(f"{model_class.__name__}IncludeField", include_values)

    def _include_parameters(
        include: list[IncludeEnum] | None = Query(None, description="Related data to include in the response. Repeatable for multiple relations."),  # type: ignore
    ):
        return {
            "include": [str(v.value) for v in include] if include else None,
            "virtual_includes": virtual_includes,
        }

    return _include_parameters

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
    
def filter_query(session: SessionDep, query, filtering: dict, model_class: type, including: dict | None = None):
    include_paths = including.get("include") if including else None
    include_values = include_paths or []
    selected_fields = filtering.get("fields")

    # Verify that filtering keys are valid model fields
    valid_fields = set(model_class.model_fields.keys())
    valid_fields.update(_related_field_paths(model_class))
    for key in filtering["fields"] or []:
        if key not in valid_fields:
            raise ValueError(f"Invalid filter field: {key}. Valid fields are: {', '.join(valid_fields)}")

    # Preload requested relation chains where explicit relationships are available.
    chains = _relation_chains(model_class, include_values, selected_fields or [])
    query = _query_with_relation_loads(query, model_class, chains)

    # Get unfiltered items to apply field selection
    unfiltered_items = session.exec(query).all()

    projection = _projection_for_response(model_class, selected_fields, include_values)
    items = [_serialize_with_projection(session, module, model_class, projection) for module in unfiltered_items]
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
        for item in items:
            writer.writerow({k: json.dumps(v, default=str) if isinstance(v, (dict, list)) else v for k, v in item.items()})
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