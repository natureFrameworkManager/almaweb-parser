from typing import TypedDict
import re
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import date, time
from threading import Event

import httpx
from bs4 import BeautifulSoup, Tag

try:
    from .utils import _WHITESPACE_RE, _cancelled
    from .types import CourseType, EventType, RoomType, BuildingType
    from .room_parser import fetch_and_parse_room_details
except ModuleNotFoundError:
    from src.parser.utils import _WHITESPACE_RE, _cancelled
    from src.parser.types import CourseType, EventType, RoomType, BuildingType
    from src.parser.room_parser import fetch_and_parse_room_details

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
}

def handleCourseList(urls: list[str], cancel_event: Event | None = None, client: httpx.Client | None = None, progress_tracker=None) -> list[CourseType | None]:
    if not urls:
        return []

    courses_by_index: dict[int, CourseType | None] = {}

    own_client = client is None
    if own_client:
        limits = httpx.Limits(
            max_connections=MAX_CONCURRENT_COURSE_REQUESTS,
            max_keepalive_connections=MAX_CONCURRENT_COURSE_REQUESTS,
        )
        client = httpx.Client(limits=limits, timeout=15.0)
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


def _fetch_and_parse_course(index: int, url: str, client: httpx.Client, cancel_event: Event | None = None, progress_tracker=None) -> tuple[int, bool, CourseType | None]:
    try:
        if _cancelled(cancel_event):
            return index, False, None

        if not url.startswith("http"):
            url = "https://almaweb.uni-leipzig.de" + url
        response = client.get(url)
        if response.status_code == 200:
            if _cancelled(cancel_event):
                return index, False, None
            return index, True, parseCourse(response.text, client=client, progress_tracker=progress_tracker)

        print(f"Failed to fetch details with status code {response.status_code} from URL: {url}")
    except Exception as e:
        print(f"An error occurred while fetching details from URL: {url}: {e}")

    return index, False, None

def parseCourse(html_content: str, client: httpx.Client | None = None, progress_tracker=None) -> CourseType | None:
    soup = BeautifulSoup(html_content, 'html.parser')
    header = soup.find("h1")
    if not header:
        print("Failed to find course header.")
        return None
    number, name = header.get_text(strip=True).split(None, 1)
    values = extract_course_values(soup.select_one("#contentlayoutleft"))
    events = extract_events(find_termine_section(soup.select_one("#contentlayoutright")), name, client=client, progress_tracker=progress_tracker)
    staff = [s.strip() for s in re.split(r"[,;]", values["staff"]) if s.strip()]

    if progress_tracker is not None:
        progress_tracker.increment("courses")

    return {
        "name": name,
        "number": number,
        "staff": staff,
        "type": values["type"],
        "weekly_hours": int(values["weekly_hours"]) if values["weekly_hours"].isdigit() else 0,
        "language": values["language"],
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
    values: dict[str, str] = {"staff": "", "type": "", "weekly_hours": "", "language": ""}
    if content is None:
        return values

    for row in content.select(".tbdata"):
        label_tag = row.find("b", recursive=False)
        if label_tag is None:
            continue
        label = _WHITESPACE_RE.sub(" ", label_tag.get_text(" ", strip=True)).rstrip(":")
        entry = _COURSE_LABEL_MAP.get(label)
        if entry is None:
            continue
        key, tag_name = entry
        tag = row.find(tag_name)
        if tag:
            values[key] = tag.get_text(strip=True)

    return values

def extract_events(content: Tag | None, course_name: str, client: httpx.Client | None = None, progress_tracker=None) -> list[EventType]:
    if content is None:
        print(f"No events content found for course: {course_name}")
        return []

    header = content.find("div", recursive=False)
    if header is not None and header.get_text(" ", strip=True) != "Termine":
        return []

    events = []
    for event_row in content.select("table tbody tr"):
        cells = [
            span for span in event_row.select("td span")
            if "lg:hidden" not in (span.get("class") or [])
        ]
        if len(cells) < 6:
            continue
        number, date_raw, start_raw, end_raw, room_text, staff_raw = [
            cell.get_text(" ", strip=True) for cell in cells[:6]
        ]
        room_url = cells[4].find("a", attrs={"name": "appointmentRooms"})
        room = None
        if room_url:
            room = fetch_and_parse_room_details(room_url["href"], room_text, client or httpx.Client(), None, progress_tracker=progress_tracker)[2]  # type: ignore
        else:
            room = RoomType(name=room_text, external_id="", description="", type="", seats=None, size=None, accessibility="", building=BuildingType(name="", short_name="", address="")) if room_text else None
        staff = [s.strip() for s in re.split(r"[,;]", staff_raw) if s.strip()]

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
    return events


def _parse_date(value: str) -> date | None:
    # Expected format: Fr, 10. Apr. 2026
    m = re.search(r"(\d{1,2})\.\s*(\w{3})\.?\s*(\d{4})", value)
    if not m:
        print(f"Failed to parse date: {value}")
        return None
    return date(int(m.group(3)), _MONTHS.get(m.group(2), 0), int(m.group(1)))


def _parse_time(value: str) -> time | None:
    # Expected format: 14:00
    m = re.search(r"(\d{1,2}):(\d{2})", value)
    if not m:
        print(f"Failed to parse time: {value}")
        return None
    return time(int(m.group(1)), int(m.group(2)))