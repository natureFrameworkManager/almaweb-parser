# Almaweb Parser & API

Scrapes the Almaweb *Vorlesungsverzeichnis* (course catalogue) of the University of Leipzig and exposes the collected data through a REST API.

The crawler walks the full module tree, parses each module and its courses (including room and building data), and stores everything in a local SQLite database. The API then serves that data with filtering, field selection, relation includes, and iCalendar export.

## Setup

1. Clone the repository and open a terminal in the project root.
2. Create and activate a virtual environment (optional but recommended):
   ```bash
   python -m venv .venv
   source .venv/bin/activate       # Linux / macOS
   .venv\Scripts\Activate.ps1      # Windows
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run the crawler to populate the database:
   ```bash
   scrapy crawl lecture_spider
   ```
   ```bash
   # Optional: run with progress bar
   scrapy crawl lecture_spider -a progress_bar=1
   ```
   This takes roughly 10 minutes. The crawler walks every page of the module tree, fetches up to 4 module pages and 8 course pages concurrently, and writes results to `database.db` as it goes. Progress is saved incrementally - interrupt with `Ctrl+C` and the modules parsed so far are kept.

   Degrees are derived separately from the stored module paths (extraction + harmonization over the full dataset) by a streaming second pass. Run it after the crawl, or automatically with the crawler:

   ```bash
   python -m src.parser.degree_parser        # batch-wise, bounded memory; add --prune to drop orphan degrees
   ```
   ```bash
   # Derive degrees at the end of the crawl:
   scrapy crawl lecture_spider -a sync_degrees=1
   ```
5. Start the API server:
   ```bash
   fastapi dev src/api/main.py
   ```

## Debugging the parser

A full crawl + parse takes hours, so the parser is built around a local page
store and JSON crawl snapshots that make iterations offline and fast.

**Store local copies of pages.** The crawl tree is cached by Scrapy
(`.scrapy/httpcache`), and every module/course/room page the parser fetches is
cached in `.pagedata/` as raw HTML with a JSON sidecar. Re-parsing the same URLs
is served from disk instead of the network. Override the location with
`ALMAWEB_PAGE_STORE`, or disable caching with `ALMAWEB_PAGE_STORE=off`. The URL
key strategy is configurable via `ALMAWEB_PAGE_KEY_STRATEGY` or
`--key-strategy` (`exact` (default), `query-sorted`, or `ignore-arguments`); see
the caveat in `src/parser/fetch.py`, since CampusNet carries page identity inside
`ARGUMENTS`.

**Rooms work offline too.** Room detail URLs are session-scoped
(`…PRGNAME=ACTION&ARGUMENTS=-A<blob>`), so they cannot be replayed by URL. Room
pages are therefore also indexed by **room name**, and `run_parse --offline`
replays them by name. For a page store created before this index existed, build
it once (fast, no network):

```bash
python -m src.parser.debug backfill-rooms
```

A fresh online crawl populates the name index automatically. Rooms whose detail
page was never stored still fall back to a name-only location when offline.

**Split crawl from parse with snapshots.** The spider writes every module it
found to `snapshots/modules_latest.json` (plus a dated `crawl-<ts>.json`) before
parsing, so crawling and parsing are independent, resumable steps:

```bash
scrapy crawl lecture_spider -a crawl_only=1          # crawl + snapshot only
python -m src.parser.run_parse                        # parse from the snapshot
python -m src.parser.run_parse --only "Rechnernetze"  # one module (regex)
python -m src.parser.run_parse --offline --resume --dump-dir debug/modules
```

`--resume` skips module URLs recorded in `snapshots/processed_modules.txt`;
failures are logged to `snapshots/failed_modules.jsonl`. Add
`-a stream_snapshot=1` to stream modules to `snapshots/modules_stream.jsonl`
while crawling, so a crash does not lose crawl progress.

**Audit the whole dataset.** After a parse, check every row for missing links and
data, and diff the crawl snapshot against the database to catch modules that were
found but never stored (renames are reported separately from true misses):

```bash
python -m src.parser.audit --sample 10 --json audit.json
```

The exit code is non-zero on structural errors; `--strict` also fails on
warnings. The report also groups the recoverable warnings recorded during
parsing (`logs/parser-warnings.jsonl`, override with `ALMAWEB_LOG_DIR` or
`--warnings-log`) so repeated `failed_date` / `no_events_content` /
`room_fetch_error` patterns become visible across the whole run.

**Debug a single page.** Fetch/store a page and parse it in isolation:

```bash
python -m src.parser.debug fetch "<url>"
python -m src.parser.debug parse-module "<url|file>" --path Root --path "SoSe 26"
python -m src.parser.debug parse-course "<url|file>"
python -m src.parser.debug parse-room "<url|file>"
```

All debug artifacts (`.pagedata/`, `snapshots/`) are git-ignored.

## API

Interactive documentation is available at `http://localhost:8000/docs` once the server is running.

