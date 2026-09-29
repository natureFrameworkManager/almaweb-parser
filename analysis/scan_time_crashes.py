#!/usr/bin/env python3
"""Find time/date values that crash the parsers (read-only).

``_parse_time`` does ``time(hour, minute)`` with no range check, and
``_parse_date`` does ``date(year, month, day)`` with no validation. AlmaWeb emits
end times like ``24:00`` (midnight) and the occasional impossible date. Either
raises ``ValueError`` inside ``parseModule``/``parseCourse``, which is caught by
the broad ``except`` in ``_fetch_and_parse_module`` -- so the **entire module or
course is dropped**, not just the bad field.

    python analysis/scan_time_crashes.py --limit 0
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import date, time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

REPO = Path(__file__).resolve().parent.parent
PAGEDATA = REPO / ".pagedata"
sys.path.insert(0, str(REPO))

from src.parser.course_parser import _MONTHS  # noqa: E402

_WS = re.compile(r"\s+")


def prgname(url: str) -> str:
    return (parse_qs(urlsplit(url).query).get("PRGNAME") or ["<none>"])[0]


def norm(text: str) -> str:
    return _WS.sub(" ", text.replace("\xa0", " ")).strip()


def bad_time(value: str) -> str | None:
    m = re.search(r"(\d{1,2}):(\d{2})", value)
    if not m:
        return None
    try:
        time(int(m.group(1)), int(m.group(2)))
    except ValueError:
        return m.group(0)
    return None


def bad_date(value: str) -> str | None:
    m = re.search(r"(\d{1,2})\.\s*(\w{3})\.?\s*(\d{4})", value)
    if not m:
        return None
    try:
        date(int(m.group(3)), _MONTHS.get(m.group(2), 0), int(m.group(1)))
    except ValueError:
        return m.group(0)
    return None


def iter_pages(root: Path, kind: str):
    for sidecar in root.glob("*/*.json"):
        html = sidecar.with_suffix(".html")
        if not html.is_file():
            continue
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if prgname(str(meta.get("url", ""))) == kind:
            yield str(meta.get("url", "")), html


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(PAGEDATA))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--json", default=None)
    args = parser.parse_args()
    root = Path(args.root)

    module_bad_times: Counter = Counter()
    module_bad_dates: Counter = Counter()
    modules_at_risk: set[str] = set()
    course_bad_times: Counter = Counter()
    course_bad_dates: Counter = Counter()
    courses_at_risk: set[str] = set()

    scanned_modules = 0
    for url, html in iter_pages(root, "MODULEDETAILS"):
        scanned_modules += 1
        soup = BeautifulSoup(html.read_text(encoding="utf-8", errors="replace"), "html.parser")
        for td in soup.select("td.rw-detail-date"):
            value = re.sub(r"^Datum\s+", "", norm(td.get_text(" ", strip=True)))
            bt = bad_time(value)
            bd = bad_date(value)
            for token in re.findall(r"\d{1,2}:\d{2}", value):
                if bad_time(token):
                    module_bad_times[token] += 1
                    modules_at_risk.add(url)
            if bd:
                module_bad_dates[bd] += 1
                modules_at_risk.add(url)
        if args.limit and scanned_modules >= args.limit:
            break

    scanned_courses = 0
    for url, html in iter_pages(root, "COURSEDETAILS"):
        scanned_courses += 1
        soup = BeautifulSoup(html.read_text(encoding="utf-8", errors="replace"), "html.parser")
        for name in ("appointmentTimeFrom", "appointmentTimeTo"):
            for td in soup.select(f"td[name='{name}']"):
                value = norm(td.get_text(" ", strip=True))
                for token in re.findall(r"\d{1,2}:\d{2}", value):
                    if bad_time(token):
                        course_bad_times[token] += 1
                        courses_at_risk.add(url)
        for td in soup.select("td[name='appointmentDate'], td.rw-course-date"):
            bd = bad_date(norm(td.get_text(" ", strip=True)))
            if bd:
                course_bad_dates[bd] += 1
                courses_at_risk.add(url)
        if args.limit and scanned_courses >= args.limit:
            break

    print(f"Module pages scanned: {scanned_modules}")
    print(f"  out-of-range times: {sum(module_bad_times.values())} occurrences {dict(module_bad_times)}")
    print(f"  impossible dates:   {sum(module_bad_dates.values())} occurrences {dict(module_bad_dates)}")
    print(f"  -> module pages at risk of being dropped entirely: {len(modules_at_risk)}")
    print(f"Course pages scanned: {scanned_courses}")
    print(f"  out-of-range times: {sum(course_bad_times.values())} occurrences {dict(course_bad_times)}")
    print(f"  impossible dates:   {sum(course_bad_dates.values())} occurrences {dict(course_bad_dates)}")
    print(f"  -> course pages at risk of being dropped entirely: {len(courses_at_risk)}")
    for url in list(modules_at_risk)[:10]:
        print(f"    module at risk: ...{url[-50:]}")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "modules_scanned": scanned_modules,
            "module_bad_times": dict(module_bad_times),
            "module_bad_dates": dict(module_bad_dates),
            "modules_at_risk": len(modules_at_risk),
            "courses_scanned": scanned_courses,
            "course_bad_times": dict(course_bad_times),
            "course_bad_dates": dict(course_bad_dates),
            "courses_at_risk": len(courses_at_risk),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
