# TODO

> Tracked differences between the [api-v4.yaml](api-v4.yaml) spec and the current implementation, inline `TODO` comments, and other open items.

---

## 1. Code TODO Comments

- [ ] **Remove `None` from `Course.type` field**
  <details><summary>Details</summary>
  In <code>src/database/model.py:100</code>, <code>Course.type</code> is <code>int | None</code> with a TODO to remove <code>None</code>. The FK to <code>eventtype.id</code> should be non-nullable once data quality is ensured.
  </details>

- [ ] **Remove `None` from `Course.status` field**
  <details><summary>Details</summary>
  In <code>src/database/model.py:104</code>, <code>Course.status</code> is <code>int | None</code> with a TODO to remove <code>None</code>. The FK to <code>status.id</code> should be non-nullable once data quality is ensured.
  </details>

- [ ] **Implement real weekly schedule filter**
  <details><summary>Details</summary>
  In <code>src/api/routers/schedule.py:31</code>, the <code>/schedule/weekly</code> endpoint ignores all filter parameters (semester, faculty, degree, course, module, staff, location, building, weekday). It currently returns an unfiltered event list.
  </details>

- [x] **Implement `distinct_parameters` helper properly**
  <details><summary>Details</summary>
  In <code>src/api/routers/shared.py:498</code>, <code>distinct_parameters()</code> is marked TODO and only captures sort/format without any real distinct-value logic.
  </details>

---

## 2. Unimplemented API Endpoints

### 2.1 Distinct Field Endpoints

All `/distinct/fields` endpoints are stubs (empty `pass`) except `/faculties/distinct/fields`.

- [x] **`GET /modules/distinct/fields`** — stub, no logic
- [x] **`GET /courses/distinct/fields`** — stub, no logic
- [x] **`GET /events/distinct/fields`** — stub, no logic
- [x] **`GET /staff/distinct/fields`** — stub, no logic
- [x] **`GET /locations/distinct/fields`** — stub, no logic
- [x] **`GET /buildings/distinct/fields`** — stub, no logic
- [x] **`GET /semesters/distinct/fields`** — stub, no logic
- [x] **`GET /degrees/distinct/fields`** — stub, no logic

### 2.3 Admin Endpoints

- [ ] **`GET /admin/health`** — stub, returns nothing
  <details><summary>Details</summary>
  Spec expects a <code>HealthResponse</code> with status and database connectivity info. Currently the function body is <code>pass</code>.
  </details>

- [ ] **`GET /admin/sync`** — list ingestion runs, stub
- [ ] **`POST /admin/sync`** — trigger data ingestion, stub
- [ ] **`GET /admin/sync/{run_id}`** — get ingestion run details, not implemented
- [ ] **`POST /admin/sync/{run_id}/cancel`** — cancel ingestion run, not implemented

- [ ] **`GET /catalog/faculties/{faculty_id}/modules`** — not implemented
  <details><summary>Details</summary>
  Spec defines an endpoint to list modules belonging to a faculty. No corresponding route exists in the faculties router.
  </details>

---

## 3. Spec vs Implementation Differences

### 3.3 Missing Query Filters

- [ ] **`q` (free-text search) parameter not implemented**
  <details><summary>Details</summary>
  The spec defines a <code>q</code> parameter on all collection endpoints for full-text search across primary text fields. No implementation exists.
  </details>

- [x] **Events: `course_id` and `module_id` filters commented out**
  <details><summary>Details</summary>
  In the events router, direct filtering by <code>course_id</code> and <code>module_id</code> is commented out (lines 70-80). These are specified in the API spec.
  </details>

- [x] **Courses: `has_events` filter commented out**
  <details><summary>Details</summary>
  In the courses router, the <code>has_events</code> boolean filter is commented out (line 49). The spec requires it.
  </details>

- [ ] **Modules: `responsible_person` filter commented out**
  <details><summary>Details</summary>
  In the modules router, filtering by responsible person (staff) is commented out (line 59).
  </details>

- [x] **Events: `building` filter not implemented**
  <details><summary>Details</summary>
  Spec allows filtering events by building name with partial match. Not present in the events router.
  </details>

