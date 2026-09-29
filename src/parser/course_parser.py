from typing import TypedDict
import re
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import date, time
from threading import Event

import httpx
from bs4 import BeautifulSoup, Tag

try:
    from .utils import _WHITESPACE_RE, _cancelled, log_warning
    from .types import CourseType, EventType, RoomType, BuildingType
    from .room_parser import fetch_and_parse_room_details
    from .fetch import ClientLike, create_cached_client
except ModuleNotFoundError:
    from src.parser.utils import _WHITESPACE_RE, _cancelled, log_warning  # type: ignore
    from src.parser.types import CourseType, EventType, RoomType, BuildingType
    from src.parser.room_parser import fetch_and_parse_room_details
    from src.parser.fetch import ClientLike, create_cached_client  # type: ignore

MAX_CONCURRENT_COURSE_REQUESTS = 8

# German 3-letter month abbreviations -> month number
_MONTHS: dict[str, int] = {
    "Jan": 1, "Feb": 2, "Mär": 3, "Apr": 4,
    "Mai": 5, "Jun": 6, "Jul": 7, "Aug": 8,
    "Sep": 9, "Okt": 10, "Nov": 11, "Dez": 12,
}

# label text -> (dict key, HTML tag to read the value from)
_COURSE_LABEL_MAP: dict[str, tuple[str, str]] = {
    "Lehrende":              ("staff",        "span"),
    "Veranstaltungsart":     ("type",         "div"),
    "Semesterwochenstunden": ("weekly_hours", "div"),
    "Unterrichtssprache":    ("language",     "span"),
    "Orga-Einheit":          ("org_unit",     "span"),
    "Offizielle Kursbeschreibung": ("official_description", "span"),
    "Organisatorisches":     ("organisational", "span"),
    "Literatur":             ("literature",   "span"),
}

# CampusNet renders every table cell as a flex container holding a mobile-only
# label span (hidden on large screens via ``lg:hidden``) followed by the actual
# value span(s). Filtering all ``span`` elements of a row and indexing them by
# position is fragile: a single cell may contain zero, one or several value
# spans (e.g. multiple rooms or several instructors), which shifts every
# following column. Reading the value per cell keeps columns aligned.
_MOBILE_LABEL_CLASS = "lg:hidden"

# Values that look like a time (optionally a range) or a bare date and can never
# be a person. These showed up as staff when table columns were misaligned.
_TIME_ONLY_RE = re.compile(r"^\d{1,2}:\d{2}(?:\s*[-–]\s*\d{1,2}:\d{2})?$")
_DATE_ONLY_RE = re.compile(
    r"^(?:[A-Za-zÄÖÜäöü]{2},?\s*)?\d{1,2}\.\s*[A-Za-zÄÖÜäöü]{3}\.?\s*\d{2,4}$"
)
_NON_STAFF_LABELS = {"k.Terminbuchung", "ohne Termin"}


def _cell_values(cell: Tag) -> list[str]:
    """Return the value texts of a table cell, one entry per outermost value span."""
    spans = [
        span for span in cell.find_all("span")
        if _MOBILE_LABEL_CLASS not in (span.get("class") or [])
    ]
    # Only keep the outermost value spans so nested styling spans are not counted twice.
    outermost = [
        span for span in spans
        if not any(other is not span and other in span.parents for other in spans)
    ]
    source = outermost or spans
    if source:
        return [span.get_text(" ", strip=True) for span in source]
    text = cell.get_text(" ", strip=True)
    return [text] if text else []


def _cell_value(cell: Tag, separator: str = " ") -> str:
    """Return the whitespace-normalised value text of a table cell.

    The mobile-only label span is ignored. If a cell holds several value spans
    (for example multiple rooms or instructors) their texts are joined with
    ``separator``.
    """
    return _WHITESPACE_RE.sub(" ", separator.join(_cell_values(cell))).strip()


def _clean_staff(raw: str) -> list[str]:
    """Split a raw staff string and drop entries that are not names.

    Guards against time ranges/dates/placeholders that leak into the staff
    column when the source table columns are misaligned.
    """
    staff: list[str] = []
    for entry in re.split(r"[,;]", raw):
        entry = _WHITESPACE_RE.sub(" ", entry).strip()
        if not entry:
            continue
        if entry in _NON_STAFF_LABELS:
            continue
        if _TIME_ONLY_RE.match(entry) or _DATE_ONLY_RE.match(entry):
            continue
        if entry not in staff:
            staff.append(entry)
    return staff

