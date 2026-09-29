#!/usr/bin/env python3
"""Quantify the global event dedup collapse (read-only).

``_insert_event_if_new`` treats two sessions as the same physical event when they
share ``(event_date, start_time, end_time, location_id)`` **globally** -- the
course is not part of the key, and a ``NULL`` location matches ``NULL``. Two
unrelated courses that have a session at the same time *without a room* are
therefore merged into one row.

This script replays every cached COURSEDETAILS page through the real
``parseCourse`` (rooms disabled, fully offline), builds the same dedup key the DB
uses and reports how many distinct source sessions collapse.

    python analysis/check_event_collisions.py --limit 2000
    python analysis/check_event_collisions.py --limit 0      # all ~15k pages
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

REPO = Path(__file__).resolve().parent.parent
PAGEDATA = REPO / ".pagedata"
sys.path.insert(0, str(REPO))

from src.parser.course_parser import parseCourse  # noqa: E402
from src.parser.fetch import create_cached_client  # noqa: E402
from src.parser.room_parser import set_room_fetch_enabled  # noqa: E402


def prgname_of(url: str) -> str:
    return (parse_qs(urlsplit(url).query).get("PRGNAME") or ["<none>"])[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(PAGEDATA))
    parser.add_argument("--limit", type=int, default=2000)
    parser.add_argument("--json", default=None)
    args = parser.parse_args()

    set_room_fetch_enabled(False)
    root = Path(args.root)

    key_to_courses: dict[tuple, set[str]] = defaultdict(set)
    courses_seen = 0
    total_events = 0
    null_location = 0
    pages_scanned = 0

    with create_cached_client(offline=True) as client:
        for sidecar in root.glob("*/*.json"):
            html_path = sidecar.with_suffix(".html")
            if not html_path.is_file():
                continue
            try:
                meta = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if prgname_of(str(meta.get("url", ""))) != "COURSEDETAILS":
                continue
            pages_scanned += 1
            try:
                course = parseCourse(html_path.read_text(encoding="utf-8", errors="replace"), client=client)
            except Exception:
                course = None
            if course is None:
                continue
            courses_seen += 1
            cid = f"{course['number']} {course['name']}"
            for ev in course["events"]:
                total_events += 1
                loc = ev.get("location")
                loc_name = (loc or {}).get("name", "") if isinstance(loc, dict) else ""
                if not loc_name:
                    null_location += 1
                key = (ev.get("event_date"), ev.get("start_time"), ev.get("end_time"), loc_name)
                key_to_courses[key].add(cid)
            if args.limit and pages_scanned >= args.limit:
                break

    distinct_keys = len(key_to_courses)
    shared = {k: v for k, v in key_to_courses.items() if len(v) > 1}
    shared_null = {k: v for k, v in shared.items() if not k[3]}

    print(f"Scanned course pages: {pages_scanned}  (parsed {courses_seen})")
    print(f"Source session rows: {total_events}")
    print(f"  of which without a room: {null_location}")
    print(f"Distinct dedup keys (event_date, start, end, room): {distinct_keys}")
    print(f"Keys shared by >1 course: {len(shared)}  (null-room: {len(shared_null)})")
    print(f"Sessions lost to the dedup collapse (rows - distinct keys): {total_events - distinct_keys}")
    print(f"  ...of those, from sessions without a room: {null_location - sum(1 for k in key_to_courses if not k[3])}")

    print("\nTop collisions (same date/time/room reused by many courses):")
    for key, courses in sorted(shared.items(), key=lambda kv: -len(kv[1]))[:15]:
        when = f"{key[0]} {key[1]}-{key[2]}" if key[0] else "(no date)"
        room = key[3] or "(no room)"
        print(f"  {len(courses):>3}x  {when}  [{room}]  e.g. {sorted(courses)[:2]}")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "pages_scanned": pages_scanned,
            "courses_parsed": courses_seen,
            "source_sessions": total_events,
            "source_sessions_without_room": null_location,
            "distinct_keys": distinct_keys,
            "sessions_lost_to_dedup": total_events - distinct_keys,
            "shared_keys": len(shared),
            "shared_keys_null_room": len(shared_null),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
