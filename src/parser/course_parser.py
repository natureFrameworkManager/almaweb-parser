import re
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import date, time
from threading import Event

from bs4 import BeautifulSoup, Tag
import httpx
import logging

MAX_CONCURRENT_COURSE_REQUESTS = 8

def _silence_httpx_logs() -> None:
    for name in ("httpx", "httpcore", "httpcore.http11", "httpcore.connection"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = False
        logger.setLevel(logging.CRITICAL + 1)
        logger.disabled = True


_silence_httpx_logs()

months = {
    "Jan": 1,
    "Feb": 2,
    "Mär": 3,
    "Apr": 4,
    "Mai": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Okt": 10,
    "Nov": 11,
    "Dez": 12
}

@dataclass
class CourseEvent:
    number: str
    event_date: None | date
    start_time: None | time
    end_time: None | time
    location: str
    staff: list[str]
    
@dataclass
class Course:
    name: str
    number: str
    staff: list[str]
    type: str
    weekly_hours: int
    language: str
    events: list[CourseEvent]

def handleCourseList(urls: list[str], cancel_event: Event | None = None):
    if not urls:
        return []

    _silence_httpx_logs()

    courses_by_index: dict[int, Course | None] = {}

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_COURSE_REQUESTS) as executor:
        futures = [
            executor.submit(_fetch_and_parse_course, idx, url, cancel_event)
            for idx, url in enumerate(urls)
        ]
        pending = set(futures)
        while pending:
            if cancel_event is not None and cancel_event.is_set():
                break

            done, pending = wait(pending, timeout=0.01, return_when=FIRST_COMPLETED)
            if not done:
                continue

            for future in done:
                idx, success, parsed = future.result()
                if success:
                    courses_by_index[idx] = parsed

        if cancel_event is not None and cancel_event.is_set():
            for future in pending:
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)

    return [courses_by_index[idx] for idx in sorted(courses_by_index.keys())]


def _fetch_and_parse_course(index: int, url: str, cancel_event: Event | None = None) -> tuple[int, bool, Course | None]:
    try:
        if cancel_event is not None and cancel_event.is_set():
            return index, False, None

        if not url.startswith("http"):
            url = "https://almaweb.uni-leipzig.de" + url
        response = httpx.get(url, timeout=15.0)
        if response.status_code == 200:
            if cancel_event is not None and cancel_event.is_set():
                return index, False, None
            return index, True, parseCourse(response.text)

        print(f"Failed to fetch details with status code {response.status_code} from URL: {url}")
    except Exception as e:
        print(f"An error occurred while fetching details from URL: {url}: {e}")

    return index, False, None

def parseCourse(html_content: str):
    soup = BeautifulSoup(html_content, 'html.parser')
    # Extract course details using BeautifulSoup
    header = soup.find("h1")
    if not header:
        print("Failed to find course header.")
        return None
    number, name = header.get_text(strip=True).split(None, 1)
    values = extract_course_values(soup.select_one("#contentlayoutleft"))
    right_content = soup.select_one("#contentlayoutright")
    events_content = find_termine_section(right_content)
    events = extract_events(events_content)
    course = Course(
        name=name,
        number=number,
        staff=values["staff"].split(", ") if values["staff"] else [],
        type=values["type"],
        weekly_hours=int(values["weekly_hours"]) if values["weekly_hours"].isdigit() else 0,
        language=values["language"],
        events=events
    )
    return course


def find_termine_section(right_content: Tag | None) -> Tag | None:
    if right_content is None or not isinstance(right_content.parent, Tag):
        return None

    for section in right_content.parent.find_all("div", recursive=False):
        if not isinstance(section, Tag):
            continue

        for child in section.children:
            if isinstance(child, Tag):
                # Check if the first div contains the header "Termine"
                if child and (child.get_text(" ", strip=True) == "Termine" or "Termine" in child.get_text(" ", strip=True)):
                    return child

    print("Failed to find 'Termine' section in course page.")
    return None


def extract_course_values(content: Tag | None) -> dict[str, str]:
    values: dict[str, str] = {
        "staff": "",
        "type": "",
        "weekly_hours": "",
        "language": ""
    }
    if content is None:
        return values
    for row in content.select(".tbdata"):
        label_tag = row.find("b", recursive=False)
        if label_tag is None:
            continue
        label = re.compile(r"\s+").sub(" ", label_tag.get_text(" ", strip=True)).rstrip(":")
        if not label:
            continue
        if label == "Lehrende":
            span = row.find("span")
            if span:
                values["staff"] = span.get_text(strip=True)
            continue
        if label == "Veranstaltungsart":
            div = row.find("div")
            if div:
                values["type"] = div.get_text(strip=True)
            continue
        if label == "Semesterwochenstunden":
            div = row.find("div")
            if div:
                values["weekly_hours"] = div.get_text(strip=True)
            continue
        if label == "Unterrichtssprache":
            span = row.find("span")
            if span:
                values["language"] = span.get_text(strip=True)
    return values

def extract_events(content: Tag | None) -> list[CourseEvent]:
    events = []
    if content is None:
        print("No events content found for course.")
        return events
    header = content.find("div", recursive=False)
    if header is not None and header.get_text(" ", strip=True) != "Termine":
        return events
    for event_row in content.select("table tbody tr"):
        cells = [span for span in event_row.select("td span") if "lg:hidden" not in (span.get("class") or [])]
        if len(cells) < 6:
            continue
        values = [cell.get_text(" ", strip=True) for cell in cells[:6]]
        number, date_str, start_time, end_time, location, staff_text = values
        # Try parse date and time, if fails use strings
        # date format: Fr, 10. Apr. 2026
        # time format: 14:00
        date_search = re.search(r"(\d{1,2})\.\s*(\w{3})\.?\s*(\d{4})", date_str)
        if date_search:
            date_str = date(int(date_search.group(3)), months.get(date_search.group(2), 0), int(date_search.group(1)))
        else:
            print(f"Failed to parse date: {date_str}")
            date_str = None
        start_time_search = re.search(r"(\d{1,2}):(\d{2})", start_time)
        if start_time_search:
            start_time = time(int(start_time_search.group(1)), int(start_time_search.group(2)))
        else:
            print(f"Failed to parse start time: {start_time}")
            start_time = None
        end_time_search = re.search(r"(\d{1,2}):(\d{2})", end_time)
        if end_time_search:
            end_time = time(int(end_time_search.group(1)), int(end_time_search.group(2)))
        else:
            print(f"Failed to parse end time: {end_time}")
            end_time = None
        staff = [name.strip() for name in re.split(r"[,;]", staff_text) if name.strip()]
        events.append(CourseEvent(number=number, event_date=date_str, start_time=start_time, end_time=end_time, location=location, staff=staff))
    return events