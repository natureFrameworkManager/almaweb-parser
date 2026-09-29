# Bugs & Missing Implementations

---

## Bugs

### ✅ 1. Unclosed `httpx.Client` in `extract_events`
**File:** `src/parser/course_parser.py`  
A new `httpx.Client()` is created inline per room fetch (`fetch_and_parse_room_details(room_url["href"], room_text, httpx.Client(), None)`) and never closed — resource leak per event row that has a room URL.

---

### ✅ 2. Wrong dict key `'room'` in room-count log line
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

### ✅ 7. `Module.start_semester` filter calls `.ilike()` on a relationship
**File:** `src/api/routers/modules.py`  
`Module.start_semester` is a `list[Semester]` relationship, not a string column. The `.ilike()` call will raise a runtime error when the `start_semester` query param is used.

---

### 8. `asyncio.get_event_loop()` deprecated in Python 3.10+
**File:** `src/api/routers/admin.py`  
`loop = asyncio.get_event_loop()` is deprecated and will emit a DeprecationWarning (and in some contexts raise) in Python 3.10+. Should be `asyncio.get_running_loop()`.

---

### ✅ 9. `cached_rooms` module-level dict is not thread-safe
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

### ✅ 18. `_cancelled` import in `room_parser` has no relative fallback
**File:** `src/parser/room_parser.py`  
`from src.parser.utils import _cancelled` is an unconditional absolute import at the top of the file. Every other symbol in the file is imported via a `try/except ModuleNotFoundError` pattern to handle both relative and absolute import contexts. `_cancelled` is missing this fallback and will fail when the module is loaded via relative imports (e.g. during the crawl).

---

### 19. 2-digit semester year stored as-is (e.g. 26 instead of 2026)
**File:** `src/database/database.py`  
`re.search(r"\d{2,4}", path_element)` on a path element like `"SoSe 26"` extracts `26`, so `semester_year` is stored as `26` rather than `2026`. The pattern allows 2-digit matches without expanding them to 4-digit years.

---

## Missing / Incomplete Implementations

### ✅ 10. Only the first semester node is ever followed
**File:** `src/parser/crawler.py`  
`for anchor in [semesterNodes[0]]:` — the list slice hard-codes a single element, so only the first matching semester is crawled. All other semesters are silently ignored.

---

### ✅ 11. Crawler hard-coded to one faculty
**File:** `src/parser/crawler.py`  
Navigation links are only followed when the name starts with `"10 - Fakultät für Mathematik und Informatik"` (or the breadcrumb already contains it). All other faculties are discovered (`found_faculties`) but never crawled.

---

