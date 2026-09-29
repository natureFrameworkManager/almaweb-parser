#!/usr/bin/env python3
"""Check that Termine (course session) rows are actually found and kept.

Read-only. Runs the *real* ``find_termine_section`` / ``extract_events`` on every
cached COURSEDETAILS page and reports pages where the DOM clearly has Termine rows
but the parser keeps none, plus rows whose date/time cell is empty (the DB
``event`` columns are ``NOT NULL``, so a ``None`` value aborts the whole module
insert in ``insert_module_graph``).

    python analysis/scan_event_detection.py --limit 0
    python analysis/scan_event_detection.py --limit 0 --json analysis/out/event_detection.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup

REPO = Path(__file__).resolve().parent.parent
PAGEDATA = REPO / ".pagedata"
sys.path.insert(0, str(REPO))

os.environ.setdefault("ALMAWEB_LOG_DIR", str(REPO / "analysis" / "out" / "warnings"))

from src.parser.course_parser import (  # noqa: E402
    _cell_value,
    extract_events,
    find_termine_section,
)
from src.parser.room_parser import set_room_fetch_enabled  # noqa: E402
from src.parser.utils import set_warning_print  # noqa: E402

set_warning_print(False)


def iter_courses(root: Path):
    for sidecar in root.glob("*/*.json"):
        html = sidecar.with_suffix(".html")
        if not html.is_file():
            continue
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if "PRGNAME=COURSEDETAILS" in str(meta.get("url", "")):
            yield html


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(PAGEDATA))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--json", default=None)
    args = parser.parse_args()

    set_room_fetch_enabled(False)
    pages = 0
    pages_with_rows = 0
    pages_rows_but_no_events = 0
    pages_partial_drop = 0
    samples_dropped: list[str] = []
    samples_partial: list[str] = []
    empty_date = 0
    empty_start = 0
    empty_end = 0
    missing_date_cell = 0
    none_after_parse = Counter()
    none_samples: list[str] = []

    for html in iter_courses(Path(args.root)):
        pages += 1
        source = html.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(source, "html.parser")
        header = soup.find("h1")
        name = re.sub(r"\s+", " ", header.get_text(" ", strip=True)) if header else html.name
        right = soup.select_one("#contentlayoutright")
        section = find_termine_section(right)

        # Independent of find_termine_section: every session row has a cell with
        # name="appointmentDate". If a page has such rows but the parser resolves
        # no Termine section, the whole schedule is silently dropped.
        raw_rows = []
        for date_cell in soup.select('td[name="appointmentDate"]'):
            tr = date_cell.find_parent("tr")
            if tr is not None:
                raw_rows.append(tr)
        pages_with_rows += 1 if raw_rows else 0

        events = extract_events(section, name) if section is not None else []

        if raw_rows and not events:
            pages_rows_but_no_events += 1
            if len(samples_dropped) < 20:
                samples_dropped.append(f"{name[:60]!r}  raw_rows={len(raw_rows)} section={'yes' if section else 'no'}")
        elif len(events) < len(raw_rows):
            pages_partial_drop += 1
            if len(samples_partial) < 20:
                samples_partial.append(f"{name[:60]!r}  raw_rows={len(raw_rows)} events={len(events)}")

        for row in raw_rows:
            cells = row.find_all("td", recursive=False)
            by_name = {c.get("name"): c for c in cells if c.get("name")}
            date_cell = by_name.get("appointmentDate")
            start_cell = by_name.get("appointmentTimeFrom")
            end_cell = by_name.get("appointmentDateTo")
            if date_cell is None:
                missing_date_cell += 1
            elif not _cell_value(date_cell):
                empty_date += 1
            if start_cell is not None and not _cell_value(start_cell):
                empty_start += 1
            if end_cell is not None and not _cell_value(end_cell):
                empty_end += 1

        for ev in events:
            for key in ("event_date", "start_time", "end_time"):
                if ev.get(key) is None:
                    none_after_parse[key] += 1
                    if len(none_samples) < 20:
                        none_samples.append(f"{name[:60]!r} {key}=None")

        if args.limit and pages >= args.limit:
            break

    print(f"Scanned {pages} course pages; with Termine rows={pages_with_rows}")
    print(f"Pages with raw rows but parser kept 0 events: {pages_rows_but_no_events}")
    for sample in samples_dropped:
        print(f"  {sample}")
    print(f"Pages where the parser kept fewer events than raw rows: {pages_partial_drop}")
    for sample in samples_partial:
        print(f"  {sample}")
    print(f"\nRows missing the appointmentDate cell: {missing_date_cell}")
    print(f"Rows with an empty date cell: {empty_date}")
    print(f"Rows with an empty start-time cell: {empty_start}")
    print(f"Rows with an empty end-time cell: {empty_end}")
    print(f"\nParsed events with None fields (would break NOT NULL insert): {dict(none_after_parse)}")
    for sample in none_samples:
        print(f"  {sample}")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "pages": pages,
            "pages_with_rows": pages_with_rows,
            "pages_rows_but_no_events": pages_rows_but_no_events,
            "dropped_samples": samples_dropped,
            "pages_partial_drop": pages_partial_drop,
            "partial_samples": samples_partial,
            "missing_date_cell": missing_date_cell,
            "empty_date": empty_date,
            "empty_start": empty_start,
            "empty_end": empty_end,
            "none_after_parse": dict(none_after_parse),
            "none_samples": none_samples,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
