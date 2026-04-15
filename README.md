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
- [ ] Support crawling multiple faculties or semesters in a single run
- [ ] Add a periodic re-crawl mechanism that updates existing records instead of requiring a full re-run
- [ ] Add a `last_updated` timestamp to each datapoint
- [ ] Better error handling and logging in the crawler to identify and recover from parsing issues

### API - Filters
- [ ] Modules: filter by specific `path` segments or exact path prefixes instead of only free-text search
- [ ] Modules: wire up declared but inactive filters (`responsible_person`, `faculty_id`, `semester_id`, `staff_id`, `course_id`, `has_courses`, `has_events`, `has_staff`)
- [ ] Courses: filter by exact staff members within the parsed `staff` list
- [ ] Courses: wire up `has_events` filter (declared but commented out)
- [ ] Events: wire up `course_id` and `module_id` direct filters (declared but commented out)
- [ ] Events: filter by exact staff members within the parsed event `staff` list
- [ ] Events: add normalized location filters to distinguish building, room, and free-text notes

### API - Endpoints
- [ ] Implement `/distinct/{field}` endpoints (currently stubs on all routers except faculties)
- [ ] Implement `/schedule/weekly` with actual filtering, day-grouping, and deduplication
- [ ] Implement `/admin/health` with database connectivity info
- [ ] Implement `/admin/sync` endpoints to trigger and manage ingestion runs
- [ ] Add a `/api/modules/{id}/ical` shortcut to export the timetable of a single module directly
- [ ] Expose a room/location schedule endpoint (all events in a given room on a given day)

### Data Model
- [ ] Handle courses of multiple modules with a many-to-many relationship where necessary
- [ ] Parse degree and semester information from the path or other sources
- [ ] Normalize events to a single week pattern and time slot format by collapsing dates
- [ ] Optimize event storage (57k+ entries per semester)

### iCal Export
- [ ] Fix event SUMMARY for events with empty names by resolving titles from linked courses/modules
- [ ] Add `ical_title_mode` to control title assembly strategy (event / course / module / smart)
- [ ] Expand format placeholders to include `{course_name}`, `{module_name}`, `{staff_names}`, etc.
- [ ] Add `ical_fan_out` parameter to emit one VEVENT per course/module pair
- [ ] Add `ical_calendar_name`, `ical_timezone`, `ical_filename`, `ical_categories` parameters
- [ ] Add named presets via `ical_template` (compact / detailed / minimal)

### Infrastructure
- [ ] Add tests
- [ ] Containerize with Docker
- [ ] Use RFC 9457 Problem Details for error responses
- [ ] Make endpoints compatible with the [planer app](https://github.com/natureFrameworkManager/planer)