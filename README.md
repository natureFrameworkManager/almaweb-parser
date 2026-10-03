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
   scrapy crawl lecture_spider -a progress_bar=1      # Run with progress bar  
   scrapy crawl lecture_spider -a sync_degrees=1      # Derive degrees at the end of the crawl  
   scrapy crawl lecture_spider -a crawl_only=1        # Crawl + snapshot only, no parsing
   scrapy crawl lecture_spider -a stream_snapshot=1   # Stream modules to a snapshot during the crawl
   ```
5. Start the API server:
   ```bash
   fastapi dev src/api/main.py      # Development server
   fastapi run src/api/main.py      # Production server
   ```

## Separate Parsing
```bash
python -m src.parser.run_parse                                                          # parse from the snapshots under `snapshots/`
python -m src.parser.run_parse --only "Rechnernetze"                                    # one module (regex)
python -m src.parser.run_parse --number "<module_number>"                               # one module by its number
python -m src.parser.run_parse --path-contains "<substring>"                            # modules whose path contains the given substring
python -m src.parser.run_parse --semester "<semester>"                                  # modules from a specific semester
python -m src.parser.run_parse --limit "<number>"                                       # limit the number of modules to parse
python -m src.parser.run_parse --refresh                                                # force refresh of cached pages
python -m src.parser.run_parse --processed-file "<file>"                                # specify a file containing already processed modules
python -m src.parser.run_parse --offline                                                # run in offline mode
python -m src.parser.run_parse --resume                                                 # resume from the last processed module  
python -m src.parser.run_parse --dump-dir debug/modules                                 # dump debug artifacts to this directory
python -m src.parser.run_parse --no-rooms                                               # skip parsing room information
python -m src.parser.run_parse --key-strategy "<exact|query-sorted|ignore-arguments>"   # specify the key strategy for parsing
```

### Debug a single page
```bash
python -m src.parser.debug fetch "<url>"  [--offline] [--refresh] [--no-rooms] [--key-strategy <exact|query-sorted|ignore-arguments>]
python -m src.parser.debug parse-module "<url|file>" --path Root --path "SoSe 26" [--offline] [--refresh] [--no-rooms] [--key-strategy <exact|query-sorted|ignore-arguments>]
python -m src.parser.debug parse-course "<url|file>" [--offline] [--refresh] [--no-rooms] [--key-strategy <exact|query-sorted|ignore-arguments>]
python -m src.parser.debug parse-room "<url|file>" [--offline] [--refresh] [--no-rooms] [--key-strategy <exact|query-sorted|ignore-arguments>]
python -m src.parser.debug backfill-rooms [--key-strategy <exact|query-sorted|ignore-arguments>]
```

### Audit the whole dataset
After a parse, check every row for missing links and data, and diff the crawl snapshot against the database to catch modules that were found but never stored (renames are reported separately from true misses):

```bash
python -m src.parser.audit --sample 10                          # sample 10 rows for auditing
python -m src.parser.audit --json audit.json                    # output audit results to a JSON file
python -m src.parser.audit --strict                             # fail on any warnings
python -m src.parser.audit --warnings-log audit-warnings.jsonl  # log warnings to a separate file
python -m src.parser.audit --no-warnings                           # no warnings summary
python -m src.parser.audit --snapshot                           # Snapshot file path
```

## API

Interactive **swagger** documentation is available at `http://localhost:8000/docs` once the server is running.

All collection endpoints support:
- **Paging** - `page` and `page_size` (pagination is disabled unless both are supplied)
- **Sorting** - `sort` with a column name and `order=asc|desc`
- **Field selection** - `fields` to return only specific columns
- **Relation includes** - `include` to embed related entities (e.g. `include=courses.modules`)
- **Export formats** - `format=json` (default), `format=csv`, and `format=ical` on event endpoints

### Known limitations

- `/modules?language=…` — `Module.language` will be **deprecated in future major releases**; it is **now populated** and is derived from the module's courses at parse time, because AlmaWeb has no module-level language field. `Course.language` remains the authoritative value.
- `/exams?building_id=…` — **not available.** Exam records carry no public room/building attribution in the source data, so `/exams` intentionally offers no `building_id` filter. Use `/events?building_id=…` (optionally combined with `module_id` / `course_id`) to find the rooms where the matching courses are taught.

### iCal Export

Event endpoints support `?format=ical` with customizable SUMMARY, DESCRIPTION, and LOCATION format strings via `ical_title_format`, `ical_description_format`, and `ical_location_format`. Placeholders use `{field_name}` syntax. An optional `ical_reminder_minutes` parameter adds a VALARM.

See [ical-format-api.md](/future-plan-docs/ical-format-api.md) for planned improvements to iCal title resolution and additional export parameters.

#### Tools to view iCal files
- [ICS Viewer](https://icsviewer.com/) - A simple online tool to view .ics files without needing a calendar application.
- [Giga Tools iCal Viewer](https://giga.tools/data-tools/ical-ics-viewer) - Another online viewer with a clean interface.

## Configuration

**Faculty filter** - You can change the starting page of the crawler and the followed semesters and faculties by modifying the relevant settings in `src/parser/crawler.py` with the variable `start_urls`, the `semesterNodes`, and the `name` of the `navigationNodes`. Also the `module_list` can be adjusted to control which modules are included in the crawl.

**Concurrency** - The maximum number of concurrent requests is controlled by `MAX_CONCURRENT_MODULE_REQUESTS` in `src/parser/module_parser.py` (default: 4) and `MAX_CONCURRENT_COURSE_REQUESTS` in `src/parser/course_parser.py` (default: 8).

**Scrapy settings** - Throttling, caching, and other Scrapy options are in `src/settings.py`. AutoThrottle is enabled by default to avoid overloading the server.

**Proxy root path** - The base path for the AlmaWeb API proxy is set via the `PROXY_ROOT_PATH` environment variable (default: `/almaweb/v1`). Adjust this if the proxy is mounted at a different path.

**DB file** - The path to the SQLite database file is set inside `src/database/database.py` under the `DATABASE_PATH` constant.

**Parser cache** - The parser cache settings are controlled via the `DEFAULT_PAGE_STORE_DIR` constant in `src/parser/fetch.py`. This directory is used to store cached pages for the offline debugging.

**Snapshot** - The snapshot settings are controlled via the `DEFAULT_SNAPSHOT_STORE_DIR` constant in `src/parser/fetch.py`. This directory is used to store snapshots of pages for offline debugging. The `LATEST_MODULES_FILE` constant in the same file points to the latest snapshot of modules. The `STREAM_MODULES_FILE` constant points to the filename that module data will be streamed to when using the `stream_snapshot=1` argument on the crawler.

## ToDo

Open work is tracked in [TODO.md](/future-plan-docs/TODO.md) and prioritised in [plan.md](/future-plan-docs/plan.md).

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

## Disclaimer regarding AI usage

Some AI tools and models may have been used to assist in the development of this project, including code generation and documentation. However, all final decisions, implementations, and verifications were performed by the developers. Users should independently verify any AI-generated content for accuracy and reliability.
I have checked all AI-generated content for accuracy and reliability.
**If any commit included AI-generated content, it has been marked with the `Assisted-by: <tool>:<model>` trailer.**

I am working to replace any AI-generated content with manually verified and developer-authored content. 
But some at some points I didn't have the nerve and time to write all code myself and just wanted it finished, so I relied on AI tools to assist me.

**Attention:**
The parser of a degree under `src/parser/path_parser/*` is fully generated by AI (`claude-sonnet-5`). Read the readme under this folder for more details.