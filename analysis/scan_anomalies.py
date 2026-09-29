#!/usr/bin/env python3
"""Scan cached pages for values the parser silently drops or mishandles.

Read-only. Three checks over the real page store:

1. **Exam dates** -- exam ``rw-detail-date`` values that ``parse_exam_datetime``
   cannot parse. The function returns ``("","","")`` without logging, so such an
   exam silently loses its date and times.
2. **Multi-room sessions** -- Termine rows whose room cell holds more than one
   room value; ``extract_events`` only keeps the first room.
3. **Module headers** -- ``h1`` texts that do not split into ``<number> <name>``
   (``parseModule`` would raise and drop the whole module).

    python analysis/scan_anomalies.py --limit 1500
    python analysis/scan_anomalies.py --limit 0
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

REPO = Path(__file__).resolve().parent.parent
PAGEDATA = REPO / ".pagedata"
sys.path.insert(0, str(REPO))

from src.parser.course_parser import _cell_values  # noqa: E402
from src.parser.module_parser import parse_exam_datetime  # noqa: E402

_WS = re.compile(r"\s+")


def prgname(url: str) -> str:
    return (parse_qs(urlsplit(url).query).get("PRGNAME") or ["<none>"])[0]


def norm(text: str) -> str:
    return _WS.sub(" ", text.replace("\xa0", " ")).strip()


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
            yield html


def check_exams(root: Path, limit: int) -> Counter:
    bad: Counter = Counter()
    n = 0
    for html in iter_pages(root, "MODULEDETAILS"):
        n += 1
        soup = BeautifulSoup(html.read_text(encoding="utf-8", errors="replace"), "html.parser")
        for td in soup.select("td.rw-detail-date"):
            value = norm(td.get_text(" ", strip=True))
            # drop the mobile label ("Datum") if it survived
            value = re.sub(r"^Datum\s+", "", value)
            if not value or value == "k.Terminbuchung":
                continue
            if parse_exam_datetime(value) == ("", "", ""):
                bad[value] += 1
        if limit and n >= limit:
            break
    print(f"Exam-date check: scanned {n} module pages")
    return bad


def check_multi_room(root: Path, limit: int) -> tuple[int, int, Counter]:
    pages = 0
    rows = 0
    bad: Counter = Counter()
    for html in iter_pages(root, "COURSEDETAILS"):
        pages += 1
        soup = BeautifulSoup(html.read_text(encoding="utf-8", errors="replace"), "html.parser")
        for cell in soup.select("td.rw-course-room, td[name='appointmentRooms']"):
            values = [v for v in _cell_values(cell) if v]
            if len(values) > 1:
                rows += 1
                bad[" | ".join(values)] += 1
        if limit and pages >= limit:
            break
    print(f"Multi-room check: scanned {pages} course pages")
    return pages, rows, bad


def check_headers(root: Path, limit: int) -> tuple[int, list[str]]:
    n = 0
    bad: list[str] = []
    for html in iter_pages(root, "MODULEDETAILS"):
        n += 1
        soup = BeautifulSoup(html.read_text(encoding="utf-8", errors="replace"), "html.parser")
        header = soup.find("h1")
        text = norm(header.get_text(" ", strip=True)) if header else ""
        if len(text.split(None, 1)) < 2:
            bad.append(text)
        if limit and n >= limit:
            break
    print(f"Header check: scanned {n} module pages")
    return n, bad


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(PAGEDATA))
    parser.add_argument("--limit", type=int, default=1500)
    args = parser.parse_args()
    root = Path(args.root)

    bad_dates = check_exams(root, args.limit)
    print(f"  unparseable exam dates: {len(bad_dates)} distinct, {sum(bad_dates.values())} occurrences")
    for value, count in bad_dates.most_common(20):
        print(f"    {count:>5}  {value!r}")

    _pages, multi, samples = check_multi_room(root, args.limit)
    print(f"  rows with multiple rooms (only first kept): {multi}")
    for value, count in samples.most_common(10):
        print(f"    {count:>5}  {value!r}")

    _n, bad_headers = check_headers(root, args.limit)
    print(f"  module headers that do not split into number + name: {len(bad_headers)}")
    for value in bad_headers[:10]:
        print(f"    {value!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
