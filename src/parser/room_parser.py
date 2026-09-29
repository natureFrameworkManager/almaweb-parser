import hashlib
import re
from collections import OrderedDict
from threading import Event, Lock

from bs4 import BeautifulSoup, Tag
import httpx

try:
    from .utils import _WHITESPACE_RE, _cancelled, log_warning, single_line, text_with_structure
    from .types import RoomType, BuildingType
    from .fetch import ClientLike, get_page_store
except ModuleNotFoundError:
    from src.parser.utils import _WHITESPACE_RE, _cancelled, log_warning, single_line, text_with_structure  # type: ignore
    from src.parser.types import RoomType, BuildingType
    from src.parser.fetch import ClientLike, get_page_store  # type: ignore

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

# Global toggle used by the debug runner (``run_parse --no-rooms``). When
# disabled, room detail pages are never fetched and events keep only the room
# name from the course table.
_fetch_rooms_enabled = True


def set_room_fetch_enabled(enabled: bool) -> None:
    """Enable/disable fetching of room detail pages (process-wide)."""
    global _fetch_rooms_enabled
    _fetch_rooms_enabled = enabled


def is_room_fetch_enabled() -> bool:
    """Return whether room detail pages are currently fetched."""
    return _fetch_rooms_enabled

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

def room_page_key(room_text: str) -> str:
    """Stable page-store key for a room detail page, derived from its display name.

    Room detail URLs are session-scoped (``PRGNAME=ACTION&ARGUMENTS=-A<blob>``) and
    change between crawls, so URL-keyed caching cannot replay them. Keying by the
    room name as well lets a re-parse serve the stored room page offline.
    """
    normalized = _WHITESPACE_RE.sub(" ", (room_text or "").strip()).lower()
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()
    return f"almaweb-room://{digest}"


def fetch_and_parse_room_details(url: str, room_text: str, client: ClientLike, cancel_event: Event, progress_tracker=None) -> tuple[int, bool, RoomType | None]:
    if _cancelled(cancel_event):
        return (0, True, None)
    if not _fetch_rooms_enabled:
        return (0, False, None)

    store = getattr(client, "store", None) or get_page_store()
    refresh = bool(getattr(client, "refresh", False))
    name_key = room_page_key(room_text) if room_text else None

    try:
        cached = _cache_get(room_text)
        if cached is not None:
            return (0, False, cached)

        # Replay by room name first: works offline across crawls even though the
        # session-scoped room URL is not in the store.
        if name_key is not None and not refresh:
            html = store.get(name_key)
            if html is not None:
                room = parseRoom(html)
                if room is not None:
                    _cache_put(room_text, room)
                    return (0, False, room)

        if not url.startswith("http"):
            url = "https://almaweb.uni-leipzig.de" + url

        response = client.get(url)
        response.raise_for_status()
        room = parseRoom(response.text)
        _cache_put(room_text, room)

        # Persist under the room name so future offline re-parses can find it.
        if name_key is not None and room is not None and response.status_code == 200:
            store.put(name_key, response.text, status=response.status_code, headers=response.headers)

        if progress_tracker is not None:
            progress_tracker.increment("rooms")

        return (0, False, room)
    except Exception as e:
        log_warning(
            "room_fetch_error",
            f"Error fetching/parsing room details from {url}: {e}",
            url=url,
            room=room_text,
            error=str(e),
        )
        return (0, False, None)


def backfill_room_name_cache(store=None, progress=None) -> dict[str, int]:
    """Index already-stored room detail pages under their room-name key.

    Room pages fetched before the room-name index existed are keyed by their
    session URL only. This scans the page store, reads each room page's name and
    also stores it under :func:`room_page_key`, so offline re-parses can find it.
    Returns ``{"scanned": n, "indexed": n}``.
    """
    store = store or get_page_store()
    scanned = 0
    indexed = 0
    for url, html_path in store.iter_entries():
        if "PRGNAME=ACTION" not in url:
            continue
        scanned += 1
        try:
            html = html_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        room = parseRoom(html)
        if room and room.get("name"):
            key = room_page_key(room["name"])
            if not store.has(key):
                store.put(key, html, status=200)
                indexed += 1
        if progress is not None and scanned % 200 == 0:
            progress(f"[rooms] indexed {indexed} of {scanned} room pages")
    return {"scanned": scanned, "indexed": indexed}

def parseRoom(html_content: str) -> RoomType | None:
    soup = BeautifulSoup(html_content, "html.parser")
    header = soup.find("h1")
    if not header:
        log_warning("room_header_missing", "Failed to find room header.")
        return None

    dl = soup.find("dl")
    if not dl or not isinstance(dl, Tag):
        log_warning("room_details_missing", "Failed to find room details list.")
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

    # Free BeautifulSoup tree and raw HTML after extracting all data
    del soup
    del html_content

    return room


def _extract_room_values(dl: Tag) -> dict[str, str]:
    values: dict[str, str] = {}
    for row in dl.find_all("div", recursive=False):
        dt = row.find("dt", recursive=False)
        dd = row.find("dd", recursive=False)
        if dt is None or dd is None:
            continue
        label = single_line(dt.get_text(" ", strip=True))
        key = _ROOM_LABEL_MAP.get(label)
        if key is not None:
            values[key] = text_with_structure(dd)
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
        label = single_line(dt.get_text(" ", strip=True))
        key = label_map.get(label)
        if key is None:
            continue
        structured = text_with_structure(dd)
        if key == "address":
            # An address is one line; its ``<br>`` separated parts are joined
            # back with ", " (the previous behaviour).
            values[key] = structured.replace("\n", ", ")
        else:
            values[key] = structured
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