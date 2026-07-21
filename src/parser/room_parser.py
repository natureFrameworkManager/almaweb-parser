import re
from collections import OrderedDict
from threading import Event, Lock

from bs4 import BeautifulSoup, Tag
import httpx

try:
    from .utils import _WHITESPACE_RE, _cancelled
    from .types import RoomType, BuildingType
except ModuleNotFoundError:
    from src.parser.utils import _WHITESPACE_RE, _cancelled
    from src.parser.types import RoomType, BuildingType

# German label -> dict key for room-level fields
_ROOM_LABEL_MAP: dict[str, str] = {
    "Name":            "name",
    "Externe Kennung": "external_id",
    "Beschreibung":    "description",
    "Raumtyp":         "type",
    "Plätze":          "seats",
    "Größe (qm)":     "size",
    "Barrierefrei":    "accessibility",
}

# German label -> dict key for building fields
_BUILDING_LABEL_MAP: dict[str, str] = {
    "Name":    "name",
    "Kürzel":  "short_name",
    "Adresse": "address",
}

# Thread-safe LRU cache for room details to prevent unbounded memory growth.
# Uses OrderedDict for O(1) move-to-end operations.
_MAX_CACHED_ROOMS = 2000
cached_rooms: OrderedDict[str, RoomType | None] = OrderedDict()
_cached_rooms_lock = Lock()

def _cache_get(key: str) -> RoomType | None | None:
    """Thread-safe lookup in the LRU room cache. Returns the cached value or None."""
    with _cached_rooms_lock:
        if key in cached_rooms:
            # Move to end (most recently used)
            cached_rooms.move_to_end(key)
            return cached_rooms[key]
        return None

def _cache_put(key: str, value: RoomType | None) -> None:
    """Thread-safe insert into the LRU room cache, evicting oldest if at capacity."""
    with _cached_rooms_lock:
        if key in cached_rooms:
            cached_rooms.move_to_end(key)
            cached_rooms[key] = value
        else:
            if len(cached_rooms) >= _MAX_CACHED_ROOMS:
                cached_rooms.popitem(last=False)
            cached_rooms[key] = value

def fetch_and_parse_room_details(url: str, room_text: str, client: httpx.Client, cancel_event: Event, progress_tracker=None) -> tuple[int, bool, RoomType | None]:
    if _cancelled(cancel_event):
        return (0, True, None)

    try:
        cached = _cache_get(room_text)
        if cached is not None:
            return (0, False, cached)
        if not url.startswith("http"):
            url = "https://almaweb.uni-leipzig.de" + url

        response = client.get(url)
        response.raise_for_status()
        room = parseRoom(response.text)
        _cache_put(room_text, room)

        if progress_tracker is not None:
            progress_tracker.increment("rooms")

        return (0, False, room)
    except Exception as e:
        print(f"Error fetching/parsing room details from {url}: {e}")
        return (0, False, None)

def parseRoom(html_content: str) -> RoomType | None:
    soup = BeautifulSoup(html_content, "html.parser")
    header = soup.find("h1")
    if not header:
        print("Failed to find room header.")
        return None

    dl = soup.find("dl")
    if not dl or not isinstance(dl, Tag):
        print("Failed to find room details list.")
        return None

    room_values = _extract_room_values(dl)
    building_values = _extract_section_values(dl, "Gebäude", _BUILDING_LABEL_MAP)

    building: BuildingType = {
        "name": building_values.get("name", ""),
        "short_name": building_values.get("short_name", ""),
        "address": building_values.get("address", ""),
    }

    room: RoomType = {
        "name": room_values.get("name", ""),
        "external_id": room_values.get("external_id", ""),
        "description": room_values.get("description", ""),
        "type": room_values.get("type", ""),
        "seats": _parse_int_or_none(room_values.get("seats", "")),
        "size": _parse_float_or_none(room_values.get("size", "")),
        "accessibility": room_values.get("accessibility", ""),
        "building": building,
    }

    return room


def _extract_room_values(dl: Tag) -> dict[str, str]:
    values: dict[str, str] = {}
    for row in dl.find_all("div", recursive=False):
        dt = row.find("dt", recursive=False)
        dd = row.find("dd", recursive=False)
        if dt is None or dd is None:
            continue
        label = _WHITESPACE_RE.sub(" ", dt.get_text(" ", strip=True))
        key = _ROOM_LABEL_MAP.get(label)
        if key is not None:
            values[key] = _WHITESPACE_RE.sub(" ", dd.get_text(" ", strip=True))
    return values


def _extract_section_values(dl: Tag, section_name: str, label_map: dict[str, str]) -> dict[str, str]:
    values: dict[str, str] = {}
    section = _find_section(dl, section_name)
    if section is None:
        return values

    for row in section.find_all("div", class_="sm:grid"):
        dt = row.find("dt")
        dd = row.find("dd")
        if dt is None or dd is None:
            continue
        label = _WHITESPACE_RE.sub(" ", dt.get_text(" ", strip=True))
        key = label_map.get(label)
        if key is None:
            continue
        if key == "address":
            values[key] = dd.get_text(", ", strip=True)
        else:
            values[key] = _WHITESPACE_RE.sub(" ", dd.get_text(" ", strip=True))
    return values


def _find_section(dl: Tag, section_name: str) -> Tag | None:
    for div in dl.find_all("div", class_="py-3", recursive=False):
        heading = div.find("div", class_="font-bold")
        if heading and section_name in heading.get_text(" ", strip=True):
            return div
    return None


def _parse_int_or_none(value: str) -> int | None:
    match = re.search(r"-?\d+", value)
    return int(match.group(0)) if match else None


def _parse_float_or_none(value: str) -> float | None:
    normalized = value.replace(" ", "").replace(",", ".")
    match = re.search(r"-?\d+(?:\.\d+)?", normalized)
    return float(match.group(0)) if match else None