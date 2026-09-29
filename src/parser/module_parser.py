import gc
import re
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from threading import Event
from typing import TYPE_CHECKING, TypedDict

import httpx
from bs4 import BeautifulSoup, Tag

from src.parser.types import AchievementType, CourseType, EventType, ExamType, RoomType

try:
    from .course_parser import handleCourseList, MAX_CONCURRENT_COURSE_REQUESTS, _parse_date, _parse_time, _cell_value, _clean_staff
    from .utils import _WHITESPACE_RE, _cancelled, log_warning
    from .types import ModuleType
    from .fetch import ClientLike, create_cached_client
except ModuleNotFoundError:
    from src.parser.course_parser import handleCourseList, MAX_CONCURRENT_COURSE_REQUESTS, _parse_date, _parse_time, _cell_value, _clean_staff
    from src.parser.utils import _WHITESPACE_RE, _cancelled, log_warning  # type: ignore
    from src.parser.types import ModuleType
    from src.parser.fetch import ClientLike, create_cached_client  # type: ignore

if TYPE_CHECKING:
    from .crawler import ModuleLink

MAX_CONCURRENT_MODULE_REQUESTS = 4

# German label -> dict key used in the parsed module dict
_LABEL_MAP: dict[str, str] = {
    "Modulverantwortliche":    "responsible_person",
    "Dauer":                   "duration_semesters",
    "Leistungspunkte":         "credits",
    "Startsemester":           "start_semester",
    "Turnus":                  "frequency",
    "Ziele":                   "goals",
    "Inhalt":                  "content",
    "Prüfungsvorleistungen":   "exam_prerequisites",
    "Teilnahmevoraussetzungen": "prerequisites",
    "Literaturangabe":         "literature",
    "Anzahl Wahlkurse":        "elective_course_count",
    "Teilnahmevoraussetzungen für den Wahlbereich": "elective_prerequisites",
    "Moduleinstufung im Wahlbereich": "elective_classification",
    "Anmerkung zur Benotung":  "grading_note",
}

_EXAM_LABEL_MAP: dict[str, str] = {
    "Prüfung":          "name",
    "Datum":            "datetime",
    "Lehrende":         "staff",
    "Bestehenspflicht": "required",
}


def handleModuleList(
    moduleList: list["ModuleLink"],
    cancel_event: Event | None = None,
    progress_tracker=None,
    *,
    store=None,
    refresh: bool = False,
    offline: bool = False,
    on_module_done=None,
):
    """Fetch, parse and persist every module in ``moduleList`` concurrently.

    ``store``/``refresh``/``offline`` are forwarded to the cached HTTP client
    (see :mod:`src.parser.fetch`), which makes re-runs serve pages from disk.
    ``on_module_done(index, module, parsed)`` is invoked for every finished
    module (``parsed`` is ``None`` on failure), allowing callers to build
    resume checkpoints or per-module debug dumps.
    """
    if not moduleList:
        return

    # One shared client for all module and course requests; the pool size covers
    # up to MAX_CONCURRENT_MODULE_REQUESTS modules each fetching
    # MAX_CONCURRENT_COURSE_REQUESTS courses in parallel.
    total_connections = MAX_CONCURRENT_MODULE_REQUESTS * MAX_CONCURRENT_COURSE_REQUESTS
    limits = httpx.Limits(
        max_connections=total_connections,
        max_keepalive_connections=total_connections,
    )
    with create_cached_client(
        limits=limits,
        timeout=15.0,
        store=store,
        refresh=refresh,
        offline=offline,
    ) as client:
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_MODULE_REQUESTS) as executor:
            futures = [
                executor.submit(_fetch_and_parse_module, idx, module, client, cancel_event, progress_tracker)
                for idx, module in enumerate(moduleList)
            ]
            pending = set(futures)
            while pending:
                if _cancelled(cancel_event):
                    break

                done, pending = wait(pending, timeout=0.01, return_when=FIRST_COMPLETED)
                if not done:
                    continue

                for future in done:
                    idx, parsed = future.result()
                    if parsed is not None:
                        try:
                            from database.database import insert_module_graph
                        except ModuleNotFoundError:
                            from src.database.database import insert_module_graph
                        try:
                            insert_module_graph(parsed)
                        except Exception as e:
                            log_warning(
                                "module_insert_failed",
                                f"Failed inserting module {parsed.get('number', '<unknown>')} - {parsed.get('name', '<unknown>')}: {e}",
                                number=parsed.get("number", ""),
                                name=parsed.get("name", ""),
                                error=str(e),
                            )
                            raise
                    if on_module_done is not None:
                        on_module_done(idx, moduleList[idx], parsed)
                    if parsed is not None:
                        # Free the parsed module data immediately after DB insert
                        del parsed

                # Run garbage collection after each batch to reclaim memory from
                # completed worker threads (soup trees, response bodies, etc.)
                gc.collect()

                # Render progress after each batch of completed modules
                if progress_tracker is not None:
                    progress_tracker.render_parsing()

            if _cancelled(cancel_event):
                for future in pending:
                    future.cancel()
                executor.shutdown(wait=False, cancel_futures=True)

    if _cancelled(cancel_event):
        print(f"Parsing was interrupted. Modules already inserted are saved.")