def handleCourseList(urls: list[str], cancel_event: Event | None = None, client: ClientLike | None = None, progress_tracker=None, *, store=None, refresh: bool = False, offline: bool = False) -> list[CourseType | None]:
    if not urls:
        return []

    courses_by_index: dict[int, CourseType | None] = {}

    own_client = client is None
    if own_client:
        limits = httpx.Limits(
            max_connections=MAX_CONCURRENT_COURSE_REQUESTS,
            max_keepalive_connections=MAX_CONCURRENT_COURSE_REQUESTS,
        )
        client = create_cached_client(
            limits=limits,
            timeout=15.0,
            store=store,
            refresh=refresh,
            offline=offline,
        )
    assert client is not None

    try:
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_COURSE_REQUESTS) as executor:
            futures = [
                executor.submit(_fetch_and_parse_course, idx, url, client, cancel_event, progress_tracker)
                for idx, url in enumerate(urls)
            ]
            pending = set(futures)
            while pending:
                if _cancelled(cancel_event):
                    break

                done, pending = wait(pending, timeout=0.01, return_when=FIRST_COMPLETED)
                if not done:
                    continue

                for future in done:
                    idx, success, parsed = future.result()
                    if success:
                        courses_by_index[idx] = parsed

            if _cancelled(cancel_event):
                for future in pending:
                    future.cancel()
                executor.shutdown(wait=False, cancel_futures=True)
    finally:
        if own_client:
            client.close()

    return [courses_by_index[idx] for idx in sorted(courses_by_index.keys())]


def _fetch_and_parse_course(index: int, url: str, client: ClientLike, cancel_event: Event | None = None, progress_tracker=None) -> tuple[int, bool, CourseType | None]:
    if _cancelled(cancel_event):
        return index, False, None

    if not url.startswith("http"):
        url = "https://almaweb.uni-leipzig.de" + url
    try:
        response = client.get(url)
    except Exception as e:
        log_warning(
            "course_fetch_error",
            f"An error occurred while fetching details from URL: {url}: {e}",
            url=url,
            error=str(e),
        )
        return index, False, None

    if response.status_code != 200:
        log_warning(
            "course_fetch_status",
            f"Failed to fetch details with status code {response.status_code} from URL: {url}",
            status=response.status_code,
            url=url,
        )
        return index, False, None

    if _cancelled(cancel_event):
        return index, False, None

    try:
        return index, True, parseCourse(response.text, client=client, cancel_event=cancel_event, progress_tracker=progress_tracker)
    except Exception as e:
        # Distinguish a parser bug/value problem from a network failure.
        log_warning(
            "course_parse_error",
            f"An error occurred while parsing details from URL: {url}: {e}",
            url=url,
            error=str(e),
        )
        return index, False, None

def parseCourse(html_content: str, client: ClientLike | None = None, cancel_event: Event | None = None, progress_tracker=None) -> CourseType | None:
    soup = BeautifulSoup(html_content, 'html.parser')
    header = soup.find("h1")
    if not header:
        log_warning("course_header_missing", "Failed to find course header.")
        return None
    header_text = header.get_text(strip=True)
    header_parts = header_text.split(None, 1)
    if len(header_parts) < 2:
        log_warning("course_header_malformed", f"Malformed course header: {header_text!r}", value=header_text)
        number, name = header_text, ""
    else:
        number, name = header_parts
    values = extract_course_values(soup.select_one("#contentlayoutleft"))
    try:
        events = extract_events(find_termine_section(soup.select_one("#contentlayoutright")), name, client=client, cancel_event=cancel_event, progress_tracker=progress_tracker)
    except Exception as e:
        # A single bad row must not drop the whole course.
        log_warning("course_parse_error", f"Failed to parse events for {name}: {e}", course=name, error=str(e))
        events = []
    staff = _clean_staff(values["staff"])

    # Free BeautifulSoup tree and raw HTML after extracting all data
    del soup
    del html_content

    if progress_tracker is not None:
        progress_tracker.increment("courses")

    return {
        "name": name,
        "number": number,
        "staff": staff,
        "type": values["type"],
        "weekly_hours": int(values["weekly_hours"]) if values["weekly_hours"].isdigit() else 0,
        "language": values["language"],
        "org_unit": values["org_unit"],
        "official_description": values["official_description"],
        "organisational": values["organisational"],
        "literature": values["literature"],
        "events": events,
        "status": "almaweb"
    }


def find_termine_section(right_content: Tag | None) -> Tag | None:
    if right_content is None or not isinstance(right_content.parent, Tag):
        return None

    for section in right_content.parent.find_all("div", recursive=False):
        if not isinstance(section, Tag):
            continue
        for child in section.children:
            if isinstance(child, Tag) and "Termine" in child.get_text(" ", strip=True):
                return child

    return None


def extract_course_values(content: Tag | None) -> dict[str, str]:
    values: dict[str, str] = {
        "staff": "",
        "type": "",
        "weekly_hours": "",
        "language": "",
        "org_unit": "",
        "official_description": "",
        "organisational": "",
        "literature": "",
    }
    if content is None:
        return values

    for row in content.select(".tbdata"):
        label_tag = row.find("b", recursive=False)
        if label_tag is None:
            continue
        label = _WHITESPACE_RE.sub(" ", label_tag.get_text(" ", strip=True)).rstrip(":")
        entry = _COURSE_LABEL_MAP.get(label)
        if entry is None:
            # Surface fields the parser does not know about instead of dropping
            # them silently; the audit groups these warnings.
            if label:
                log_warning(
                    "unknown_course_label",
                    f"Unknown course field {label!r}.",
                    label=label,
                )
            continue
        key, tag_name = entry
        tag = row.find(tag_name)
        if tag:
            values[key] = tag.get_text(strip=True)

    return values

