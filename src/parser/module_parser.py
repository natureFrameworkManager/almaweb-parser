import logging
import re
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from threading import Event
from typing import TYPE_CHECKING

import httpx
from bs4 import BeautifulSoup, Tag

from .course_parser import handleCourseList, MAX_CONCURRENT_COURSE_REQUESTS
from ..database.database import insert_module_graph

if TYPE_CHECKING:
    from .crawler import ModuleLink

MAX_CONCURRENT_MODULE_REQUESTS = 4

_WHITESPACE_RE = re.compile(r"\s+")

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


def _silence_httpx_logs() -> None:
    for name in ("httpx", "httpcore", "httpcore.http11", "httpcore.connection"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = False
        logger.setLevel(logging.CRITICAL + 1)
        logger.disabled = True


_silence_httpx_logs()


def _cancelled(cancel_event: Event | None) -> bool:
    return cancel_event is not None and cancel_event.is_set()


def handleModuleList(moduleList: list["ModuleLink"], cancel_event: Event | None = None):
    if not moduleList:
        return []

    parsed_by_index: dict[int, dict] = {}

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
                executor.submit(_fetch_and_parse_module, idx, module, client, cancel_event)
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
                        insert_module_graph(parsed)

            if _cancelled(cancel_event):
                for future in pending:
                    future.cancel()
                executor.shutdown(wait=False, cancel_futures=True)

    modules = [parsed_by_index[idx] for idx in sorted(parsed_by_index.keys())]

    if _cancelled(cancel_event):
        print(f"Saved {len(modules)} parsed modules before interruption.")

    return modules


def _fetch_and_parse_module(index: int, module: "ModuleLink", client: httpx.Client, cancel_event: Event | None = None) -> tuple[int, dict | None]:
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
            return index, parseModule(response.text, path=module.path, client=client, cancel_event=cancel_event)

        print(f"Failed to fetch details for {module.name} with status code {response.status_code} from URL: {url}")
    except Exception as e:
        print(f"An error occurred while fetching details for {module.name} under URL: {module.url}: {e}")

    return index, None


def parseModule(html_content: str, path: list[str], client: httpx.Client | None = None, cancel_event: Event | None = None) -> dict | None:
    if _cancelled(cancel_event):
        return None

    soup = BeautifulSoup(html_content, 'html.parser')
    header = soup.find("h1")
    if not header:
        print("Failed to find module header.")
        return None
    number, name = header.get_text(strip=True).split(None, 1)
    values = extract_module_values(soup.select_one("#contentlayoutleft"))
    course_urls = [
        str(a["href"])
        for a in soup.find_all("a", attrs={"name": "eventLink"})
        if "COURSEDETAILS" in a["href"]
    ]
    courses = handleCourseList(course_urls, cancel_event=cancel_event, client=client)

    module = {
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
    }
    print(f"Parsed module {module['number']} - {module['name']}. Includes {len(module['courses'])} courses and {sum(len(course['events']) for course in module['courses'])} events.")
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