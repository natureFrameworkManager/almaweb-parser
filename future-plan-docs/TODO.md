# Outstanding work

Only **open** items are listed here; completed items from the earlier audit and
the query-parameter cleanup have been removed. The detailed, prioritised plan
(files, approach, tests, risk, versioning) lives in [plan.md](plan.md); the raw
evidence for the parser/data items is in
[analysis/out2/FINDINGS2.md](analysis/out2/FINDINGS2.md) and
[analysis/FINDINGS.md](analysis/FINDINGS.md).

## P1 — data loss (parser)

- [ ] **F1 Find the `Termine` table on every page layout.**
  `find_termine_section` misses a second layout → 374 courses / 4 365 session rows
  dropped (`src/parser/course_parser.py`).
- [ ] **F2 Keep all rooms of a multi-room session.**
  Only the first room is stored → 405 rows lose 1–3 rooms (`extract_events`,
  `EventType`, `Event`).
- [ ] **F3 Parse exam dates whose month has no trailing dot.**
  `parse_exam_datetime` rejects `Mai` → 9 exams lose date/time; also handle
  `ohne Termin` explicitly (`src/parser/module_parser.py`).

## P2 — important correctness

- [ ] **F4 Capture the `Leistungskombination` group rows** in the achievements
  table (596 rows / 289 pages) (`extract_achievements`, `ModuleAchievement`).
- [ ] **F5 Parse course-level "Veranstaltungseigene Prüfungen"** (500 pages /
  485 rows) into a new `CourseExam` entity + API.
- [ ] **F6 Never abort a whole parse run on one bad module.**
  `handleModuleList` re-raises `module_insert_failed`; log and continue instead.
- [ ] **F7 Stop creating name-only duplicate locations / enrich them.**
  Merge a detailed room into the name-only row (e.g. `Seminar 101`);
  410 locations are name-only (13 173 events lack building/address).

## P3 — data quality

- [ ] **F8 Decide on the global event dedup.** 1 851 events are linked to >1
  distinct course; document the co-scheduled-session model or scope the key.
- [ ] **F9 Stabilise module identity.** `(number, name)` splits modules that
  differ only by `[Start …]`/`[Granada]` annotations (81 numbers / 171 rows).
- [ ] **F10 Backfill `responsible_person` on re-encounter** and merge richer
  `prerequisites` dicts (`_get_or_insert_module`).
- [ ] **F11 Give the warnings log a run boundary** (`run_id`) so
  `warning_summary()` no longer mixes runs.

## P4 — polish / code

- [ ] **F12 `src/api/routers/admin.py`**: replace deprecated
  `asyncio.get_event_loop()` with `asyncio.get_running_loop()`.
- [ ] **F13 `analysis/scan_time_crashes.py`**: drop the stale "24:00 drops the
  module" risk label (the parser now maps `24:00` → `23:59`).

## Legacy items still open (low priority)

- [ ] **2-digit semester year**: `_get_or_insert_semester` stores
  `int(year_match.group(0))` verbatim, so a `SoSe 26` path would store `26`
  (not triggered by the current 4-digit paths).
- [ ] **Class-level mutable lists on `LectureSpider`** (`found_modules`,
  `found_faculties`) are shared between instances; move them to `__init__`.
- [ ] **Multi-level sorting**: `sort`/`order` accept a single column only
  (documented in the OpenAPI description; client-side otherwise).

## Future ideas (unchanged)

- [ ] Periodic re-crawl that updates existing records instead of a full re-run.
- [ ] `last_updated` timestamp on each datapoint.
- [ ] Recovery from partial failures / resume from the last successful point.
- [ ] Optimise event storage (159k+ events per run).
- [ ] Make endpoints compatible with the
  [planer app](https://github.com/natureFrameworkManager/planer).
