import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag
import httpx

@dataclass
class CourseEvent:
    number: str
    date: str
    start_time: str
    end_time: str
    location: str
    staff: list[str]
    
@dataclass
class Course:
    staff: list[str]
    type: str
    weekly_hours: int
    language: str
    events: list[CourseEvent]

def handleCourseList(urls: list[str]):
    courses = []
    for url in urls:
        try:
            if not url.startswith("http"):
                url = "https://almaweb.uni-leipzig.de" + url
            response = httpx.get(url)
            if response.status_code == 200:
                courses.append(parseCourse(response.text))
            else:
                print(f"Failed to fetch details with status code {response.status_code} from URL: {url}")
        except Exception as e:
            print(f"An error occurred while fetching details from URL: {url}: {e}")
    return courses

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
    # TODO: fix div select based on title "Termine" instead of fixed position
    # As the "Anmeldefristen" section can appear before "Termine" for some courses, we need to find the correct div based on its header
    events_container = right_content.parent.find_all("div", recursive=False)[2] if right_content and isinstance(right_content.parent, Tag) else None
    events_content = events_container.find("div", recursive=False) if events_container else None
    events = extract_events(events_content)
    course = Course(
        staff=values["staff"].split(", ") if values["staff"] else [],
        type=values["type"],
        weekly_hours=int(values["weekly_hours"]) if values["weekly_hours"].isdigit() else 0,
        language=values["language"],
        events=events
    )
    return course
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
        number, date, start_time, end_time, location, staff_text = values
        staff = [name.strip() for name in re.split(r"[,;]", staff_text) if name.strip()]
        events.append(CourseEvent(number, date, start_time, end_time, location, staff))
    return events