### ✅ 12. Several declared query params in `/modules` are never applied
**File:** `src/api/routers/modules.py`  
**Fixed:** every declared filter is now translated into a `WHERE` clause — `id`, `language`, `degree_id`, `faculty_id`, `semester_id`, `course_id`, `staff_id`, `responsible_person`, `start_semester`, `has_courses`, `has_events`, `has_staff`. Note that `language` is still a no-op *in practice* because the underlying column is never populated (see #14); its parameter description is now explicitly marked `NOT IMPLEMENTED` so the OpenAPI docs do not advertise behaviour that cannot work yet.

---

### ✅ 13. `accessible` filter parameter declared but never applied
**File:** `src/api/routers/locations.py`  
**Fixed:** the filter is applied **and** now matches the right token. It previously looked for `%barrierefrei%`, but the parser stores `accessibility` as `"Ja"` / `"Nein"` / `""`, so `accessible=true` returned **0** rows and `accessible=false` returned **all 758**. The predicate now accepts `"ja"` as well as the legacy German `"barrierefrei"` text (excluding `"nicht …"`), yielding **145** accessible / **613** not-accessible-or-unknown.

---

### 14. Module `language` field never parsed or stored
**Files:** `src/parser/types.py`, `src/parser/module_parser.py`  
`ModuleType` has no `language` key and `_LABEL_MAP` has no entry for it, so the database `Module.language` column always stays empty even though AlmaWeb exposes the teaching language on the module detail page.

**Impact on the API:** `/modules?language=…` therefore matches no rows with the current data. The query parameter is still accepted (it will work once the column is populated) but its OpenAPI description is now explicitly marked `NOT IMPLEMENTED` in `src/api/routers/modules.py`.

---

### 20. Class-level mutable lists on `LectureSpider` are shared across instances
**File:** `src/parser/crawler.py`  
`found_modules: list[ModuleLink] = []` and `found_faculties: list[dict] = []` are class-level attributes, not instance attributes. If Scrapy ever instantiates the spider more than once, both instances mutate the same list, causing duplicate or mixed data.

---

### ✅ 21. `split_by_day` ordering is appended after user sort instead of taking priority
**File:** `src/api/routers/schedule.py`  
**Fixed:** the `ORDER BY` for `weekday_col` is now applied *before* `sort_query()`, so a weekday sort is primary and the user-supplied `sort` only breaks ties within a day. Verified: `/schedule/weekly?page_size=20&split_by_day=true` returns a non-decreasing weekday sequence, also when combined with `&sort=location_id&order=desc`.

---

### ✅ 22. `weekday` filter documentation inconsistency between `/events` and `/schedule/weekly`
**File:** `src/api/routers/events.py`  
**Fixed:** the `/events` `weekday` description now documents the API convention `0=Monday … 6=Sunday`, matching the `(day + 1) % 7` conversion and `/schedule/weekly`. Additionally `weekday` is now bounded with `ge=0, le=6` on **every** event endpoint that accepts it — `/events`, `/modules/{id}/events` (previously unbounded, so `weekday=7` silently wrapped to Monday) and `weekdays` on `/schedule/weekly` (same wrap). Out-of-range values now return **422**.

---

### 23. API supports only a single sort column (multi-level sort done client-side)

**File:** `src/api/routers/shared.py` (`sort_parameters`, `sort_query`)  
The `sort` parameter is a scalar string on every endpoint (`/modules`, `/courses`, `/events`, `/exams`, …): `sort_parameters()` exposes only `?sort=<column>&order=asc|desc`, and `sort_query()` applies exactly one `ORDER BY`. The UI offers multi-level sorting, so the client sends only the **primary** level to the backend and applies the whole sort chain itself (documented workaround, not an API fix).

- `ts/api/api.ts:74` — *"The API only supports one sort column, so the client sends the primary level and applies the remaining levels itself."*
- `ts/filters/query.ts:180` (`backendSort`) — *"The API only accepts a single sort column…"*
- `ts/sort.ts:171` (`compareItems`) and `ts/views/collection.ts:71` (`activeSortLevels`) — same rationale.

---

### ✅ 24. Courses: staff is not resolved to IDs → instructor filter disabled

**File:** `src/api/routers/courses.py` (`get_courses`)  
`/courses` only exposes a **name-based** `staff` filter (`{"type":"string", "description":"…partial match"}`), while the UI filter (`#filter-instructors`) supplies staff **IDs**. The client's `getCourses` has its `staff_id` block commented out with the note `// Currently staff is not resolved to IDs -> bug API` (`ts/api/api.ts:245`), so the instructor filter is effectively disabled.

- **Fixed:** `/courses` now exposes `staff_id` (repeatable, OR within the filter) alongside the name-based `staff` filter, so the client-side `staff_id` block can be re-enabled. Live proof: `/courses?page_size=1` → **9562**; `&staff_id=1` → **9** (filter is applied).

---

### ✅ 25. Exams: `building_id`, `staff_id` and `semester_id` filters are silently ignored

**File:** `src/api/routers/exams.py` (`get_exams`)  
**Originally:** the exam filter UI (`#filter-group-exam`) offers Gebäude (`#filter-buildings`), Prüfer (`#filter-staff`) and the global semester list, and `fetchExamPage` sends all three, but `/exams` accepted **none** of them (it only had a name-based `staff` filter), so those filters were simply ineffective.

- Live proof: `/exams?page_size=1` baseline = **7130**.
- **`staff_id` and `semester_id` are implemented:** `&staff_id=1` → **1**, `&semester_id=1` → **2385** (both narrow the result).
- **`building_id` is marked as _data not available_ instead of being implemented:** exam records carry no room/building attribution in the source data, so there is no meaningful `building_id` filter for `/exams`. The endpoint docstring in `src/api/routers/exams.py` now states this explicitly, and clients are pointed at `/events?building_id=…` (optionally with `module_id`/`course_id`) to locate the rooms where the matching courses are taught. A `building_id` sent by the UI is still ignored (see #27).

---

### ✅ 26. Events: `building_id` is a scalar, so multiple buildings cannot be OR-ed

**File:** `src/api/routers/events.py` (`get_events`)  
`getEvents` is typed `building?: number | number[]` and appends `building_id` repeatedly (`ts/api/api.ts:322-328`), but `/events` declares `building_id` as a single integer (`building_id: int | None`). Repeated scalar params are **last-value-wins**, not OR.

- **Fixed:** `/events` declares `building_id: list[int]`, i.e. it is repeatable and OR-ed, consistent with `location_ids`/`building_ids` on `/schedule/*`. Live proof: `building_id=1` → **3566**; `building_id=2` → **13151**; `building_id=1&building_id=2` → **16717** (= union, independent of argument order).

---

## Query-parameter audit (API contract pass)

Audit of every `Query(...)` parameter on every list endpoint, run against a production
copy of `database.db`. Each item below was reproduced live and is now fixed or
explicitly documented.

### ✅ 27. Unknown query parameters are silently ignored → now documented

FastAPI silently drops parameters an endpoint does not declare (e.g. `building_id` and
`course_id` on `/exams`, `faculty_id` on `/courses`, `type` on `/modules`), so a client
cannot tell a typo from an ignored filter. This is inherent framework behaviour and was
kept, but it is now stated in the OpenAPI **app description** (`src/api/main.py`) together
with the other parameter conventions:

- unknown parameters have no effect — rely on the per-endpoint parameter list;
- parameters marked `NOT IMPLEMENTED` match nothing because the data is not populated;
- repeated parameters are OR-ed inside one filter, different filters are AND-ed;
- `sort`/`order` support a single column only;
- pagination requires both `page` and `page_size`.

`/exams` additionally documents in its docstring that `building_id` is not available
(see #25).

### ✅ 28. `ical_reminder_minutes` returned HTTP 500 for every value

**File:** `src/api/routers/shared.py` (`export_event_parameters`)

`list[int] | None = Query(None, ge=0, le=10080, …)` applied the `ge`/`le` constraint to
the **list** instead of its items, so Pydantic raised
`TypeError: Unable to apply constraint 'ge' to supplied value [15]` and **every** event
endpoint (13 of them) returned 500 whenever the parameter was supplied — single value
included, and even without `format=ical`.

**Fixed** by validating per item: `list[Annotated[int, Query(ge=0, le=10080)]] | None`.
Verified: `?ical_reminder_minutes=15` → 200, `?…=15&…=60` → 200, `?…=-1` / `?…=99999`
→ 422.

### ✅ 29. `sort` was not validated → HTTP 500 when a relationship name was passed

**File:** `src/api/routers/shared.py` (`sort_parameters`, `sort_query`)

`sort` was declared as a plain `str` with an `enum=[…]` list. FastAPI only *documents*
an enum passed this way — it does not validate it — so any value reached `sort_query()`,
where `getattr(Model, <relationship>).asc()` raised
`NotImplementedError: asc_op` and the request failed with **500** on every list endpoint
(`/courses?sort=events`, `/modules?sort=degrees`, `/events?sort=courses`,
`/exams?sort=module`, `/staff?sort=modules`, `/locations?sort=building`,
`/schedule/weekly?sort=location`, `/modules/{id}/events?sort=location`, …). An
unknowable value such as `?sort=bogus` was silently ignored instead of rejected.

**Fixed** by annotating the parameter with the real `Enum` type (`SortField`) and by
making `sort_query()` ignore anything that is not an actual DB column as a second line of
defence. Verified: `?sort=events` → **422**, `?sort=bogus` → **422**,
`?sort=name&order=desc` → 200.

### ✅ 30. `/…/distinct/fields?field=…` returned HTTP 500

**Files:** `src/api/routers/shared.py` (`distinct_parameters`), all 10 `/distinct/fields` endpoints

Same root cause as #29: `field` was a plain `str` + `enum=`, so
`?field=events` (relationship) raised `NotImplementedError: asc_op` and `?field=bogus`
raised `AttributeError: bogus` — both surfacing as **500**.

**Fixed** by using the `DistinctField` enum type for validation and by moving the ten
duplicated handler bodies into a single shared `distinct_field_response()` helper that
rejects non-column fields with **422** and orders by the requested column. Verified:
`?field=name` → 200, `?field=events` → 422, `?field=bogus` → 422, `?field=path` (JSON
column) → 200.

### ✅ 31. `ical_map_type` accepted arbitrary values

**File:** `src/api/routers/shared.py` (`export_event_parameters`)

Declared as `str` + `enum=["module", "course"]`, so `?ical_map_type=bogus` was accepted
(200) and fell through to the default branch. **Fixed** with a real `ICalMapType` enum —
invalid values now return **422**.

### ✅ 32. `path` and `path_prefix` filters added to `/modules`

**File:** `src/api/routers/modules.py`

The README ToDo *"Modules: filter by specific `path` segments or exact path prefixes"*
is now implemented:

- `path` (repeatable, OR within the filter) — matches modules with at least one stored
  navigation path containing the given segment, e.g. `?path=Informatik`.
- `path_prefix` — exact path prefix as `/`-separated segments, e.g.
  `?path_prefix=Root/SoSe 2025/10 - Fakultät für Mathematik und Informatik`.

`Module.path` is JSON-encoded as a **list of paths, each a list of ordered segments**, so
both filters are implemented with SQLite `json_each` predicates that flatten one level
(and therefore also decode `\uXXXX` escapes correctly, unlike a plain `LIKE` on the raw
text). Verified: `?path=Informatik` → **172**, `?path=Modulübersichten` → **27**,
`?path_prefix=Root/SoSe 2025` → **718**, `?path=Informatik&path=Philosophie` → **184**.

### ✅ 33. `staff` and `staff_id` filters added to `/events`

**File:** `src/api/routers/events.py`

The README ToDo *"Events: filter by exact staff members within the parsed event `staff`
list"* is now implemented on **all seven** event-list endpoints (`/events`, `/today`,
`/tomorrow`, `/week`, `/day/{date}`, `/week/{date}`, `/month/{date}`):

- `staff` (repeatable; case-insensitive partial match on `Staff.name`; OR within the filter)
- `staff_id` (repeatable; exact `Staff.id`; OR within the filter)

Verified: `/events?staff_id=1` → **57** and `/events?staff=Deeg` → **57** (baseline
158848); `/events/week/2025-10-20?staff_id=1` → **3** (baseline 2987);
`/events/month/2025-10-20?staff_id=1` → **8** (baseline 8457);
`/events?staff_id=1&course_id=1` → **16** (filters AND-ed).


### ✅ 34. `/events/{event_id}/location` returned HTTP 500 for events without a room

**File:** `src/api/routers/events.py` (`get_event_location`)

Found while smoke-testing every endpoint after the parameter fixes. The handler returns
`items[0] if items else None`, but the route declared `response_model=LocationRead`
(non-optional), so FastAPI raised
`ResponseValidationError: Input should be a valid dictionary or object to extract fields from`
— a **500** — for every event whose `location_id` is `NULL`. That is **1264 / 158848**
events in the production data set (`/events/6437/location` reproduced it).

**Fixed** by declaring `response_model=LocationRead | None` and documenting that `null`
(HTTP 200) is returned when the event has no location. The same latent pattern in
`/locations/{location_id}/building` (declared `BuildingRead`, returns `None`) was fixed
the same way; it does not currently trigger because no location in the data set lacks a
building.

### ✅ 35. `/…/distinct/fields` required `field` but that was only visible via a 422

**File:** all `/…/distinct/fields` endpoints

Not a bug as such, but recorded for the API contract: `field` is a **required** parameter
(omitting it returns `422 query.field: Field required`). This is now consistent across all
ten `distinct/fields` endpoints after the shared-helper refactor in #30.

