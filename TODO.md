# TODO
## Code & Model Issues

- [x] **Remove `None` from `Course.type` field**
  - In `src/database/model.py:100`, should be non-nullable once data quality is ensured

- [x] **Remove `None` from `Course.status` field**
  - In `src/database/model.py:104`, should be non-nullable once data quality is ensured

- [x] **Fix parser of unsplit staff names**

- [x] **Fix data model and parser creating events of different modules, staff and courses**
  - Many-to-many relationships/links not handled properly

## Unimplemented API Endpoints

- [ ] **`GET /catalog/faculties/{faculty_id}/modules`**
  - Spec defines an endpoint to list modules belonging to a faculty

## Missing Features (Spec vs Implementation)

- [ ] **`q` (free-text search) parameter not implemented**
  - All collection endpoints should support full-text search

- [x] **Weekly schedule: no day-grouping or deduplication logic**
  - Spec requires events grouped by weekday into deduplicated recurring slots

- [x] **Implement real weekly schedule filter**
  - In `src/api/routers/schedule.py:31`, endpoint ignores all filter parameters

