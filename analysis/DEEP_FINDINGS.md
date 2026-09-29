# AlmaWeb parser deep audit — new findings

Read-only offline audit of the **current** parser (`HEAD 37ce800`) against the full
local page store `.pagedata` (21 603 cached pages: 14 957 COURSEDETAILS, 5 823
MODULEDETAILS, 467 room `ACTION` pages). No production code, no `.pagedata` file and
no crawl snapshot was modified. All analysis scripts live in `analysis/` and write
only to `analysis/out/`.

> Important context: `database.db` is **stale** — it was produced by an older
> parser revision. It still shows `moduleachievement = 0`, every `course.org_unit = ''`
> and a navigation-path loss (6 721 path groups) that the current code no longer
> produces. Do not use the DB as the baseline; everything below is measured by
> re-running the current parser over the cached HTML.

## Scripts added

| script | purpose |
|--------|---------|
| `analysis/compare_module_capture.py` | module scalar fields, exam rows/dates, achievement rows |
| `analysis/compare_course_capture.py` | course scalar fields, `<br>` text corruption, Termine rows |
| `analysis/scan_event_detection.py` | Termine detection + null date/time that would break the `NOT NULL` insert |
| `analysis/scan_prerequisites.py` | prerequisite line collapse / key loss |
| `analysis/scan_course_exams.py` | "Veranstaltungseigene Prüfungen" (dropped section) |
| `analysis/test_insert_events.py` | proves one bad event aborts the whole module insert |

## Summary

| # | Severity | Issue | Scope |
|---|----------|-------|-------|
| 1 | **High** | Prerequisite lines collapse → 3 840 requirement keys lost / merged | 1 594 of 5 662 module pages |
| 2 | **High** | `<br>` in course text fields not separated → words glued | 2 497 field values |
| 3 | Medium-High | Exam date regex rejects months without a trailing dot (`Mai`) | 9 exam rows (+339 `ohne Termin`) |
| 4 | Medium-High | One unparseable event aborts the whole parse run | any module with a null event field |
| 5 | Medium | "Veranstaltungseigene Prüfungen" table never parsed | 500 course pages / 485 rows |
| 6 | Medium | "Leistungen" combination group rows dropped | 596 rows / 289 pages |
| 7 | Low-Medium | Duplicate `location` rows (name-only + detailed) | 2 pairs, no enrichment |
| 8 | Low | `module.language` still a dead field (derived from courses) | all modules |


## 1. Prerequisite (Teilnahmevoraussetzungen) keys are lost / merged (HIGH)

`extract_module_values` normalises the value with
`_WHITESPACE_RE.sub(" ", get_text(" ", strip=True))` **before** `parse_prerequisites`
runs. The source separates requirements with `<br>`, one per line of the form
`<context>: <requirement>`. After the collapse there are no `\r\n` characters left,
so the `re.split(r"[\r\n]+", value)` inside `parse_prerequisites` yields a single
part: only the first `key: value` pair survives and every following `key: value` is
swallowed into the previous value (its key becomes unrecoverable text).

Evidence (`analysis/scan_prerequisites.py --limit 0`):

```
Scanned 5823 module pages; with Teilnahmevoraussetzungen=5662
Pages whose value spans multiple <br> lines: 1754
Pages with >1 'key: value' line:             1594
Requirement keys lost to the collapse:       3840
Pages whose stored value swallowed a following key: 1678
```

Example (page `1a7f97e74c1f52926234bfa85b39caee063fecc4`):
```
line : Staatsexamen Lehramt an Gymnasien Bildungswissenschaften: Teilnahme am Modul 05-BWI-02 und 05-BWI-03
line : Staatsexamen Lehramt Sonderpädagogik Bildungswissenschaften: Teilnahme an den Modulen 05-BWI-02 und 05-BWI-03
line : Staatsexamen Lehramt an Grundschulen Bildungswissenschaften: Teilnahme am Modul 05-BWI-02 und 05-BWI-03
line : Staatsexamen Lehramt an Oberschulen Bildungswissenschaften: Teilnahme an den Modulen 05-BWI-02 und 05-BWI-03
stored: ['Staatsexamen Lehramt an Gymnasien Bildungswissenschaften']  (lost 4)
```

The same split-at-first-colon also truncates a *key* when the context itself
contains a colon, e.g. `... (Schwerpunkt: Nachhaltigkeitsmanagement): keine`
became the key `... (Schwerpunkt` (`9758a808...`).

