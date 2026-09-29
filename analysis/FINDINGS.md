# AlmaWeb parser audit — findings

Read-only audit of the current parser against the full local page store
(``.pagedata``: 5 823 module pages, 14 957 course pages, 467 room pages) and the
crawl snapshot (``snapshots/modules_latest.json``: 5 823 module entries). No
production code or cache was modified; the analysis lives in ``analysis/``.

Reproduce with:

```bash
.venv/bin/python analysis/check_coverage.py          # found -> stored
.venv/bin/python analysis/scan_time_crashes.py --limit 0
.venv/bin/python analysis/check_path_retention.py
.venv/bin/python analysis/check_json_mutation.py
.venv/bin/python analysis/check_degree_loss.py
.venv/bin/python analysis/check_event_collisions.py --limit 0
.venv/bin/python analysis/scan_fields.py --kind module --limit 0
```

## Summary

| # | Severity | Issue | Data affected |
|---|----------|-------|---------------|
| A | **High** | `_parse_time` crashes on `24:00`, dropping whole modules | 19 modules (courses/events/exams too) |
| B | **High** | `module.path` appended in place on a JSON column is not persisted | 6 721 of 13 871 path groups lost |
| C | Medium-High | Global event dedup merges unrelated sessions (no room = no room) | 341 null-room events shared across courses |
| D | Medium | "Leistungen" (module achievements + Gewichtung) table never parsed | ~97% of module pages |
| E | Low-Medium | Unmapped structured fields dropped | Literaturangabe (5 642), Wahlbereich fields, course sections |
| F | Low | `module.language` is always empty (dead field, but exposed by API) | all 2 940 modules |
| G | Low | `_get_or_insert_course` drops staff links on re-encounter | 9 courses with no staff |
| H | Info | 81 module numbers carry multiple names → duplicate module rows | 81 numbers |

## A. `24:00` exam time drops the entire module (HIGH)

`src/parser/course_parser.py::_parse_time` does `time(int(hour), int(minute))`
with no range check. AlmaWeb uses exam end times of `24:00` (midnight), e.g.
`So, 31. Aug. 2025, 23:59 - 24:00`. `time(24, 0)` raises
`ValueError: hour must be in 0..23`. `parseModule` propagates it and the broad
`except` in `_fetch_and_parse_module` logs it as `module_fetch_error` and returns
`None`, so the **whole module** (and all its courses/events/exams) is discarded.

Evidence:

* `logs/parser-warnings.jsonl` has exactly **19** `module_fetch_error` entries,
  all with `error = "hour must be in 0..23"` (they are parse crashes, not
  network failures).
* `analysis/scan_time_crashes.py` finds **19** module pages containing an
  out-of-range time (`24:00`), and 0 impossible dates. Course pages: 0.