def print_modules(modules: list[ModuleType]):
    def print_room(room: RoomType | None):
        if room is None:
            return None
        return {
            "name": room["name"],
            "external_id": room["external_id"],
            "description": room["description"],
            "type": room["type"],
            "seats": room["seats"],
            "size": room["size"],
            "accessibility": room["accessibility"],
            "building": {
                "name": room["building"]["name"],
                "short_name": room["building"]["short_name"],
                "address": room["building"]["address"],
            },
        }
    def print_events(events: list[EventType]):
        return [
            {
                "number": event["number"],
                "event_date": event["event_date"].isoformat(),
                "start_time": event["start_time"].isoformat(),
                "end_time": event["end_time"].isoformat(),
                "location": print_room(event["location"]),
                "staff": event["staff"],
            }
            for event in events
        ]
    def print_courses(courses: list[CourseType | None]):
        return [
            {
                "name": course["name"],
                "number": course["number"],
                "staff": course["staff"],
                "type": course["type"],
                "weekly_hours": course["weekly_hours"],
                "language": course["language"],
                "events": print_events(course["events"]),
                "status": course["status"],
            }
            for course in courses if course is not None
        ]
    return [
        {
            "name": module["name"],
            "number": module["number"],
            "path": module["path"],
            "responsible_person": module["responsible_person"],
            "duration_semesters": module["duration_semesters"],
            "credits": module["credits"],
            "start_semester": module["start_semester"],
            "frequency": module["frequency"],
            "goals": module["goals"],
            "content": module["content"],
            "exam_prerequisites": module["exam_prerequisites"],
            "prerequisites": module["prerequisites"],
            "courses": print_courses(module["courses"]),
        }
        for module in modules
    ]

def _fetch_and_parse_module(index: int, module: "ModuleLink", client: ClientLike, cancel_event: Event | None = None, progress_tracker=None) -> tuple[int, ModuleType | None]:
    if _cancelled(cancel_event):
        return index, None

    url = module.url
    if not url.startswith("http"):
        url = "https://almaweb.uni-leipzig.de" + url

    try:
        response = client.get(url)
    except Exception as e:
        log_warning(
            "module_fetch_error",
            f"An error occurred while fetching details for {module.name} under URL: {module.url}: {e}",
            module=module.name,
            url=module.url,
            error=str(e),
        )
        return index, None

    if response.status_code != 200:
        log_warning(
            "module_fetch_status",
            f"Failed to fetch details for {module.name} with status code {response.status_code} from URL: {url}",
            module=module.name,
            status=response.status_code,
            url=url,
        )
        return index, None

    if _cancelled(cancel_event):
        return index, None

    try:
        return index, parseModule(response.text, path=module.path, client=client, cancel_event=cancel_event, progress_tracker=progress_tracker)
    except Exception as e:
        # Distinguish a parser bug/value problem from a network failure. With the
        # parsers now total this should only fire on genuinely unexpected markup.
        log_warning(
            "module_parse_error",
            f"An error occurred while parsing details for {module.name} under URL: {module.url}: {e}",
            module=module.name,
            url=module.url,
            error=str(e),
        )
        return index, None