- [ ] **Events: `start_time_from/to`, `end_time_from/to` range filters missing**
  <details><summary>Details</summary>
  The spec defines separate time-range parameters for start/end times. The implementation has <code>start_time</code> and <code>end_time</code> exact matches instead of ranges.
  </details>

- [x] **Staff: `has_courses`, `has_events` filters missing**
  <details><summary>Details</summary>
  The spec defines these filters on the staff list endpoint. The implementation only supports <code>ids</code>, <code>names</code>, and relation-based filters.
  </details>

- [x] **Locations: `event_id`, `has_events` filters missing**
  <details><summary>Details</summary>
  The spec allows filtering locations by associated events. Not implemented.
  </details>

### 3.4 Weekly Schedule

- [ ] **Weekly schedule: no day-grouping or deduplication logic**
  <details><summary>Details</summary>
  Spec requires events grouped by weekday into deduplicated recurring slots. Current implementation returns a flat event list.
  </details>

### 3.5 Response Format Differences

- [ ] **RFC 9457 Problem Details not used for error responses**
  <details><summary>Details</summary>
  The spec requires all error responses (400, 404, 409) to use the <code>Problem</code> schema (RFC 9457). The implementation uses FastAPI default error responses.
  </details>

---

## 4. Code Quality & Bugs

- [x] **Typo in `admin.py`: variable `couts` should be `counts`**
  <details><summary>Details</summary>
  In <code>src/api/routers/admin.py:21</code>, the stats dict is assigned to <code>couts</code> instead of <code>counts</code>. Works functionally but is a typo.
  </details>

- [x] **`/admin/stats` uses `len(session.exec(select(...)).all())` instead of `COUNT`**
  <details><summary>Details</summary>
  The stats endpoint fetches all rows into memory to count them. Should use <code>SELECT COUNT(*)</code> queries for performance.
  </details>

- [x] **Catalog single-item endpoints missing 404 handling**
  <details><summary>Details</summary>
  <code>GET /catalog/event-types/{id}</code> and <code>GET /catalog/statuses/{id}</code> don't validate existence. They should return 404 for missing IDs.
  </details>

---

## 5. Future Ideas

> Items from [README.md](README.md) not already tracked above.

### Crawler

- [ ] Support crawling multiple faculties or semesters in a single run
- [ ] Add a periodic re-crawl mechanism that updates existing records instead of requiring a full re-run
- [ ] Add a `last_updated` timestamp to each datapoint
- [ ] Better error handling and logging in the crawler to identify and recover from parsing issues

### API — Filters

- [ ] Modules: filter by specific `path` segments or exact path prefixes instead of only free-text search
- [ ] Modules: wire up declared but inactive filters (`faculty_id`, `semester_id`, `staff_id`, `course_id`, `has_courses`, `has_events`, `has_staff`)
- [ ] Courses: filter by exact staff members within the parsed `staff` list
- [ ] Events: filter by exact staff members within the parsed event `staff` list
- [ ] Events: add normalized location filters to distinguish building, room, and free-text notes

### API — Endpoints

- [ ] Add `/api/modules/{id}/ical` shortcut to export a single module's timetable directly
- [ ] Expose a room/location schedule endpoint (all events in a given room on a given day)

### Data Model

- [ ] Handle courses of multiple modules with a many-to-many relationship where necessary
- [ ] Parse degree and semester information from the path or other sources
- [ ] Normalize events to a single week pattern and time slot format by collapsing dates
- [ ] Optimize event storage (57k+ entries per semester)

### iCal Export

- [ ] Fix event SUMMARY for events with empty names by resolving titles from linked courses/modules
- [ ] Add `ical_title_mode` to control title assembly strategy (event / course / module / smart)
- [ ] Expand format placeholders to include `{course_name}`, `{module_name}`, `{staff_names}`, etc.
- [ ] Add `ical_fan_out` parameter to emit one VEVENT per course/module pair
- [ ] Add `ical_calendar_name`, `ical_timezone`, `ical_filename`, `ical_categories` parameters
- [ ] Add named presets via `ical_template` (compact / detailed / minimal)

### Infrastructure

- [ ] Add tests
- [ ] Containerize with Docker
- [ ] Make endpoints compatible with the [planer app](https://github.com/natureFrameworkManager/planer)