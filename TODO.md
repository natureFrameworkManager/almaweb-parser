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

- [ ] **Implement `distinct_parameters` helper properly**
  <details><summary>Details</summary>
  In <code>src/api/routers/shared.py:498</code>, <code>distinct_parameters()</code> is marked TODO and only captures sort/format without any real distinct-value logic.
  </details>

---

## 2. Unimplemented API Endpoints

### 2.1 Distinct Field Endpoints

All `/distinct/{field}` endpoints are stubs (empty `pass`) except `/faculties/distinct/{field}`.

- [ ] **`GET /modules/distinct/{field}`** — stub, no logic
- [ ] **`GET /courses/distinct/{field}`** — stub, no logic
- [ ] **`GET /events/distinct/{field}`** — stub, no logic
- [ ] **`GET /staff/distinct/{field}`** — stub, no logic
- [ ] **`GET /locations/distinct/{field}`** — stub, no logic
- [ ] **`GET /buildings/distinct/{field}`** — stub, no logic
- [ ] **`GET /semesters/distinct/{field}`** — stub, no logic
- [ ] **`GET /degrees/distinct/{field}`** — stub, no logic

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

- [ ] **Events: `course_id` and `module_id` filters commented out**
  <details><summary>Details</summary>
  In the events router, direct filtering by <code>course_id</code> and <code>module_id</code> is commented out (lines 70-80). These are specified in the API spec.
  </details>

- [ ] **Courses: `has_events` filter commented out**
  <details><summary>Details</summary>
  In the courses router, the <code>has_events</code> boolean filter is commented out (line 49). The spec requires it.
  </details>

- [ ] **Modules: `responsible_person` filter commented out**
  <details><summary>Details</summary>
  In the modules router, filtering by responsible person (staff) is commented out (line 59).
  </details>

- [ ] **Events: `building` filter not implemented**
  <details><summary>Details</summary>
  Spec allows filtering events by building name with partial match. Not present in the events router.
  </details>

- [ ] **Events: `start_time_from/to`, `end_time_from/to` range filters missing**
  <details><summary>Details</summary>
  The spec defines separate time-range parameters for start/end times. The implementation has <code>start_time</code> and <code>end_time</code> exact matches instead of ranges.
  </details>

- [ ] **Staff: `has_courses`, `has_events` filters missing**
  <details><summary>Details</summary>
  The spec defines these filters on the staff list endpoint. The implementation only supports <code>ids</code>, <code>names</code>, and relation-based filters.
  </details>

- [ ] **Locations: `event_id`, `has_events` filters missing**
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

- [ ] **Typo in `admin.py`: variable `couts` should be `counts`**
  <details><summary>Details</summary>
  In <code>src/api/routers/admin.py:21</code>, the stats dict is assigned to <code>couts</code> instead of <code>counts</code>. Works functionally but is a typo.
  </details>

- [ ] **`/admin/stats` uses `len(session.exec(select(...)).all())` instead of `COUNT`**
  <details><summary>Details</summary>
  The stats endpoint fetches all rows into memory to count them. Should use <code>SELECT COUNT(*)</code> queries for performance.
  </details>

- [ ] **Catalog single-item endpoints missing 404 handling**
  <details><summary>Details</summary>
  <code>GET /catalog/event-types/{id}</code> and <code>GET /catalog/statuses/{id}</code> don't validate existence. They should return 404 for missing IDs.
  </details>