def parseModule(html_content: str, path: list[str] | list[list[str]], client: ClientLike | None = None, cancel_event: Event | None = None, progress_tracker=None) -> ModuleType | None:
    if _cancelled(cancel_event):
        return None

    soup = BeautifulSoup(html_content, 'html.parser')
    header = soup.find("h1")
    if not header:
        log_warning("module_header_missing", "Failed to find module header.")
        return None
    header_text = header.get_text(strip=True)
    header_parts = header_text.split(None, 1)
    if len(header_parts) < 2:
        log_warning("module_header_malformed", f"Malformed module header: {header_text!r}", value=header_text)
        number, name = header_text, ""
    else:
        number, name = header_parts

    if progress_tracker is not None:
        progress_tracker.set_current_module(f"{number} - {name}")

    left_content = soup.select_one("#contentlayoutleft")
    values = extract_module_values(left_content)
    # Extract course link URLs using BeautifulSoup (the module page count is low)
    course_urls = [
        str(a["href"])
        for a in soup.find_all("a", attrs={"name": "eventLink"})
        if "COURSEDETAILS" in a["href"]
    ]
    # remove duplicates while preserving order
    seen = set()
    course_urls = [x for x in course_urls if not (x in seen or seen.add(x))]
    try:
        courses = handleCourseList(course_urls, cancel_event=cancel_event, client=client, progress_tracker=progress_tracker)
    except Exception as e:
        log_warning("module_parse_error", f"Failed to parse courses for {name}: {e}", module=name, error=str(e))
        courses = []
    try:
        exams = extract_exams(find_exam_section(left_content), name, progress_tracker=progress_tracker)
    except Exception as e:
        # A single bad exam row must not drop the whole module.
        log_warning("module_parse_error", f"Failed to parse exams for {name}: {e}", module=name, error=str(e))
        exams = []
    try:
        achievements = extract_achievements(find_achievements_table(left_content), name)
    except Exception as e:
        log_warning("module_parse_error", f"Failed to parse achievements for {name}: {e}", module=name, error=str(e))
        achievements = []
    # Free BeautifulSoup tree and raw HTML after extracting all data
    del soup
    del html_content

    module: ModuleType = {
        "name": name,
        "number": number,
        "path": _normalize_path(path),
        "responsible_person": values["responsible_person"],
        "duration_semesters": parse_int(values["duration_semesters"]),
        "credits": parse_float(values["credits"]),
        "start_semester": values["start_semester"],
        "frequency": values["frequency"],
        "goals": values["goals"],
        "content": values["content"],
        "exam_prerequisites": values["exam_prerequisites"],
        "prerequisites": parse_prerequisites(values["prerequisites"]),
        "literature": values["literature"],
        "elective_course_count": parse_int(values["elective_course_count"]),
        "elective_prerequisites": values["elective_prerequisites"],
        "elective_classification": values["elective_classification"],
        "grading_note": values["grading_note"],
        "courses": courses,
        "exams": exams,
        "achievements": achievements,
    }
    room_count = len({
        (location.get("name") or location.get("external_id"))
        for course in module['courses'] if course is not None
        for event in course['events'] if event is not None
        for location in ([event.get('location')] if event.get('location') else [])
    })

    # Update progress tracker
    if progress_tracker is not None:
        progress_tracker.increment("modules")
        progress_tracker.set_current_module("")

    print(f"Parsed module {module['number']} - {module['name']}. Includes {len(module['courses'])} courses and {sum(len(course['events']) for course in module['courses'] if course is not None)} events with {room_count} rooms.")
    return module