def extract_events(content: Tag | None, course_name: str, client: ClientLike | None = None, cancel_event: Event | None = None, progress_tracker=None) -> list[EventType]:
    if content is None:
        log_warning("no_events_content", f"No events content found for course: {course_name}", course=course_name)
        return []

    header = content.find("div", recursive=False)
    if header is not None and header.get_text(" ", strip=True) != "Termine":
        return []

    # Without a caller-provided client (e.g. ``parseCourse`` used directly), use
    # a cached client so room fetches are stored/replayed too, and close it once.
    own_client = client is None
    if own_client:
        client = create_cached_client(timeout=15.0)

    events = []
    for event_row in content.select("table tbody tr"):
        cells = event_row.find_all("td", recursive=False)
        if not cells:
            continue

        by_name = {cell.get("name"): cell for cell in cells if cell.get("name")}
        number_cell = cells[0]
        date_cell = by_name.get("appointmentDate")
        start_cell = by_name.get("appointmentTimeFrom")
        end_cell = by_name.get("appointmentDateTo")
        staff_cell = by_name.get("appointmentInstructors")
        room_cell = next(
            (cell for cell in cells if "rw-course-room" in (cell.get("class") or [])),
            None,
        )

        # Fall back to positional columns for older AlmaWeb markup that does not
        # expose the semantic ``name``/class attributes.
        if date_cell is None or start_cell is None or end_cell is None or staff_cell is None:
            if len(cells) < 6:
                continue
            number_cell, date_cell, start_cell, end_cell, room_cell, staff_cell = cells[:6]

        number = _cell_value(number_cell)
        date_raw = _cell_value(date_cell)
        start_raw = _cell_value(start_cell)
        end_raw = _cell_value(end_cell)
        # A room cell may list several rooms; use the first one for the fallback
        # name / room cache key while the anchor resolves the actual details.
        room_values = _cell_values(room_cell) if room_cell is not None else []
        room_text = _WHITESPACE_RE.sub(" ", room_values[0]).strip() if room_values else ""
        staff_raw = _cell_value(staff_cell, separator=", ")

        room_url = room_cell.find("a", attrs={"name": "appointmentRooms"}) if room_cell is not None else None
        room = None
        if room_url:
            room = fetch_and_parse_room_details(room_url["href"], room_text, client, cancel_event, progress_tracker=progress_tracker)[2]  # type: ignore
            # The source lists a room, but fetching/parsing its detail page failed:
            # keep the room name instead of dropping the location entirely. The room
            # name is later merged with the detailed location if a fetch succeeds.
            if room is None and room_text:
                room = RoomType(name=room_text, external_id="", description="", type="", seats=None, size=None, accessibility="", building=BuildingType(name="", short_name="", address=""))
        else:
            room = RoomType(name=room_text, external_id="", description="", type="", seats=None, size=None, accessibility="", building=BuildingType(name="", short_name="", address="")) if room_text else None
        staff = _clean_staff(staff_raw)

        if progress_tracker is not None:
            progress_tracker.increment("events")

        events.append({
            "number": number,
            "event_date": _parse_date(date_raw),
            "start_time": _parse_time(start_raw),
            "end_time": _parse_time(end_raw),
            "location": room,
            "staff": staff,
        })
    if own_client:
        client.close()
    return events


def _parse_date(value: str) -> date | None:
    # Expected format: Fr, 10. Apr. 2026
    m = re.search(r"(\d{1,2})\.\s*(\w{3})\.?\s*(\d{4})", value)
    if not m:
        log_warning("failed_date", f"Failed to parse date: {value}", value=value)
        return None
    month = _MONTHS.get(m.group(2))
    if month is None:
        log_warning("failed_date", f"Unknown month in date: {value}", value=value)
        return None
    try:
        return date(int(m.group(3)), month, int(m.group(1)))
    except ValueError:
        # e.g. "31. Feb. 2025"; never raise so the surrounding record survives.
        log_warning("invalid_date", f"Invalid date: {value}", value=value)
        return None


def _parse_time(value: str) -> time | None:
    # Expected format: 14:00
    m = re.search(r"(\d{1,2}):(\d{2})", value)
    if not m:
        log_warning("failed_time", f"Failed to parse time: {value}", value=value)
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    # AlmaWeb uses "24:00" to mark the end of a full-day session; represent it as
    # the last minute of the day instead of raising ``time(24, 0)``.
    if hour == 24:
        return time(23, 59)
    if not (0 <= hour <= 23) or not (0 <= minute <= 59):
        log_warning("invalid_time", f"Out-of-range time: {value}", value=value)
        return None
    return time(hour, minute)