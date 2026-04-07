# Almaweb Parser & API

Scrapes the Almaweb *Vorlesungsverzeichnis* (course catalogue) of the University of Leipzig and exposes the collected data through a REST API.

The crawler walks the full module tree, parses each module and its courses, and stores everything in a local SQLite database. The API then serves that data with filtering and iCalendar export.

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

## Configuration

**Starting URL** - The crawler currently starts from the *SoSe 2026 - Fakultät für Mathematik und Informatik* page. To target a different faculty or semester, replace the URL in the `start_urls` list in `src/parser/crawler.py`.

**Concurrency** - The maximum number of concurrent requests is controlled by `MAX_CONCURRENT_MODULE_REQUESTS` in `src/parser/module_parser.py` (default: 4) and `MAX_CONCURRENT_COURSE_REQUESTS` in `src/parser/course_parser.py` (default: 8).

**Scrapy settings** - Throttling, caching, and other Scrapy options are in `src/settings.py`. AutoThrottle is enabled by default to avoid overloading the server.

## Future Ideas

- [ ] Implement the `path_search` filter on `/api/modules` (the parameter exists but is not yet applied to the query).
- [ ] Support crawling multiple faculties or semesters in a single run and differentiating them in the database.
- [ ] Add a periodic re-crawl mechanism that updates existing records rather than requiring a full re-run.
- [ ] Add a `/api/modules/{id}/ical` shortcut to export the timetable of a single module directly.
- [ ] Expose a room/location schedule endpoint (all events in a given room on a given day).
- [ ] Add more detailed error handling and logging in the crawler to identify and recover from parsing issues.
- [ ] Containerize the application with Docker for easier deployment.
- [ ] Add tests
- [ ] Parse room data, which is linked from each event entry inside AlmaWeb
- [ ] Add filters for multiple modules or courses at once (e.g. `?module_id=123&module_id=456`)
- [ ] Add a `last_updated` timestamp to each datapoint
- [ ] Add optional paging and limiting
- [ ] Add more filters and fields to the single entity endpoints
- [ ] Add more filters
- [ ] Possibly handle courses of multiple modules and introduce a many-to-many relationship where necessary
- [ ] Parse degree and semester information from the path or other points
- [ ] Make the endpoints compatible with the [planer app](https://github.com/natureFrameworkManager/planer) 