All collection endpoints support:
- **Paging** - `page` and `page_size` (pagination is disabled unless both are supplied)
- **Sorting** - `sort` with a column name and `order=asc|desc`
- **Field selection** - `fields` to return only specific columns
- **Relation includes** - `include` to embed related entities (e.g. `include=courses.modules`)
- **Export formats** - `format=json` (default), `format=csv`, and `format=ical` on event endpoints

### Query parameter conventions

- **Unknown parameters are ignored.** Only the parameters documented for an endpoint have an effect;
  any other query parameter is silently dropped (FastAPI behaviour). A parameter that exists on one
  resource does not necessarily exist on another — for example `/exams` accepts `staff_id` and
  `semester_id` but **not** `building_id`.
- **Repeated parameters** (`?id=1&id=2`) are combined with `OR` inside one filter; different filters
  are combined with `AND`.
- **`sort` / `order`** accept a single column only. Multi-level sorting has to be applied client-side
  (the client sends the primary level and sorts the remaining levels itself).
- **Invalid values return `422`** with an RFC 9457 problem document; malformed dates/times return `400`.

### Known limitations

- `/modules?language=…` — `Module.language` will be **deprecated in future major releases**; it is **now populated** and is derived from the module's
  courses at parse time, because AlmaWeb has no module-level language field. `Course.language` remains
  the authoritative value.
- `/exams?building_id=…` — **not available.** Exam records carry no room/building attribution in the
  source data, so `/exams` intentionally offers no `building_id` filter. Use `/events?building_id=…`
  (optionally combined with `module_id` / `course_id`) to find the rooms where the matching courses
  are taught.

### iCal Export

Event endpoints support `?format=ical` with customizable SUMMARY, DESCRIPTION, and LOCATION format strings via `ical_title_format`, `ical_description_format`, and `ical_location_format`. Placeholders use `{field_name}` syntax. An optional `ical_reminder_minutes` parameter adds a VALARM.

See [ical-format-api.md](ical-format-api.md) for planned improvements to iCal title resolution and additional export parameters.

#### Tools to view iCal files
- [ICS Viewer](https://icsviewer.com/) - A simple online tool to view .ics files without needing a calendar application.
- [Giga Tools iCal Viewer](https://giga.tools/data-tools/ical-ics-viewer) - Another online viewer with a clean interface.

## Configuration

**Faculty filter** - The crawler starts from the AlmaWeb external pages entry point and navigates the full semester tree, but currently only follows links under *10 - Fakultät für Mathematik und Informatik*. To target a different faculty, change the hard-coded prefix filter in `src/parser/crawler.py`.

**Concurrency** - The maximum number of concurrent requests is controlled by `MAX_CONCURRENT_MODULE_REQUESTS` in `src/parser/module_parser.py` (default: 4) and `MAX_CONCURRENT_COURSE_REQUESTS` in `src/parser/course_parser.py` (default: 8).

**Scrapy settings** - Throttling, caching, and other Scrapy options are in `src/settings.py`. AutoThrottle is enabled by default to avoid overloading the server.

## ToDo

Open work is tracked in [TODO.md](TODO.md) and prioritised in [plan.md](plan.md).
Current highlights from the offline page audit:

- [ ] Find the course `Termine` table on every page layout (374 courses currently store no sessions).
- [ ] Keep all rooms of a multi-room session (405 rows keep only the first room).
- [ ] Parse exam dates whose month has no trailing dot (`Mai`) and handle `ohne Termin`.
- [ ] Capture achievement `Leistungskombination` group rows.
- [ ] Parse course-level "Veranstaltungseigene Prüfungen".
- [ ] Do not abort a whole parse run when a single module fails to insert.
- [ ] Merge/enrich name-only locations (410 locations, 13 173 events without building/address).

## Future Ideas

### Crawler
- [ ] Add a periodic re-crawl mechanism that updates existing records instead of requiring a full re-run
- [ ] Add a `last_updated` timestamp to each datapoint
- [ ] Better error handling and logging in the crawler to identify and recover from parsing issues
- [ ] Add recovery from partial failures (if one module fails to parse, still ingest the rest of the data)
- [ ] Resume from the last successful point instead of starting over if the crawler exits halfway

### API
- [ ] Make endpoints compatible with the [planer app](https://github.com/natureFrameworkManager/planer)

### Data Model
- [ ] Optimize event storage (159k+ events per run)