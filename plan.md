# AlmaWeb parser/API fix plan

Consolidated plan for all open fixes found in audit #1 (`analysis/FINDINGS.md`)
and audit #2 (`analysis/out2/FINDINGS2.md`). Ordered by impact.

Legend: **P1** = data loss / correctness, **P2** = important, **P3** = quality,
**P4** = polish. Each item lists the files, the approach, tests and risk.

---

## P1 — data loss

### F1. Find the `Termine` table on every page layout  (374 courses / 4 365 rows)

**Files:** `src/parser/course_parser.py` (`find_termine_section`).
**Problem:** the helper only inspects the direct children of
`#contentlayoutright.parent`; a second layout puts the Termine column in a
different container, so it returns `None` and all sessions are dropped.
**Fix:** resolve the section by *content*, not nesting — locate the first table on
the page that has a `td[name="appointmentDate"]` (fall back to
`name="appointmentTimeFrom"`), and return that table's enclosing section. Keep the
current lookup as a fast path. Optionally also accept headings matching
`Termine`/`Kurstermine`.
**Tests:** `scan_event_detection.py` must report `pages_rows_but_no_events == 0`
and `dropped_rows == 0`; add a focused unit test with one page of each layout
(from `.pagedata`) asserting `len(parseCourse(...).events) == raw_rows`.
**Risk:** low; strictly widens the match.

### F2. Keep all rooms of a multi-room session  (405 rows)

**Files:** `src/parser/course_parser.py` (`extract_events`, `_cell_values`),
`src/parser/types.py` (`EventType`), `src/database/model.py`,
`src/database/database.py`.
**Problem:** only `room_values[0]` / the first `appointmentRooms` anchor is used.
**Fix (preferred):** model the many-to-many properly — either an
`EventLocationLink(Event, Location)` association table, or store a
`locations` list on the event. Minimal alternative: parse every room anchor, store
the primary in `location_id` and the rest in a new `Event.additional_location_ids`
JSON column, and expose them via `?include=`. Recommend the association table
(consistent with the rest of the schema) with the first room kept as the primary
for backwards compatibility.
**Tests:** pick the 405 rows from `scan_anomalies.py`; assert the new relation has
2-4 locations; `db_integrity.py` gains a check that multi-room source rows have the
matching link count.
**Risk:** medium (schema + API change; needs migration and a version note).

### F3. Parse exam dates whose month has no trailing dot  (9 rows)

**Files:** `src/parser/module_parser.py` (`parse_exam_datetime`).
**Problem:** `(\d{1,2}\. \w{3}\. \d{4})` requires a dot after the month; `Mai`
has none, so May exams lose date/time.
**Fix:** make the dot optional (`\w{3}\.?\s*`) and accept `24:00` (already handled
by `_parse_time`). Also recognise `ohne Termin` explicitly (store `None` without a
warning) and log a warning for genuinely unparseable values.
**Tests:** extend `analysis/test_text_structure.py` (or a new parser test) with
`Mai`, `Jul.`, `ohne Termin`, `k.Terminbuchung`; `compare_module_capture.py`
must report 0 real unparseable dates.

## P2 — important correctness

### F4. Capture the `Leistungskombination` group rows  (596 rows / 289 pages)

**Files:** `src/parser/module_parser.py` (`extract_achievements`),
`src/database/model.py` (`ModuleAchievement`).
**Problem:** the group row (`Kurs/Modulabschlussleistungen` + `Summe` +
`Gewichtung`) is skipped; the combination name and summed weight are lost.
**Fix:** parse the rowspan group rows too. Store the group name + summed weight
(e.g. new columns `combination_name`, `combination_weight`, or emit an explicit
`is_group` achievement carrying them). Keep the existing per-component rows.
**Tests:** `compare_module_capture.py` `ach_raw_rows == ach_parsed_rows`; new unit
test on a page with a multi-component combination.
**Risk:** medium (schema addition + dedup key update).

### F5. Parse course-level "Veranstaltungseigene Prüfungen"  (500 pages / 485 rows)

**Files:** `src/parser/course_parser.py`, new `CourseExam` model, API router.
**Problem:** the course page table (`name="examName"`/`name="examDate"`/staff/
`Pflicht`) is ignored.
**Fix:** parse it into a new `CourseExam` entity linked to `Course` (mirroring
`ModuleExam`), add the fields, migration, and an API endpoint/schema. Note most
rows are `k.Terminbuchung` placeholders — store them anyway for completeness.
**Tests:** `scan_course_exams.py` rows == stored rows.
**Risk:** medium (new entity + API surface; version bump).

### F6. Never abort a whole parse run on one bad module  (latent)

**Files:** `src/parser/module_parser.py` (`handleModuleList`), optionally
`src/database/database.py`.
**Problem:** `insert_module_graph` failures are re-raised, so one event with a
`NULL` date/time (or any insert error) aborts the run.
**Fix:** log `module_insert_failed` and **continue** (skip that module); keep the
exception for `--strict`/debug. Consider `Event` columns nullable or a
row-level guard so a single unparseable session is skipped, not the module.
**Tests:** extend `analysis/test_insert_events.py` to assert the run continues past
a bad module (a fake executor loop or a direct unit test of the handler).
**Risk:** low.