def extract_module_values(content: Tag | None) -> dict[str, str]:
    values: dict[str, str] = {
        "responsible_person": "",
        "duration_semesters": "",
        "credits": "",
        "start_semester": "",
        "frequency": "",
        "goals": "",
        "content": "",
        "exam_prerequisites": "",
        "prerequisites": "",
        "literature": "",
        "elective_course_count": "",
        "elective_prerequisites": "",
        "elective_classification": "",
        "grading_note": "",
    }
    if content is None:
        return values

    for label_tag in content.select(".font-semibold.break-all"):
        label = _WHITESPACE_RE.sub(" ", label_tag.get_text(" ", strip=True)).rstrip(":")
        key = _LABEL_MAP.get(label)
        if key is None:
            # Surface fields the parser does not know about instead of dropping
            # them silently; the audit groups these warnings.
            if label:
                log_warning(
                    "unknown_module_label",
                    f"Unknown module field {label!r}.",
                    label=label,
                )
            continue
        value_tag = label_tag.find_next_sibling("div")
        if value_tag is None:
            continue
        values[key] = _WHITESPACE_RE.sub(" ", value_tag.get_text(" ", strip=True))

    return values


def parse_int(value: str) -> int:
    match = re.search(r"-?\d+", value)
    return int(match.group(0)) if match else 0


def parse_float(value: str) -> float:
    normalized = value.replace(" ", "").replace(",", ".")
    match = re.search(r"-?\d+(?:\.\d+)?", normalized)
    return float(match.group(0)) if match else 0.0


def parse_prerequisites(value: str) -> dict[str, str]:
    if not value:
        return {}

    parts = [part.strip() for part in re.split(r"[\r\n]+", value) if part.strip()]

    prerequisites: dict[str, str] = {}
    for part in parts:
        if ":" in part:
            key, val = part.split(":", 1)
            key = key.strip()
            val = val.strip()
            if key and val:
                prerequisites[key] = val
                continue
        if part:
            prerequisites["allgemein"] = part

    return prerequisites

def find_exam_section(right_content: Tag | None) -> Tag | None:
    if right_content is None or not isinstance(right_content.parent, Tag):
        return None

    for section in right_content.parent.find_all("div", recursive=False):
        if not isinstance(section, Tag):
            continue
        for child in section.children:
            if isinstance(child, Tag) and "Modulabschlussprüfungen" in child.get_text(" ", strip=True):
                return child

    return None


def _normalize_path(path: list[str] | list[list[str]] | None) -> list[list[str]]:
    """Normalise a navigation path to the canonical ``list[list[str]]`` shape."""
    if not path:
        return []
    if any(isinstance(node, list) for node in path):
        return [[str(node) for node in group] for group in path if group]  # type: ignore[union-attr]
    return [[str(node) for node in path]]


def find_achievements_table(right_content: Tag | None) -> Tag | None:
    """Return the "Leistungen" (module achievements) table, if present.

    The table is not always nested inside ``#contentlayoutleft``; like the exams
    section it can live in a sibling branch of the page form, so search from the
    enclosing form when available.
    """
    if right_content is None:
        return None
    scope = right_content.parent if isinstance(right_content.parent, Tag) else right_content
    table = scope.find("table", attrs={"summary": "Leistungen"})
    return table if isinstance(table, Tag) else None


