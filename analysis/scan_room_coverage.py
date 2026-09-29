#!/usr/bin/env python3
"""Room-detail coverage: which locations stayed name-only although a detail page exists.

Read-only. Parses every cached room page (``PRGNAME=ACTION``) in ``.pagedata`` and
compares it with the locations stored in ``database.db``:

* locations with an empty ``external_id`` (name-only fallback) whose room *name*
  is available as a cached detail page -> these could have been enriched but were
  not (fetch/parse/lookup miss);
* events that reference a name-only location (they lose building/address/seats);
* how many Termine room cells carry a detail-page anchor vs free text.

    python analysis/scan_room_coverage.py
    python analysis/scan_room_coverage.py --json analysis/out2/room_coverage.json
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from bs4 import BeautifulSoup

REPO = Path(__file__).resolve().parent.parent
PAGEDATA = REPO / ".pagedata"
DB = REPO / "database.db"
sys.path.insert(0, str(REPO))

os.environ.setdefault("ALMAWEB_LOG_DIR", str(REPO / "analysis" / "out2" / "warnings"))

from src.parser.room_parser import parseRoom  # noqa: E402
from src.parser.utils import set_warning_print  # noqa: E402

set_warning_print(False)


def cached_room_pages(root: Path):
    for sidecar in root.glob("*/*.json"):
        html = sidecar.with_suffix(".html")
        if not html.is_file():
            continue
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if "PRGNAME=ACTION" in str(meta.get("url", "")):
            yield html


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(PAGEDATA))
    parser.add_argument("--db", default=str(DB))
    parser.add_argument("--json", default=None)
    args = parser.parse_args()

    cached: dict[str, dict] = {}
    for html in cached_room_pages(Path(args.root)):
        room = parseRoom(html.read_text(encoding="utf-8", errors="replace"))
        if room and room.get("name"):
            cached[room["name"].strip()] = room
    print(f"cached room detail pages: {len(cached)}")

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    cur = con.cursor()
    locations = cur.execute("SELECT id, name, external_id FROM location").fetchall()
    nameless = [r for r in locations if not (r[2] or "").strip()]
    recoverable = [r for r in nameless if (r[1] or "").strip() in cached]
    print(f"DB locations: {len(locations)}; name-only (empty external_id): {len(nameless)}")
    print(f"name-only locations whose detail page IS cached: {len(recoverable)}")

    events_on_nameless = cur.execute(
        "SELECT COUNT(*) FROM event e JOIN location l ON l.id=e.location_id WHERE l.external_id=''"
    ).fetchone()[0]
    distinct_nameless_used = cur.execute(
        "SELECT COUNT(DISTINCT e.location_id) FROM event e JOIN location l ON l.id=e.location_id WHERE l.external_id=''"
    ).fetchone()[0]
    print(f"events on name-only locations: {events_on_nameless} over {distinct_nameless_used} locations")

    print("\nsample recoverable-but-empty locations:")
    for loc_id, name, _ in recoverable[:15]:
        print(f"  {loc_id:>5}  {name!r}")

    # Termine room-cell anchors vs free text
    anchor = free = 0
    for sidecar in Path(args.root).glob("*/*.json"):
        html = sidecar.with_suffix(".html")
        if not html.is_file():
            continue
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if "COURSEDETAILS" not in str(meta.get("url", "")):
            continue
        soup = BeautifulSoup(html.read_text(encoding="utf-8", errors="replace"), "html.parser")
        for cell in soup.select("td.rw-course-room"):
            if cell.find("a", attrs={"name": "appointmentRooms"}) is not None:
                anchor += 1
            elif cell.get_text(" ", strip=True):
                free += 1
    print(f"\nTermine room cells: with detail anchor={anchor}; free text only={free}")

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "cached_room_pages": len(cached),
            "db_locations": len(locations),
            "name_only_locations": len(nameless),
            "recoverable_but_empty": [{"id": i, "name": n} for i, n, _ in recoverable],
            "events_on_name_only": events_on_nameless,
            "room_cells_with_anchor": anchor,
            "room_cells_free_text": free,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
