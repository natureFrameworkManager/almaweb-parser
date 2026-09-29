# AlmaWeb audit #2 — fresh crawl (2026-09-30) findings

Read-only audit of the parser against the **new** page store and DB produced by
`scrapy crawl lecture_spider -a progress_bar=1 -a sync_degrees=1`
(5 766 requests; 14 957 course, 5 823 module, 356 distinct room pages; DB: 2 937
modules, 9 591 courses, 159 113 events, 7 149 exams, 3 345 achievements, 766
locations, 445 degrees).

No production code, `.pagedata`, snapshot or `database.db` was modified. New
analysis scripts/results live in `analysis/` and `analysis/out2/`.

## Confirmed clean (audit #1 fixes hold end-to-end)

| check | result |
|-------|--------|
| `check_coverage.py` | 5 823/5 823 modules matched, **0 missing rows, 0 missing semester links** |
| `check_path_retention.py` | **0** path groups lost (was 6 721) |
| `check_semester_links.py` | **0** under-linked modules (tool fixed, see #12) |
| `scan_prerequisites.py` | **0** prerequisite keys lost / swallowed (was 3 840) |
| `compare_module_capture.py` | **0** scalar mismatches over all 5 823 pages |
| `compare_course_capture.py` | **0** glued/truncated course values (was 2 497) |
| `scan_text_separators.py` | all module/course fields OK |
| `db_integrity.py` | 0 duplicate modules/courses/exams/achievements, 0 orphan links, 0 empty mandatory fields |
| DB newlines | 1 327 modules `goals`, 757 courses `official_description`, 573 `organisational` carry `\n` |
| this crawl's warnings | only `no_events_content` (361) + `no_exams_section` (4); no fetch/parse crashes |

## Findings

| # | Severity | Issue | Impact |
|---|----------|-------|--------|
| 1 | **High** | Course `Termine` section not found on a page-layout variant | **374 courses, 4 365 session rows lost** |
| 2 | **High** | Multi-room `Termine` rows keep only the first room | **405 rows** lose 1-3 rooms |
| 3 | Medium-High | Exam dates in months without trailing dot (`Mai`) rejected | 9 exam rows lose date/time |
| 4 | Medium | Achievement `Leistungskombination` group rows dropped | 596 rows / 289 pages |
| 5 | Medium | "Veranstaltungseigene Prüfungen" never parsed | 500 pages / 485 rows |
| 6 | Medium | One unparseable event aborts the whole parse run | latent (`raise`) |
| 7 | Medium | 410 name-only locations (free-text room cells) | 13 173 events without building/address |
| 8 | Low-Med | Event dedup merges co-scheduled courses | 1 851 events shared by >1 distinct course |
| 9 | Low | Same module number, several names | 81 numbers / 171 rows |
| 10 | Low | `_get_or_insert_module` never backfills `responsible_person` | latent (0 affected now) |
| 11 | Info | warnings log is cumulative across runs | counts mix runs |
| 12 | Info/Fix | `check_semester_links.py` reported 2 155 false gaps | analysis tool fixed |
| 13 | Info | 374 modules have no degree link | legitimate (Wahlbereich/Sprachenzentrum) |

## 1. Whole `Termine` tables are dropped on a page-layout variant (HIGH)

`parseCourse` resolves the session table with `find_termine_section`, which only
looks for a "Termine" child among the **direct children of `#contentlayoutright`'s
parent**. A second layout exists where the Termine column lives in a different
container (`div.flex.flex-col.space-y-12.col-span-3` under `form`), so the lookup
returns `None`, `extract_events` gets `content=None` and the whole schedule is
lost. The course row is still written, just with zero events.

Evidence (`scan_event_detection.py`):

```
Scanned 14957 course pages; with Termine rows=12874
Pages with raw rows but parser kept 0 events: 374 (session rows lost: 4365)
  1a408ca214b7cd5c6af256d868cb38d908ff7b2c.html  '03-MUS-1108.SE01 Musik im Kontext ...'  raw_rows=15 section=no
  97eff9dd0829145dac352d6f4e9a0351f4accaf9.html  '06-002-106-1.TU01c Angewandte Statistik' raw_rows=14 section=no
```

Verified in the DB (course `03-MUS-1108.SE01` -> 0 event links). This crawl logged
361 `no_events_content` warnings for exactly these pages. This is the single
largest data loss in the current dataset.

## 2. Multi-room sessions keep only the first room (HIGH)

`extract_events` reads one room per Termine row (`room_values[0]` and the first
`appointmentRooms` anchor). Many sessions legitimately list several rooms/fields;
the rest are silently dropped. The earlier 300-page sample that found "0
multi-room rows" was not representative — the full store has **405**.

Evidence (`scan_anomalies.py`, full run):

```
rows with multiple rooms (only first kept): 405
   71  'Schärttner Halle A 0100 | , Seminarraum S 11 A 0025'
   57  'Ernst-Grube-Halle C 0100 - Feld 1 | , ... - Feld 2 | , ... - Feld 3'
   44  'Seminarraum S412  S 4.205 | , PC-Pool R 3015'
```

## 3. Exam dates in months without a trailing dot are lost (MED-HIGH)

`parse_exam_datetime` requires `(\d{1,2}\. \w{3}\. \d{4})` — a dot after the
month. German abbreviations are dotted except **"Mai"**, so every May exam
silently gets `date/start/end = None`.

Evidence (`compare_module_capture.py` / `scan_anomalies.py`):

```
Unparseable exam dates: 8 distinct, 348 occurrences
    339  'ohne Termin'                (placeholder, no date expected)
      2  'Do, 21. Mai 2026, 13:30 - 15:00'
      2  'Fr, 1. Mai 2026, 00:00 - 00:00'
      1  'Do, 21. Mai 2026, 09:00 - 09:15'
      1  'Di, 20. Mai 2025, 13:30 - 14:30'
      1  'Fr, 22. Mai 2026, 00:00 - 23:59'
      1  'Mo, 4. Mai 2026, 00:00 - 00:00'
      1  'Do, 7. Mai 2026, 00:00 - 00:00'
```

## 4. Achievement "Leistungskombination" group rows are dropped (MEDIUM)

The `Leistungen` table has a rowspan group row per combination
(`Kurs/Modulabschlussleistungen`, `Summe`, `Gewichtung`) followed by the component
rows carrying `rw-detail-reqachieve`. `extract_achievements` keeps only the
latter, so the combination name and summed weight are discarded.

Evidence: `Achievement rows: raw=7107; parsed=6511; count mismatches=289 pages`.

## 5. "Veranstaltungseigene Prüfungen" is never parsed (MEDIUM)

Each course page carries a `name="examName"` / `name="examDate"` table
(course-level exams) that `parseCourse` ignores.

Evidence (`scan_course_exams.py`): `500 pages, 485 rows` (461 `k.Terminbuchung`,
24 `ohne Termin`).


## 6. One unparseable event aborts the whole parse run (MEDIUM, latent)

`Event.start_time/end_time/event_date` are `NOT NULL`; `extract_events` can yield
`None`; `_insert_event_if_new` then raises `IntegrityError`, and
`handleModuleList` **re-raises** after logging `module_insert_failed`, aborting
the run. This crawl had **0** such rows (`Parsed events with None fields: {}`),
so it did not trigger — but the failure mode is one bad page away.
`analysis/test_insert_events.py` reproduces it against a temp DB.

## 7. 410 name-only locations (MEDIUM, largely source data)

17 310 Termine room cells have **no** detail anchor (free text); the parser stores
those as name-only locations (`external_id=""`, empty building). 13 173 events
reference such a location and therefore expose no building/address.

Evidence (`scan_room_coverage.py`): `766 locations, 410 name-only; room cells with
anchor=159312, free text only=17310`. Only **1** of the 410 has a cached detail
page (`Seminar 101`) — a real miss that also created a duplicate location row
(the same room exists with details). The rest are upstream gaps.

## 8. Event dedup merges co-scheduled courses (LOW-MEDIUM)

`_insert_event_if_new` keys on `(event_date, start_time, end_time, location_id)`
globally. 1 851 events are linked to more than one **distinct** course (e.g. six
different "What is ...?" seminars merged into one event). Whether that is a
co-taught session or an over-merge cannot be decided from the DB alone, but it
means an event's identity is not course-scoped. Null-room events are correctly
scoped per course (341 groups of identical null-room slots across courses are
*separate* rows, which is intended).

## 9-14. Minor / informational

* **#9** 81 module numbers map to 2-6 names (171 rows), e.g. `05-GSD-DEU14` ->
  `[Start SoSe 2026]` / `[Start SoSe 25]` / `[Start SoSe 26]`, and
  `30-SPZ-SPANB1` -> `Spanisch B1` vs `Spanisch B1  [Granada]` (double space).
  The `(number,name)` identity key splits these into separate rows.
* **#10** `_get_or_insert_module` backfills many scalar fields on re-encounter but
  not `responsible_person` (staff links are only created on first insert).
  0 modules are affected in this dataset.
* **#11** `logs/parser-warnings.jsonl` is appended across runs with no run marker,
  so `warning_summary()` mixes runs (it still reports the 19 old
  `module_fetch_error` from 21:31 while this crawl had none).
* **#12** `analysis/check_semester_links.py` matched DB links by `module.name`
  while snapshot names include the number prefix -> it reported 2 155 false
  under-links. Fixed (keys by `(number, name)`); now reports 0.
* **#13** 374 modules have no degree link because their paths are outside a degree
  programme (Wahlbereich, Sprachenzentrum, Aufbaukurse) — expected.
* **#14** `src/api/routers/admin.py:243` uses deprecated `asyncio.get_event_loop()`.
* **Note:** `scan_time_crashes.py` still labels 19 module pages "at risk of being
  dropped" for `24:00` times, but `_parse_time` now maps `24:00`->`23:59` and
  coverage shows those modules are present — the label is stale.

## Tooling added / changed

| script | purpose |
|--------|---------|
| `analysis/db_integrity.py` | NEW: dedup/collision/empty-field integrity over the DB |
| `analysis/scan_room_coverage.py` | NEW: name-only locations vs cached room pages |
| `analysis/scan_event_detection.py` | extended: counts lost rows + file names |
| `analysis/check_semester_links.py` | fixed: match by `(number, name)` |

## What to fix (priority)

1. `find_termine_section`: locate the Termine table by its content
   (`td[name=appointmentDate]` / heading "Termine" or "Kurstermine") instead of by
   a fixed nesting — recovers 4 365 rows.
2. `extract_events`: support several rooms per row (store them / de-duplicate),
   or at least log the dropped rooms — affects 405 rows.
3. `parse_exam_datetime`: make the month dot optional — recovers the May exams.
4. `extract_achievements`: also read the combination group rows.
5. Parse the course-level "Veranstaltungseigene Prüfungen" table.
6. Do not `raise` from `handleModuleList` on a single insert failure; log and
   continue (skip the module, keep the rest of the run).

| 14 | Low | `admin.py` uses deprecated `asyncio.get_event_loop()` | API code |