* Those 19 modules match the coverage gap exactly: `check_coverage.py` reports
  1 module missing from the DB and **18 missing module↔semester links** (the
  19 entries collapse to 19 unique (number,name) pairs; one is the single
  missing row, the other 18 modules already exist from another semester page but
  never receive this semester's link).

All 19 pages are present in ``.pagedata``, so they are fully recoverable by an
offline re-parse once the time parsing is made robust.

## B. Navigation paths are lost (HIGH)

`src/database/database.py::_get_or_insert_module` accumulates additional paths
for an existing module with ``module.path.append(...)``. ``Module.path`` is a
plain ``Column(JSON)`` (``src/database/model.py``); SQLAlchemy does **not** track
in-place mutations of JSON columns, so the appended paths are never flushed.

Evidence:

* `analysis/check_json_mutation.py` (on a DB copy) appends a path group exactly
  like the parser and shows it is not persisted.
* `analysis/check_path_retention.py`: the snapshot holds **13 871** path groups
  for the matched modules, the DB stores **7 150** → **6 721 lost (48 %)**,
  2 161 modules store fewer paths than were found.

Consequence (chained data loss): `degree_parser` derives degrees from
``module.path``. `analysis/check_degree_loss.py` shows **616 degree memberships
are lost across 362 modules**, and the previously reported 422 modules with no
degree at all. ``ModuleDegreeLink`` currently holds only 5 115 rows.

## C. Global event dedup merges unrelated sessions (MEDIUM-HIGH)

`src/database/database.py::_insert_event_if_new` treats two sessions as one
physical event when they share ``(event_date, start_time, end_time,
location_id)`` **globally** — the course is not in the key, and a ``NULL``
location matches another ``NULL``. Two unrelated courses meeting at the same
time without a room are therefore merged into a single row, and their staff and
course links are mixed.

Evidence (DB):

* event 31209 = `2025-04-08 11:15–12:45`, no room, linked to *Walter Benjamin zur
  Einführung*, *Stochastic Processes 1* and *Quanten- und Relativitätstheorie*.
* 341 null-location events are linked to more than one course; 2 192 dedup keys
  overall are shared by >1 course.

Source replay (`analysis/check_event_collisions.py`, all 14 957 course pages):
174 163 source session rows vs 158 640 distinct keys; 2 192 keys shared by >1
course (341 null-room). Some sharing is legitimate (a shared colloquium), but
null-room merging of unrelated courses is not.

## D. "Leistungen" table (achievements + Gewichtung) never parsed (MEDIUM)

Each module page carries two exam-like tables:

* **Leistungen** — `summary="Leistungen"`, columns *Kurs/Modulabschlussleistungen ·
  Leistungen · Bestehenspflicht · Gewichtung*
  (classes `rw-detail-reqachieve`, `rw-detail-compulsory`, `rw-detail-weight`).
* **Modulabschlussprüfungen** — the parser only reads this one
  (`rw-detail-exam`, `rw-detail-date`, `rw-detail-instructors`,
  `rw-detail-compulsory`).

`extract_exams` selects only the *Modulabschlussprüfungen* table and there is no
model field for achievement/weighting, so the *Gewichtung* (weight) and the
"Leistungen" rows are dropped entirely. `analysis/scan_fields.py --kind exam`
shows 561 Leistungen vs 552 Modulabschlussprüfungen tables in the first 600
pages; 800/800 sampled module pages contain `Gewichtung`,
`Leistungskombination` and `Modulabschlussleis`, none of which reach the DB.

Exam rows themselves have **no location column** — the suspicion about lost exam
locations is unfounded for this source (there is no `Prüfungsort` anywhere).

## E. Unmapped structured fields silently dropped (LOW-MEDIUM)

`_LABEL_MAP` (module) captures 9 labels; the full scan of all 5 823 module pages
finds 5 more that are ignored:

| label | pages |
|-------|------:|
| `Anzahl Wahlkurse` | 5 823 |
| `Literaturangabe` | 5 642 |
| `Teilnahmevoraussetzungen für den Wahlbereich` | 930 |
| `Moduleinstufung im Wahlbereich` | 925 |
| `Anmerkung zur Benotung` | 457 |

`_COURSE_LABEL_MAP` is missing `Orga-Einheit`, and the free-text sections
*Offizielle Kursbeschreibung* (142), *Organisatorisches* (92) and *Literatur*
(81) are ignored.

## F. `module.language` is a dead field (LOW)

There is no structured language field on module pages (only prose such as
"Die Unterrichtssprache ist Englisch"). `_get_or_insert_module` reads
`module_data.get("language")`, a key `ModuleType` never defines, so all
2 940 module rows have `language == ""`. The course level is populated
(`course.language` 9 600/9 600). The API schema (`models.ModuleRead.language`)
therefore always returns empty.

## G. Course dedup drops staff on re-encounter (LOW)

`_get_or_insert_course` returns early when a course with the same
``(name, number, type)`` exists and does **not** link any staff carried by the
new occurrence. Additional instructors from later semesters/modules are lost
(9/9 600 courses currently have no staff link at all).

## H. Same number, several names (INFO)

81 module numbers map to more than one name (real renames, e.g.
`03-AFR-2108` "Planen und Forschen" vs "Planning and Researching"). Because the
module identity key is ``(number, name)``, these become separate module rows and
the API's module ``number`` is not unique. Not a bug in itself, but it splits
semester links and degrees across rows, which the API consumers should know.

## Dead fields / minor

* `Event.name` is never set by `extract_events`, so `event.name` is `""` for all
  159 535 rows.
* `_parse_date` is likewise unguarded (`date(y, m, d)`); no impossible date was
  found in the current store, but the same crash-and-drop failure mode exists
  (e.g. a `31. Feb.`).
* Audit snapshot diff reported "stored modules=2738" — an artifact of how it
  matches names (snapshot names include the number prefix). `check_coverage.py`
  matches on ``(number, name)`` and is the reliable measure.

## What checked out fine

* Header parsing: 0 module/course headers fail to split into `<number> <name>`.
* Course event dates/times: 0 out-of-range values; `_parse_date`/`_parse_time`
  never fired a warning for course events.
* Multi-room sessions: 0 found in 300 sampled pages (only the first room would
  be kept anyway).
* All 19 crashed module pages are cached locally and recoverable offline.

## Tooling added (all read-only)

| script | purpose |
|--------|---------|
| `scan_pages.py` | classify the page store by `PRGNAME` |
| `scan_fields.py` | mapped vs unmapped labels; exam/achievement table inventory |
| `scan_anomalies.py` | unparseable exam dates, multi-room rows, bad headers |
| `scan_time_crashes.py` | out-of-range times / impossible dates that crash parsers |
| `check_coverage.py` | snapshot (found) → DB (stored) module + semester-link diff |
| `check_semester_links.py` | semester histogram, multi-path modules, under-linking |
| `check_path_retention.py` | stored vs found navigation paths |
| `check_json_mutation.py` | proves the in-place JSON mutation is not persisted (DB copy) |
| `check_degree_loss.py` | degree memberships lost to path loss |
| `check_event_collisions.py` | replays course pages through the global event dedup |
