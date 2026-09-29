#!/usr/bin/env python3
"""Audit the current course parser against the cached COURSEDETAILS pages.

Read-only. Runs ``parseCourse`` (rooms disabled, no network) over every cached
course page and compares the stored fields with an independent DOM extraction to
surface silent data loss:

* scalar fields read from the wrong node (``Lehrende`` uses ``row.find("span")``,
  which collapses to the *first* value span when a cell carries several)
* Termine rows the parser drops (missing/blank date or time -> the DB ``event``
  columns are ``NOT NULL``, so a ``None`` would abort the whole module insert)
* multiple rooms in one Termine row (only the first is kept)
* staff values that do not look like a person

    python analysis/compare_course_capture.py --limit 0
    python analysis/compare_course_capture.py --limit 0 --json analysis/out/course_capture.json
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

# Route any parser warnings this audit triggers into analysis/out (never the repo log).
os.environ.setdefault("ALMAWEB_LOG_DIR", str(REPO / "analysis" / "out" / "warnings"))

from src.parser.course_parser import (  # noqa: E402
    _COURSE_LABEL_MAP,
    _MOBILE_LABEL_CLASS,
    _MONTHS,
    _TIME_ONLY_RE,
    _DATE_ONLY_RE,
    _cell_value,
    parseCourse,
)
from src.parser.room_parser import set_room_fetch_enabled  # noqa: E402
from src.parser.utils import set_warning_print, text_with_structure  # noqa: E402

set_warning_print(False)

_WS = re.compile(r"\s+")


def norm(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def _date_ok(value: str) -> bool:
    """Non-logging replica of ``_parse_date``: True if it yields a real date."""
    m = re.search(r"(\d{1,2})\.\s*(\w{3})\.?\s*(\d{4})", value)
    if not m:
        return False
    month = _MONTHS.get(m.group(2))
    if month is None:
        return False
    import datetime
    try:
        datetime.date(int(m.group(3)), month, int(m.group(1)))
        return True
    except ValueError:
        return False


def _time_ok(value: str) -> bool:
    """Non-logging replica of ``_parse_time``: True if it yields a real time."""
    m = re.search(r"(\d{1,2}):(\d{2})", value)
    if not m:
        return False
    hour, minute = int(m.group(1)), int(m.group(2))
    if hour == 24 and minute == 0:
        return True
    return 0 <= hour <= 23 and 0 <= minute <= 59


def iter_pages(root: Path, prgname: str):
    for sidecar in root.glob("*/*.json"):
        html = sidecar.with_suffix(".html")
        if not html.is_file():
            continue
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if f"PRGNAME={prgname}" in str(meta.get("url", "")):
            yield html


def value_container(row, label_tag):
    """The element holding the field's value: the row's next sibling after <b>."""
    sibling = label_tag.find_next_sibling()
    return sibling if sibling is not None else row



def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(PAGEDATA))
    parser.add_argument("--limit", type=int, default=0, help="0 = all pages")
    parser.add_argument("--json", default=None)
    args = parser.parse_args()

    set_room_fetch_enabled(False)
    root = Path(args.root)

    pages = 0
    parsed_ok = 0
    parse_failed = 0
    field_truncations = 0
    trunc_by_label: Counter = Counter()
    trunc_samples: list[dict] = []
    multi_value_cells: Counter = Counter()
    multi_value_samples: list[str] = []
    raw_event_rows = 0
    parsed_events = 0
    event_count_mismatch = 0
    none_date = 0
    none_time = 0
    none_date_samples: list[str] = []
    multi_room = 0
    multi_room_samples: list[str] = []
    suspect_staff: Counter = Counter()

    for html in iter_pages(root, "COURSEDETAILS"):
        pages += 1
        source = html.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(source, "html.parser")
        header = soup.find("h1")
        page_name = norm(header.get_text(" ", strip=True)) if header else html.name
        left = soup.select_one("#contentlayoutleft")

        # --- independent scalar extraction vs parser mapping ---
        if left is not None:
            for row in left.select(".tbdata"):
                label_tag = row.find("b", recursive=False)
                if label_tag is None:
                    continue
                label = norm(label_tag.get_text(" ", strip=True)).rstrip(":")
                entry = _COURSE_LABEL_MAP.get(label)
                if entry is None:
                    continue
                _, tag_name = entry
                container = value_container(row, label_tag)
                truth = text_with_structure(container)
                sub = row.find(tag_name)
                got = text_with_structure(sub) if sub is not None else ""
                spans = [
                    s for s in container.find_all("span")
                    if _MOBILE_LABEL_CLASS not in (s.get("class") or [])
                ]
                if label == "Lehrende" and len(spans) > 1:
                    multi_value_cells[label] += len(spans)
                    if len(multi_value_samples) < 10:
                        multi_value_samples.append(
                            f"{page_name}: {len(spans)} spans -> parser keeps {got!r}")
                if truth and got and got not in truth and truth not in got:
                    field_truncations += 1
                    trunc_by_label[label] += 1
                    if len(trunc_samples) < 25:
                        trunc_samples.append({
                            "page": page_name, "label": label, "truth": truth[:200], "parsed": got,
                        })

        # --- Termine table: raw rows vs parser ---
        right = soup.select_one("#contentlayoutright")
        if right is not None:
            row_nodes = right.select("table tbody tr")
            raw_event_rows += len(row_nodes)
            for row in row_nodes:
                cells = row.find_all("td", recursive=False)
                if not cells:
                    continue
                by_name = {c.get("name"): c for c in cells if c.get("name")}
                date_cell = by_name.get("appointmentDate")
                start_cell = by_name.get("appointmentTimeFrom")
                end_cell = by_name.get("appointmentDateTo")
                date_raw = _cell_value(date_cell) if date_cell is not None else ""
                start_raw = _cell_value(start_cell) if start_cell is not None else ""
                end_raw = _cell_value(end_cell) if end_cell is not None else ""
                if date_raw and not _date_ok(date_raw):
                    none_date += 1
                    if len(none_date_samples) < 20:
                        none_date_samples.append(f"{page_name}: date={date_raw!r}")
                if (start_raw and not _time_ok(start_raw)) or (end_raw and not _time_ok(end_raw)):
                    none_time += 1
                room_cell = next((c for c in cells if "rw-course-room" in (c.get("class") or [])), None)
                anchors = room_cell.find_all("a", attrs={"name": "appointmentRooms"}) if room_cell is not None else []
                if len(anchors) > 1:
                    multi_room += 1
                    if len(multi_room_samples) < 10:
                        multi_room_samples.append(
                            f"{page_name}: " + " | ".join(a.get_text(" ", strip=True) for a in anchors))

        # --- parser output ---
        try:
            course = parseCourse(source)
        except Exception:  # noqa: BLE001
            parse_failed += 1
            continue
        if course is None:
            parse_failed += 1
            continue
        parsed_ok += 1
        parsed_events += len(course["events"])
        for staff in course["staff"]:
            if _TIME_ONLY_RE.match(staff) or _DATE_ONLY_RE.match(staff) or "Termin" in staff:
                suspect_staff[staff] += 1

        if args.limit and pages >= args.limit:
            break

    print(f"Scanned {pages} course pages; parsed ok={parsed_ok}; parse failures={parse_failed}")
    print(f"\nMulti-value Lehrende cells (parser keeps first span only): {sum(multi_value_cells.values())}")
    for sample in multi_value_samples:
        print(f"  {sample}")
    print(f"\nScalar value truncation/mismatch: {field_truncations}")
    for label, count in trunc_by_label.most_common():
        print(f"  {count:>6}  {label!r}")
    for sample in trunc_samples[:20]:
        print(f"    {sample['page'][:45]!r} {sample['label']!r}: "
              f"truth={sample['truth']!r} parsed={sample['parsed']!r}")

    print(f"\nTermine raw rows={raw_event_rows}; parsed events={parsed_events}; "
          f"count mismatches={event_count_mismatch}")
    print(f"Rows with unparseable (non-empty) date -> None: {none_date}")
    for sample in none_date_samples:
        print(f"  {sample}")
    print(f"Rows with unparseable (non-empty) time -> None: {none_time}")
    print(f"Rows with multiple rooms (only first kept): {multi_room}")
    for sample in multi_room_samples:
        print(f"  {sample}")
    print(f"Suspect staff entries (look like times/dates): {sum(suspect_staff.values())}")
    for value, count in suspect_staff.most_common(10):
        print(f"  {count:>5}  {value!r}")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "pages": pages,
            "parsed_ok": parsed_ok,
            "parse_failed": parse_failed,
            "multi_value_lehrende": sum(multi_value_cells.values()),
            "multi_value_samples": multi_value_samples,
            "field_truncations": field_truncations,
            "trunc_by_label": dict(trunc_by_label),
            "trunc_samples": trunc_samples,
            "raw_event_rows": raw_event_rows,
            "parsed_events": parsed_events,
            "event_count_mismatch": event_count_mismatch,
            "none_date": none_date,
            "none_date_samples": none_date_samples,
            "none_time": none_time,
            "multi_room": multi_room,
            "multi_room_samples": multi_room_samples,
            "suspect_staff": dict(suspect_staff),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
