import re
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from threading import Event
from typing import TYPE_CHECKING, TypedDict

import httpx
from bs4 import BeautifulSoup, Tag

from src.parser.types import CourseType, EventType, ExamType, RoomType

try:
    from .course_parser import handleCourseList, MAX_CONCURRENT_COURSE_REQUESTS, _parse_date, _parse_time
    from .utils import _WHITESPACE_RE, _cancelled
    from .types import ModuleType
except ModuleNotFoundError:
    from src.parser.course_parser import handleCourseList, MAX_CONCURRENT_COURSE_REQUESTS, _parse_date, _parse_time
    from src.parser.utils import _WHITESPACE_RE, _cancelled
    from src.parser.types import ModuleType

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
}

_EXAM_LABEL_MAP: dict[str, str] = {
    "Prüfung":          "name",
    "Datum":            "datetime",
    "Lehrende":         "staff",
    "Bestehenspflicht": "required",
}


def handleModuleList(moduleList: list["ModuleLink"], cancel_event: Event | None = None, progress_tracker=None):
    if not moduleList:
        return []

    parsed_by_index: dict[int, ModuleType] = {}

    # One shared client for all module and course requests; the pool size covers
    # up to MAX_CONCURRENT_MODULE_REQUESTS modules each fetching
    # MAX_CONCURRENT_COURSE_REQUESTS courses in parallel.
    total_connections = MAX_CONCURRENT_MODULE_REQUESTS * MAX_CONCURRENT_COURSE_REQUESTS
    limits = httpx.Limits(
        max_connections=total_connections,
        max_keepalive_connections=total_connections,
    )
    with httpx.Client(limits=limits, timeout=15.0) as client:
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
                        parsed_by_index[idx] = parsed
                        try:
                            from database.database import insert_module_graph
                        except ModuleNotFoundError:
                            from src.database.database import insert_module_graph
                        try:
                            insert_module_graph(parsed)
                        except Exception as e:
                            print(f"Failed inserting module {parsed.get('number', '<unknown>')} - {parsed.get('name', '<unknown>')}: {e}")
                            raise

                # Render progress after each batch of completed modules
                if progress_tracker is not None:
                    progress_tracker.render_parsing()

            if _cancelled(cancel_event):
                for future in pending:
                    future.cancel()
                executor.shutdown(wait=False, cancel_futures=True)

    modules = [parsed_by_index[idx] for idx in sorted(parsed_by_index.keys())]

    if _cancelled(cancel_event):
        print(f"Saved {len(modules)} parsed modules before interruption.")

    # Print the parsed modules in a structured format to a file for easier inspection and debugging
    # with open("parsed_modules.json", "w", encoding="utf-8") as f:
    #     import json
    #     json.dump(print_modules(modules), f, ensure_ascii=False, indent=4)
    return modules

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

def _fetch_and_parse_module(index: int, module: "ModuleLink", client: httpx.Client, cancel_event: Event | None = None, progress_tracker=None) -> tuple[int, ModuleType | None]:
    try:
        if _cancelled(cancel_event):
            return index, None

        url = module.url
        if not url.startswith("http"):
            url = "https://almaweb.uni-leipzig.de" + url

        response = client.get(url)
        if response.status_code == 200:
            if _cancelled(cancel_event):
                return index, None
            return index, parseModule(response.text, path=module.path, client=client, cancel_event=cancel_event, progress_tracker=progress_tracker)

        print(f"Failed to fetch details for {module.name} with status code {response.status_code} from URL: {url}")
    except Exception as e:
        print(f"An error occurred while fetching details for {module.name} under URL: {module.url}: {e}")

    return index, None


def parseModule(html_content: str, path: list[str], client: httpx.Client | None = None, cancel_event: Event | None = None, progress_tracker=None) -> ModuleType | None:
    if _cancelled(cancel_event):
        return None

    soup = BeautifulSoup(html_content, 'html.parser')
    header = soup.find("h1")
    if not header:
        print("Failed to find module header.")
        return None
    number, name = header.get_text(strip=True).split(None, 1)

    if progress_tracker is not None:
        progress_tracker.set_current_module(f"{number} - {name}")

    values = extract_module_values(soup.select_one("#contentlayoutleft"))
    course_urls = [
        str(a["href"])
        for a in soup.find_all("a", attrs={"name": "eventLink"})
        if "COURSEDETAILS" in a["href"]
    ]
    # remove duplicates while preserving order
    seen = set()
    course_urls = [x for x in course_urls if not (x in seen or seen.add(x))]
    courses = handleCourseList(course_urls, cancel_event=cancel_event, client=client, progress_tracker=progress_tracker)
    exams = extract_exams(find_exam_section(soup.select_one("#contentlayoutleft")), name, progress_tracker=progress_tracker)

    module: ModuleType = {
        "name": name,
        "number": number,
        "path": path,
        "responsible_person": values["responsible_person"],
        "duration_semesters": parse_int(values["duration_semesters"]),
        "credits": parse_float(values["credits"]),
        "start_semester": values["start_semester"],
        "frequency": values["frequency"],
        "goals": values["goals"],
        "content": values["content"],
        "exam_prerequisites": values["exam_prerequisites"],
        "prerequisites": parse_prerequisites(values["prerequisites"]),
        "courses": courses,
        "exams": exams,
    }
    room_count = len(set(room for course in module['courses'] if course is not None for event in course['events'] if event is not None for room in ([event.get('room')] if event.get('room') else [])))

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
    }
    if content is None:
        return values

    for label_tag in content.select(".font-semibold.break-all"):
        label = _WHITESPACE_RE.sub(" ", label_tag.get_text(" ", strip=True)).rstrip(":")
        key = _LABEL_MAP.get(label)
        if key is None:
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
        print(f"No exams content found for course: {course_name}")
        return []

    header = content.find("div", recursive=False)
    if header is not None and header.get_text(" ", strip=True) != "Modulabschlussprüfungen":
        print(f"No exams section found for course: {course_name}")
        return []

    exams = []
    for event_row in content.select("table tbody tr"):
        cells = [
            span for span in event_row.select("td span")
            if "lg:hidden" not in (span.get("class") or [])
        ]
        if len(cells) < 4:
            continue
        name, datetime_str, staff_raw, required_raw = [
            cell.get_text(" ", strip=True) for cell in cells[:4]
        ]
        # Remove any leading/trailing whitespace from the name
        # Also remove multiple spaces and newlines from the name
        name = name.strip()
        name = re.sub(r'\s+', ' ', name)
        date_str, start_time, end_time = ("", "", "") if datetime_str == "k.Terminbuchung" else parse_exam_datetime(datetime_str)
        staff = [s.strip() for s in re.split(r"[,;]", staff_raw) if s.strip()]
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