def extract_achievements(table: Tag | None, module_name: str) -> list[AchievementType]:
    """Extract ``Modulabschlussleistungen`` (achievements) rows.

    Columns are identified by their semantic class names:
    ``rw-detail-reqachieve`` (name), ``rw-detail-compulsory`` (Leistungskombination)
    and ``rw-detail-weight`` (Gewichtung). This table is otherwise not read by the
    parser, so its data was previously dropped entirely.
    """
    if table is None:
        return []

    achievements: list[AchievementType] = []
    for row in table.select("tbody tr"):
        by_class: dict[str, Tag] = {}
        for cell in row.find_all("td", recursive=False):
            for class_name in (cell.get("class") or []):
                if class_name.startswith("rw-detail"):
                    by_class.setdefault(class_name, cell)

        name_cell = by_class.get("rw-detail-reqachieve")
        if name_cell is None:
            continue
        name = _WHITESPACE_RE.sub(" ", _cell_value(name_cell)).strip()
        if not name:
            continue

        combination_raw = _cell_value(by_class["rw-detail-compulsory"]) if "rw-detail-compulsory" in by_class else ""
        weight_raw = _cell_value(by_class["rw-detail-weight"]) if "rw-detail-weight" in by_class else ""

        achievements.append({
            "name": name,
            "required": _WHITESPACE_RE.sub(" ", combination_raw).strip() == "Ja",
            "weight": parse_float(weight_raw) if weight_raw else None,
            "combination": _WHITESPACE_RE.sub(" ", combination_raw).strip(),
        })
    return achievements


def parse_exam_datetime(datetime_str: str) -> tuple[str, str, str]:
    # Expected format: "Mi, 15. Jul. 2026, 08:30 - 09:30"
    # Do, 1. Okt. 2026, 15:00 - 16:00
    match = re.match(r"\w{2}, (\d{1,2}\. \w{3}\. \d{4}), (\d{2}:\d{2}) - (\d{2}:\d{2})", datetime_str)
    if match:
        date_str, start_time, end_time = match.groups()
        return date_str, start_time, end_time
    return "", "", ""

def extract_exams(content: Tag | None, course_name: str, progress_tracker=None) -> list[ExamType]:
    if content is None:
        log_warning("no_exams_content", f"No exams content found for course: {course_name}", course=course_name)
        return []

    header = content.find("div", recursive=False)
    if header is not None and header.get_text(" ", strip=True) != "Modulabschlussprüfungen":
        log_warning("no_exams_section", f"No exams section found for course: {course_name}", course=course_name)
        return []

    exams = []
    for event_row in content.select("table tbody tr"):
        cells = event_row.find_all("td", recursive=False)
        if not cells:
            continue

        # Identify columns by their AlmaWeb class names instead of by position.
        # The leading "Leistungskombination" cell uses a rowspan and therefore
        # only exists in the first row of each exam group; positional indexing
        # shifted every following column (dates/time ranges ended up as staff).
        by_class: dict[str, Tag] = {}
        for cell in cells:
            for class_name in (cell.get("class") or []):
                by_class.setdefault(class_name, cell)
        name_cell = by_class.get("rw-detail-exam")
        date_cell = by_class.get("rw-detail-date")
        staff_cell = by_class.get("rw-detail-instructors")
        required_cell = by_class.get("rw-detail-compulsory")

        # Fall back to positional columns for older AlmaWeb markup that does not
        # expose the semantic class attributes.
        if name_cell is None or date_cell is None or staff_cell is None or required_cell is None:
            if len(cells) < 4:
                continue
            name_cell, date_cell, staff_cell, required_cell = cells[:4]

        # Remove any leading/trailing whitespace from the name
        # Also remove multiple spaces and newlines from the name
        name = _cell_value(name_cell).strip()
        name = re.sub(r'\s+', ' ', name)
        datetime_str = _cell_value(date_cell)
        staff_raw = _cell_value(staff_cell, separator=", ")
        required_raw = _cell_value(required_cell)
        date_str, start_time, end_time = ("", "", "") if datetime_str == "k.Terminbuchung" else parse_exam_datetime(datetime_str)
        staff = _clean_staff(staff_raw)
        required = required_raw == "Ja"

        if progress_tracker is not None:
            progress_tracker.increment("exams")

        exams.append({
            "name": name,
            "date": None if date_str == "" else _parse_date(date_str),
            "start_time": None if start_time == "" else _parse_time(start_time),
            "end_time": None if end_time == "" else _parse_time(end_time),
            "staff": staff,
            "required": required,
        })
    return exams