### F7. Stop creating name-only duplicate locations / enrich them  (410 locations)

**Files:** `src/database/database.py` (`_get_or_insert_location`),
`src/parser/room_parser.py`.
**Problem:** a room seen first as free text is stored name-only; a later detailed
page creates a second row (e.g. `Seminar 101`), and name-only rows are never
enriched.
**Fix:** when a detailed room arrives, merge into the name-only row
(same `name`, empty `external_id`) — update `external_id`, `building_id`,
`description`, `type`, `seats`, `size`, `accessibility`, `url` — and/or add a
dedup step that prefers the detailed row. Keep the name-only fallback for genuine
upstream gaps (17 310 free-text room cells).
**Tests:** `scan_room_coverage.py` `recoverable_but_empty == 0`; `db_integrity.py`
`location name split == 0`.
**Risk:** medium (data merge; needs care not to merge distinct rooms with the same
name in different buildings).


## P3 — data quality

### F8. Event identity: scope or document the global dedup  (1 851 shared events)

**Files:** `src/database/database.py` (`_insert_event_if_new`).
**Problem:** an event is keyed globally on `(date, start, end, location_id)`; 1 851
events are linked to more than one *distinct* course.
**Decision needed:** if a shared room+time is genuinely one physical session, the
current M2M link is correct — then document it and add a check that flags
suspicious merges. Otherwise add `course_id` (or the source course number) to the
key. Recommend: keep the merge (it is the intended co-scheduled-session model) but
expose `courses` on the event (already possible) and add a `db_integrity` check
with a threshold/anomaly sample for review.
**Tests:** `db_integrity.py` report; manual review of a few samples.
**Risk:** low if documented only; high if the key changes.

### F9. Stabilise module identity  (81 numbers / 171 rows)

**Files:** `src/database/database.py` (`_get_or_insert_module`), `crawler.py`.
**Problem:** the `(number, name)` key splits modules whose name differs only by a
`[Start …]`/`[Granada]` annotation or a double space.
**Fix:** normalise the name for the identity key (collapse whitespace, strip
`[...]` semester/annex annotations) while keeping the full name for display; or
dedup with a normalised key and merge rows. Requires a one-off merge migration.
**Tests:** `db_integrity.py` "module numbers with several names" drops.
**Risk:** medium (identity change; needs a merge script and review).

### F10. Backfill `responsible_person` on re-encounter  (latent)

**Files:** `src/database/database.py` (`_get_or_insert_module`).
**Fix:** in the existing-module branch, if the incoming page carries a
`responsible_person` and the module has no staff links, create the links (reuse the
insert-path code). Also merge a richer `prerequisites` dict instead of only filling
when empty.
**Tests:** unit test inserting the same module twice with the staff only on the
second call.
**Risk:** low.

### F11. Give the warnings log a run boundary  (info)

**Files:** `src/parser/utils.py` (`log_warning`), audit tooling.
**Problem:** the JSONL is appended across runs, so `warning_summary()` mixes runs
(it still reports 19 old `module_fetch_error`).
**Fix:** include a `run_id` (crawl timestamp / `SyncRun.id`) in each record and
summarise per run; or rotate/annotate a run header line.
**Tests:** `warning_summary()` per run.
**Risk:** low.

## P4 — polish / code

### F12. API: `asyncio.get_event_loop()` deprecation

**File:** `src/api/routers/admin.py`. Replace with `asyncio.get_running_loop()`.
**Risk:** low.

### F13. Stale risk label in `scan_time_crashes.py`

The `24:00` crash is fixed (`_parse_time` maps it to `23:59`); the scan should stop
labelling those 19 modules "at risk" (or check the actual parser result).
**Risk:** none (analysis tool).

## Versioning

* F2/F5 add relations/entities -> further **minor** bump (e.g. `1.4.0`) with a
  changelog note; no breaking removal.
* Parser changes alone do not need an API bump, but the DB must be re-parsed.

## Suggested order / milestones

1. **M1 (correctness):** F1, F3, F6 — small, high impact, no schema change.
2. **M2 (completeness):** F2, F4, F5, F7 — schema/API changes; re-crawl after.
3. **M3 (quality):** F8 (document/review), F9, F10, F11.
4. **M4 (polish):** F12, F13.
5. Re-run the full audit suite after each milestone and compare against
   `analysis/out2/` baselines.

## Test strategy

* Offline replay against `.pagedata` (never the network) via
  `analysis/run_parse`-style harnesses.
* Per finding: the scanner named above must reach its "expected" value
  (`scan_event_detection`, `compare_module_capture`, `scan_prerequisites`,
  `scan_text_separators`, `scan_room_coverage`, `scan_course_exams`,
  `db_integrity`).
* Real unit tests for the pure functions (`_parse_date`/`_parse_time`/
  `parse_exam_datetime`, `parse_prerequisites`, `text_with_structure`) under
  `analysis/test_*.py`.
* A fresh crawl with a fresh DB is the final acceptance test; run
  `python -m src.parser.audit` and `analysis/db_integrity.py` on it.

## Out of scope

* Re-crawling from the tool (the user runs it).
* The planer-app compatibility work and event-storage optimisation noted in the
  README "Future Ideas".
