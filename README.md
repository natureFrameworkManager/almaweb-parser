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
   This takes roughly 10 minutes. The crawler walks every page of the module tree, fetches up to 4 module pages and 8 course pages concurrently, and writes results to `database.db` as it goes. Progress is saved incrementally - interrupt with `Ctrl+C` and the modules parsed so far are kept.
5. Start the API server:
   ```bash
   fastapi dev src/api/main.py
   ```

## API

Interactive documentation is available at `http://localhost:8000/docs` once the server is running.

All collection endpoints support:
- **Paging** - `offset` and `limit`
- **Sorting** - `sort` with field name, prefix `-` for descending
- **Field selection** - `fields` to return only specific columns
- **Relation includes** - `include` to embed related entities (e.g. `include=courses.modules`)
- **Export formats** - `format=json` (default), `format=csv`, and `format=ical` on event endpoints

### iCal Export

Event endpoints support `?format=ical` with customizable SUMMARY, DESCRIPTION, and LOCATION format strings via `ical_title_format`, `ical_description_format`, and `ical_location_format`. Placeholders use `{field_name}` syntax. An optional `ical_reminder_minutes` parameter adds a VALARM.

See [ical-format-api.md](ical-format-api.md) for planned improvements to iCal title resolution and additional export parameters.

## Configuration

**Faculty filter** - The crawler starts from the AlmaWeb external pages entry point and navigates the full semester tree, but currently only follows links under *10 - Fakultät für Mathematik und Informatik*. To target a different faculty, change the hard-coded prefix filter in `src/parser/crawler.py`.

**Concurrency** - The maximum number of concurrent requests is controlled by `MAX_CONCURRENT_MODULE_REQUESTS` in `src/parser/module_parser.py` (default: 4) and `MAX_CONCURRENT_COURSE_REQUESTS` in `src/parser/course_parser.py` (default: 8).

**Scrapy settings** - Throttling, caching, and other Scrapy options are in `src/settings.py`. AutoThrottle is enabled by default to avoid overloading the server.

## Future Ideas

### Crawler
- [ ] Add a periodic re-crawl mechanism that updates existing records instead of requiring a full re-run
- [ ] Add a `last_updated` timestamp to each datapoint
- [ ] Better error handling and logging in the crawler to identify and recover from parsing issues
- [ ] Add recovery from partial failures (if one module fails to parse, still ingest the rest of the data)
- [ ] Resume from the last successful point instead of starting over if the crawler exits halfway

### API — Filters
- [ ] Modules: filter by specific `path` segments or exact path prefixes instead of only free-text search
- [x] Courses: filter by exact staff members within the parsed `staff` list
- [ ] Events: filter by exact staff members within the parsed event `staff` list
- [x] Events: add normalized location filters to distinguish building, room, and free-text notes

### API — Endpoints
- [x] Expose a room/location schedule endpoint (all events in a given room on a given day)

### Data Model
- [ ] Parse degree and semester information from the path or other sources
- [ ] Optimize event storage (57k+ entries per semester)

### Infrastructure
- [x] Containerize with Docker
- [ ] Make endpoints compatible with the [planer app](https://github.com/natureFrameworkManager/planer)