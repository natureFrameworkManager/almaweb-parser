# Bugs & Missing Implementations

---

## Bugs

### 1. Unclosed `httpx.Client` in `extract_events`
**File:** `src/parser/course_parser.py`  
A new `httpx.Client()` is created inline per room fetch (`fetch_and_parse_room_details(room_url["href"], room_text, httpx.Client(), None)`) and never closed — resource leak per event row that has a room URL.

---

### 2. Wrong dict key `'room'` in room-count log line
**File:** `src/parser/module_parser.py`  
`event.get('room')` is used, but `EventType` stores the location under key `'location'`. The room count will always be 0.

---

### 3. `Course.type` and `Course.staff` filters call `.ilike()` on non-string columns
**File:** `src/api/routers/courses.py`  
`Course.type` is an `int` foreign-key column and `Course.staff` is a relationship — calling `.ilike()` on either will raise a runtime error when those query params are supplied.

---

### 4. `Course.module_id` / `Course.module` don't exist
**File:** `src/api/routers/courses.py`  
The `module_id` and `module_name`/`module_number` filters reference `Course.module_id` and `Course.module`, neither of which exist on the model (it uses a many-to-many join via `ModuleCourseLink`). Both filter branches will crash at runtime.

---

### 5. Building name/address filters reference `Location` instead of `Building`
**File:** `src/api/routers/events.py`  
`building` filter uses `Location.name.ilike(...)` and `building_address` uses `Location.address.ilike(...)`. Both should reference `Building.name` and `Building.address` respectively.

---

### 6. `Event.location is not None` is a Python identity check, not SQL
**File:** `src/api/routers/events.py`  
`and_(Event.location is not None, ...)` is always `True` at the Python level (the InstrumentedAttribute object is never `None`). The correct SQLAlchemy expression is `Event.location_id.isnot(None)` or `Event.location_id != None`.

---

### 7. `Module.start_semester` filter calls `.ilike()` on a relationship
**File:** `src/api/routers/modules.py`  
`Module.start_semester` is a `list[Semester]` relationship, not a string column. The `.ilike()` call will raise a runtime error when the `start_semester` query param is used.

---

### 8. `asyncio.get_event_loop()` deprecated in Python 3.10+
**File:** `src/api/routers/admin.py`  
`loop = asyncio.get_event_loop()` is deprecated and will emit a DeprecationWarning (and in some contexts raise) in Python 3.10+. Should be `asyncio.get_running_loop()`.

---

### 9. `cached_rooms` module-level dict is not thread-safe
**File:** `src/parser/room_parser.py`  
`cached_rooms` is read and written from multiple threads (via `ThreadPoolExecutor`) without any lock, which can cause a `RuntimeError` on dict size change or return stale/corrupted data under concurrent access.

---

### 15. Unknown month abbreviation causes `ValueError` in `_parse_date`
**File:** `src/parser/course_parser.py`  
`_MONTHS.get(m.group(2), 0)` returns `0` when the month abbreviation is not in the map. Passing `0` to `date(year, 0, day)` raises `ValueError` (month must be 1–12) instead of returning `None` gracefully.

---

### 16. `parse_prerequisites` silently overwrites the `"allgemein"` key
**File:** `src/parser/module_parser.py`  
When multiple prerequisite lines contain no `":"`, every one writes to `prerequisites["allgemein"]`, so only the last survives. All earlier lines are silently discarded.

---

### 17. Unguarded header split raises `ValueError` on single-token headers
**Files:** `src/parser/course_parser.py`, `src/parser/module_parser.py`  
`number, name = header.get_text(strip=True).split(None, 1)` raises `ValueError` if the header text contains no whitespace (i.e. is a single token). There is no try/except around this call in either parser.

---

### 18. `_cancelled` import in `room_parser` has no relative fallback
**File:** `src/parser/room_parser.py`  
`from src.parser.utils import _cancelled` is an unconditional absolute import at the top of the file. Every other symbol in the file is imported via a `try/except ModuleNotFoundError` pattern to handle both relative and absolute import contexts. `_cancelled` is missing this fallback and will fail when the module is loaded via relative imports (e.g. during the crawl).

---

### 19. 2-digit semester year stored as-is (e.g. 26 instead of 2026)
**File:** `src/database/database.py`  
`re.search(r"\d{2,4}", path_element)` on a path element like `"SoSe 26"` extracts `26`, so `semester_year` is stored as `26` rather than `2026`. The pattern allows 2-digit matches without expanding them to 4-digit years.

---

## Missing / Incomplete Implementations

### 10. Only the first semester node is ever followed
**File:** `src/parser/crawler.py`  
`for anchor in [semesterNodes[0]]:` — the list slice hard-codes a single element, so only the first matching semester is crawled. All other semesters are silently ignored.

---

### 11. Crawler hard-coded to one faculty
**File:** `src/parser/crawler.py`  
Navigation links are only followed when the name starts with `"10 - Fakultät für Mathematik und Informatik"` (or the breadcrumb already contains it). All other faculties are discovered (`found_faculties`) but never crawled.

---

### 12. Several declared query params in `/modules` are never applied
**File:** `src/api/routers/modules.py`  
The following parameters are accepted by the endpoint but never translated into `WHERE` clauses: `id`, `language`, `degree_id`, `faculty_id`, `semester_id`, `course_id`, `has_courses`, `has_events`, `has_staff`.

---

### 13. `accessible` filter parameter declared but never applied
**File:** `src/api/routers/locations.py`  
`accessible: bool | None` is a declared query parameter but no corresponding `query = query.where(...)` is ever added, so the filter has no effect.

---

### 14. Module `language` field never parsed or stored
**Files:** `src/parser/types.py`, `src/parser/module_parser.py`  
`ModuleType` has no `language` key and `_LABEL_MAP` has no entry for it, so the database `Module.language` column always stays empty even though AlmaWeb exposes the teaching language on the module detail page.

---

### 20. Class-level mutable lists on `LectureSpider` are shared across instances
**File:** `src/parser/crawler.py`  
`found_modules: list[ModuleLink] = []` and `found_faculties: list[dict] = []` are class-level attributes, not instance attributes. If Scrapy ever instantiates the spider more than once, both instances mutate the same list, causing duplicate or mixed data.

---

### 21. `split_by_day` ordering is appended after user sort instead of taking priority
**File:** `src/api/routers/schedule.py`  
When `split_by_day=True`, `query.order_by(weekday_col)` is added *after* the user-specified `sort_query`. The weekday becomes a tiebreaker instead of the primary sort, so the response is not actually split by day as the parameter name suggests.

---

### 22. `weekday` filter documentation inconsistency between `/events` and `/schedule/weekly`
**File:** `src/api/routers/events.py`  
The `weekday` parameter description on `/events` says `"0=Sunday, 1=Monday, …, 6=Saturday"`, but the conversion `(day + 1) % 7` treats `0` as Monday — the same convention used (and correctly documented) in `/schedule/weekly`. The doc string for `/events` is wrong, causing the filter to behave differently from what the API documentation states.
