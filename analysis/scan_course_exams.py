#!/usr/bin/env python3
"""Show that "Veranstaltungseigene Prüfungen" (course-level exams) are dropped.

The COURSEDETAILS page carries a ``Veranstaltungseigene Prüfungen`` table
(``name="examName"`` / ``name="examDate"`` / staff / ``Pflicht``). ``parseCourse``
never reads it, so these course-specific exam dates are not part of the parsed
data or the data model.

    python analysis/scan_course_exams.py --limit 0
    python analysis/scan_course_exams.py --limit 0 --json analysis/out/course_exams.json
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

from src.parser.course_parser import parseCourse  # noqa: E402
from src.parser.room_parser import set_room_fetch_enabled  # noqa: E402
from src.parser.utils import set_warning_print  # noqa: E402

set_warning_print(False)
_WS = re.compile(r"\s+")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(PAGEDATA))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--json", default=None)
    args = parser.parse_args()

    set_room_fetch_enabled(False)
    pages = 0
    scanned = 0
    pages_with_exams = 0
    exam_rows = 0
    dates: Counter = Counter()
    samples: list[dict] = []

    for sidecar in Path(args.root).glob("*/*.json"):
        html = sidecar.with_suffix(".html")
        if not html.is_file():
            continue
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if "PRGNAME=COURSEDETAILS" not in str(meta.get("url", "")):
            continue
        pages += 1
        source = html.read_text(encoding="utf-8", errors="replace")
        if "Veranstaltungseigene Prüfungen" not in source:
            continue
        scanned += 1
        soup = BeautifulSoup(source, "html.parser")
        for table in soup.find_all("table"):
            if "Veranstaltungseigene Prüfungen" not in table.get_text(" ", strip=True) and \
               table.find(attrs={"name": "examDate"}) is None:
                continue
            rows = table.select("tbody tr")
            if not rows:
                continue
            pages_with_exams += 1
            for row in rows:
                cells = row.find_all("td", recursive=False)
                by_name = {c.get("name"): c for c in cells if c.get("name")}
                if "examDate" not in by_name:
                    continue
                exam_rows += 1
                name = _WS.sub(" ", by_name.get("examName").get_text(" ", strip=True)) if by_name.get("examName") else ""
                date = _WS.sub(" ", by_name["examDate"].get_text(" ", strip=True))
                date = re.sub(r"^Datum\s+", "", date)
                dates[date] += 1
                if len(samples) < 15:
                    samples.append({"name": name, "date": date})
            break
        if args.limit and scanned >= args.limit:
            break

    print(f"Scanned {pages} course pages; containing 'Veranstaltungseigene Prüfungen'={scanned}")
    print(f"Pages with such an exam table={pages_with_exams}; exam rows={exam_rows}")
    print("Sample rows (never parsed, never stored):")
    for sample in samples:
        print(f"  {sample['name'][:50]!r}  {sample['date']!r}")
    print("Most common dates:")
    for value, count in dates.most_common(10):
        print(f"  {count:>5}  {value!r}")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "pages": pages,
            "pages_with_section": scanned,
            "pages_with_exam_table": pages_with_exams,
            "exam_rows": exam_rows,
            "dates": dict(dates),
            "samples": samples,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
