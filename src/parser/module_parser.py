import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag
import httpx
from .crawler import ModuleLink
from .course_parser import Course, handleCourseList

@dataclass
class Module:
    name: str
    number: str
    path: list[str]
    responsible_person: str
    duration_semesters: int
    credits: float
    start_semester: str
    frequency: str
    goals: str
    content: str
    exam_prerequisites: str
    prerequisites: dict[str, str]
    courses: list[Course]

def handleModuleList(moduleList: list[ModuleLink]):
    modules = []
    for module in moduleList:
        try:
            if not module.url.startswith("http"):
                module.url = "https://almaweb.uni-leipzig.de" + module.url
            response = httpx.get(module.url)
            if response.status_code == 200:
                parsed = parseModule(response.text, path=module.path)
                if parsed is not None:
                    modules.append(parsed)
            else:
                print(f"Failed to fetch details for {module.name} with status code {response.status_code} from URL: {module.url}")
        except Exception as e:
            print(f"An error occurred while fetching details for {module.name} under URL: {module.url}: {e}")
    return modules

def parseModule(html_content: str, path: list[str]) -> Module | None:
    soup = BeautifulSoup(html_content, 'html.parser')
    # Extract module details using BeautifulSoup
    header = soup.find("h1")
    if not header:
        print("Failed to find module header.")
        return None
    number, name = header.get_text(strip=True).split(None, 1)
    values = extract_module_values(soup.select_one("#contentlayoutleft"))
    courses = []
    course_urls = [str(course['href']) for course in soup.find_all("a", attrs={"name": "eventLink"}) if "COURSEDETAILS" in course['href']]
    courses.extend(handleCourseList(course_urls))

    module = Module(
        name=name,
        number=number,
        path=path,
        responsible_person=values["responsible_person"],
        duration_semesters=parse_int(values["duration_semesters"]),
        credits=parse_float(values["credits"]),
        start_semester=values["start_semester"],
        frequency=values["frequency"],
        goals=values["goals"],
        content=values["content"],
        exam_prerequisites=values["exam_prerequisites"],
        prerequisites=parse_prerequisites(values["prerequisites"]),
        courses=courses,
    )
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
        label = re.compile(r"\s+").sub(" ", label_tag.get_text(" ", strip=True)).rstrip(":")
        if not label:
            continue
        value_tag = label_tag.find_next_sibling("div")
        if value_tag is None:
            continue
        value = re.compile(r"\s+").sub(" ", value_tag.get_text(" ", strip=True))

        if label == "Modulverantwortliche":
            values["responsible_person"] = value
            continue
        if label == "Dauer":
            values["duration_semesters"] = value
            continue
        if label == "Leistungspunkte":
            values["credits"] = value
            continue
        if label == "Startsemester":
            values["start_semester"] = value
            continue
        if label == "Turnus":
            values["frequency"] = value
            continue
        if label == "Ziele":
            values["goals"] = value
            continue
        if label == "Inhalt":
            values["content"] = value
            continue
        if label == "Prüfungsvorleistungen":
            values["exam_prerequisites"] = value
            continue
        if label == "Teilnahmevoraussetzungen":
            values["prerequisites"] = value

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
    if not parts:
        parts = [value.strip()]

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