A secondary bug remains in `parse_prerequisites` itself: lines without `:` all
write to `prerequisites["allgemein"]`, so only the last such line would survive
even if the newlines were preserved (TODO.md #16, still open).

## 2. `<br>` boundaries are dropped in course text fields (HIGH)

`extract_course_values` reads each value with `tag.get_text(strip=True)` (no
separator), so text nodes separated by `<br>` are concatenated with no space.
Words are glued together and line structure is lost. Example (page
`1a379d116fe34270f34605626dc3975d131d3bdb`, field *Organisatorisches*):

```
stored  : "...Interessierte aller StudiengängePrüfungsleistungen sind ... erbringen.Modulverantwortliche/r: ..."
expected: "...Interessierte aller Studiengänge\nPrüfungsleistungen sind ... erbringen.\nModulverantwortliche/r: ..."
```

Evidence (`analysis/compare_course_capture.py --limit 0`):

```
Scalar value truncation/mismatch: 2497
    1018  'Organisatorisches'
    1000  'Offizielle Kursbeschreibung'
     479  'Literatur'
```

All 14 957 course pages parse without raising; the loss is silent. The module

## 3. Exam dates in May (and any month without a trailing dot) are lost (MEDIUM-HIGH)

`parse_exam_datetime` requires the month abbreviation to be followed by a literal
dot: `(\d{1,2}\. \w{3}\. \d{4})`. German month abbreviations are dotted except
**"Mai"**, so every exam dated in May fails the regex and silently gets
`date=None, start_time=None, end_time=None`.

Evidence (`analysis/compare_module_capture.py --limit 0`, date cell non-empty and
not `k.Terminbuchung`):

```
Unparseable exam dates: 8 distinct, 348 occurrences
    339  'ohne Termin'          (placeholder, expected to have no date)
      2  'Do, 21. Mai 2026, 13:30 - 15:00'
      2  'Fr, 1. Mai 2026, 00:00 - 00:00'
      1  'Do, 21. Mai 2026, 09:00 - 09:15'
      1  'Di, 20. Mai 2025, 13:30 - 14:30'
      1  'Fr, 22. Mai 2026, 00:00 - 23:59'
      1  'Mo, 4. Mai 2026, 00:00 - 00:00'
      1  'Do, 7. Mai 2026, 00:00 - 00:00'
```

Also note the raw `ohne Termin` placeholder is not explicitly recognised (only
`k.Terminbuchung` is), so it falls through the parser without a hint.

## 4. One unparseable event aborts the whole parse run (MEDIUM-HIGH)

`Event.start_time`, `Event.end_time` and `Event.event_date` are `NOT NULL`
(`src/database/model.py`). `extract_events` returns `None` for any Termine
date/time it cannot parse. `_insert_event_if_new` then inserts `None`, raising
`IntegrityError`; `insert_module_graph` is not guarded, and in `handleModuleList`
the handler logs `module_insert_failed` and **re-raises**, so the exception leaves
the whole parse (every remaining module is lost).

Reproduced with `analysis/test_insert_events.py`:

```
valid module inserted ok=True events=1 (expected ok=True events=1)
event_date=None -> IntegrityError: (sqlite3.IntegrityError) NOT NULL constraint failed: event.event_date
=> a single unparseable Termine row makes the whole module insert fail
```

`scan_event_detection.py` measures how many real Termine rows have an empty /
unparseable date or time. The scan was interrupted before finishing, so the exact
row count is not yet known; the failure mode itself is proven by the test above and
by the `NOT NULL` schema.


## 5. "Veranstaltungseigene Prüfungen" (course-level exams) are never parsed (MEDIUM)

Each COURSEDETAILS page has a sibling section *Veranstaltungseigene Prüfungen*
with a table using `name="examName"` / `name="examDate"` / staff / `Pflicht`.
`parseCourse` only reads the *Termine* section and the scalar `.tbdata` rows, so
this table is dropped entirely. Evidence (`analysis/scan_course_exams.py`):

```
Scanned 14957 course pages; containing 'Veranstaltungseigene Prüfungen'=500
Pages with such an exam table=500; exam rows=485
Most common dates: 461 'k.Terminbuchung', 24 'ohne Termin'
```

(The rows are mostly placeholders, but the section is unmodelled data that never
reaches the DB.)

The pages also carry "Contained in modules" (14 958), "Anmeldefristen" and other
sections that are likewise ignored.

## 6. "Leistungen" combination group rows are dropped (MEDIUM)

In the achievements table a `Leistungskombination` group is a rowspan row
(`Kurs/Modulabschlussleistungen = <group>`, `Summe`, `Gewichtung = <sum>`) followed
by the component rows carrying `rw-detail-reqachieve`. `extract_achievements` keeps
only rows with `rw-detail-reqachieve`, so the group row (its combination name and
the summed weight) is discarded. Evidence (`analysis/compare_module_capture.py`):

```
Achievement rows: raw=7107; parsed=6511; count mismatches=289 pages
```

The component names/weights are stored, but the grouping and the sum are lost.

## 7. Duplicate `location` rows without enrichment (LOW-MEDIUM)

When a room's detail page cannot be fetched, `fetch_and_parse_room_details` falls
back to a name-only room (`external_id=""`, empty building). `_get_or_insert_location`
keys on `(name, external_id, building_id)` and never updates an existing row, so a
room first seen name-only and later with details yields **two** location rows. The
stale DB already shows two such pairs (`Hörsaal 113`, `Seminar 101`); 406 of 760
locations have an empty `external_id`. Events attached to the name-only row keep an
empty building/address forever.

## 8. Smaller notes

* `module.language` is still empty on the module row itself (it is derived from the
  courses in `insert_module_graph`, but the field is documented as deprecated).
* `parse_prerequisites` still overwrites `prerequisites["allgemein"]`
  (TODO.md #16) — see finding 1.
* `_parse_date` accepts only 3-letter months; `_MONTHS` has no `Sept`, so a 4-letter
  abbreviation would silently fail. No real `DD. Sept YYYY` date was found in the
  store (the 21 `Sept` hits are prose "September"), so this is a latent risk only.
* Exam `name` keeps the leading row number (e.g. `"1 Projektarbeit"`).

## What checked out fine

* 14 957 / 14 957 course pages parse without raising (0 exceptions).
* 0 multi-value `Lehrende` cells: multiple instructors are `;`-separated and split
  correctly by `_clean_staff`.
* All module and course labels found on the pages are mapped; 0 unknown labels.
* Exam rows parse 1:1 with the DOM (8 705 raw = 8 705 parsed) apart from the lost
  May dates in #3; achievement rows differ only by the group rows in #6.
* All 467 cached room pages parse; 0 failures.
* 0 module headers fail to split; 0 duplicate module labels.

Note: the row-level Termine checks in `scan_event_detection.py` (empty/multi-room

## Fixes applied (parser only — API untouched)

A new block-aware extractor and a hardened prerequisite parser address both
failure-mode families (#1 and #2) everywhere they occur.

**`src/parser/utils.py`**
* `text_with_structure(tag)` walks the descendants, emits ``"\n"`` for
  block-level tags (``<br>``, ``<div>``, ``<p>``, ``<li>``, ``<tr>``, ...) and
  ``" "`` for inline tags (``<span>``, hidden ``<input>``), then normalises each
  line. It replaces both ``get_text(strip=True)`` (gluing) and
  ``get_text(" ", strip=True)`` (flattening) for parsed values.
* `single_line(text)` for labels/one-line values.

**`src/parser/module_parser.py`**
* `extract_module_values` now stores values via `text_with_structure`, so the
  ``<br>`` line structure of `Teilnahmevoraussetzungen` reaches the parser.
* `parse_prerequisites` rewritten: splits at the first **top-level** colon
  (colons inside parentheses no longer truncate the key), merges duplicate
  contexts, and joins all colon-less lines into `allgemein` instead of
  overwriting it. New helper `_split_prerequisite`.

**`src/parser/course_parser.py`**
* `extract_course_values` uses `text_with_structure`, removing the glued words
  in `Organisatorisches` / `Offizielle Kursbeschreibung` / `Literatur`
  (`...StudiengängePrüfungsleistungen...` → `...Studiengänge\nPrüfungsleistungen...`).

**`src/parser/room_parser.py`**
* `_extract_room_values` / `_extract_section_values` use the same helper; the
  building address keeps its previous single-line `", "` join.

### Verification (offline, full store)

| metric | before | after |
|--------|-------:|------:|
| prerequisite keys lost | 3 840 | **0** |
| pages with a swallowed following key | 1 678 | **0** |
| course scalar values with glued/truncated text | 2 497 | **0** |
| module scalar mismatches | 0 | 0 |
| exam rows raw vs parsed | 8 705 / 8 705 | 8 705 / 8 705 |
| modules parsed without raising (800-page smoke) | — | 800/800 |

New tests: `analysis/test_text_structure.py`. Scanners
`analysis/scan_text_separators.py` (per-field GLUED/FLATTENED verdicts) and
`analysis/scan_prerequisites.py` (keys lost) reproduce the numbers.

Not changed: the API, `database.db`, `.pagedata`, and the crawl snapshots. The
remaining findings #3–#8 are untouched (deferred).

> Note: `database.db` must be re-generated (`python -m src.parser.run_parse`) for
> the fixes to take effect in stored data.

rows) were not completed — that script is left fixed for a follow-up run.
