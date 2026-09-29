#!/usr/bin/env python3
"""General detector for text-separator bugs (the #1/#2 failure modes).

For every labelled value container on every cached page it compares three
renderings of the same node:

* ``glue``  = ``get_text("", strip=True)``  -- what the parser gets when it omits
  the separator (words separated only by an element boundary are concatenated)
* ``space`` = ``get_text(" ", strip=True)`` -- boundaries become a space
* ``lines`` = ``get_text("\\n", strip=True)`` -- structural boundaries preserved

Verdicts
--------
* **GLUED**   -- the container has boundaries, and the parser's stored value equals
  the glue rendering (i.e. it dropped the separator).
* **FLATTENED** -- the container has multiple non-empty lines and the stored value
  is single-line (structure lost; words still separated).
* **OK**      -- stored value matches the space rendering.

Covers module, course, room, exam and event text. Read-only.

    python analysis/scan_text_separators.py --limit 0
    python analysis/scan_text_separators.py --limit 0 --json analysis/out/text_separators.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup, Tag

REPO = Path(__file__).resolve().parent.parent
PAGEDATA = REPO / ".pagedata"
sys.path.insert(0, str(REPO))

os.environ.setdefault("ALMAWEB_LOG_DIR", str(REPO / "analysis" / "out" / "warnings"))

from src.parser.course_parser import (  # noqa: E402
    _COURSE_LABEL_MAP,
    _cell_value,
    extract_course_values,
)
from src.parser.module_parser import (  # noqa: E402
    _LABEL_MAP,
    extract_module_values,
)
from src.parser.room_parser import (  # noqa: E402
    _BUILDING_LABEL_MAP,
    _ROOM_LABEL_MAP,
    _extract_room_values,
    _extract_section_values,
)
from src.parser.utils import set_warning_print, text_with_structure  # noqa: E402

set_warning_print(False)
_WS = re.compile(r"\s+")


def norm(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def lines_of(tag: Tag) -> list[str]:
    return [l.strip() for l in tag.get_text("\n", strip=True).split("\n") if l.strip()]


def verdict(stored: str, tag: Tag) -> str:
    stored = (stored or "").replace("\xa0", " ").strip()
    structured = text_with_structure(tag)
    if stored == structured:
        return "OK"
    glue = _WS.sub(" ", tag.get_text("", strip=True)).strip()
    space = _WS.sub(" ", tag.get_text(" ", strip=True)).strip()
    if norm(glue) == norm(stored) and norm(space) != norm(glue):
        return "GLUED"
    if norm(space) == norm(stored):
        return "FLATTENED" if len(lines_of(tag)) > 1 else "OK"
    return "MISMATCH"


def iter_pages(root: Path, substr: str):
    for sidecar in root.glob("*/*.json"):
        html = sidecar.with_suffix(".html")
        if not html.is_file():
            continue
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if substr in str(meta.get("url", "")):
            yield html



def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(PAGEDATA))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--json", default=None)
    args = parser.parse_args()
    root = Path(args.root)

    results: dict[str, Counter] = {}
    samples: dict[str, list[str]] = {}

    def record(page_kind: str, field: str, v: str, stored: str, tag: Tag, page: str) -> None:
        key = f"{page_kind}:{field}"
        results.setdefault(key, Counter())[v] += 1
        if v != "OK":
            samples.setdefault(key, [])
            if len(samples[key]) < 5:
                samples[key].append(f"{page} {field}={stored[:90]!r}")

    n = 0
    for html in iter_pages(root, "MODULEDETAILS"):
        n += 1
        soup = BeautifulSoup(html.read_text(encoding="utf-8", errors="replace"), "html.parser")
        left = soup.select_one("#contentlayoutleft")
        if left is None:
            continue
        parsed = extract_module_values(left)
        tags: dict[str, Tag] = {}
        for label_tag in left.select(".font-semibold.break-all"):
            label = norm(label_tag.get_text(" ", strip=True)).rstrip(":")
            key = _LABEL_MAP.get(label)
            sib = label_tag.find_next_sibling("div")
            if key and sib is not None and key not in tags:
                tags[key] = sib
        for key, tag in tags.items():
            stored = parsed.get(key, "")
            if not isinstance(stored, str):
                continue
            record("module", key, verdict(stored, tag), stored, tag, html.name)
        if args.limit and n >= args.limit:
            break
    print(f"module pages scanned: {n}")

    n = 0
    for html in iter_pages(root, "COURSEDETAILS"):
        n += 1
        soup = BeautifulSoup(html.read_text(encoding="utf-8", errors="replace"), "html.parser")
        left = soup.select_one("#contentlayoutleft")
        if left is None:
            continue
        parsed = extract_course_values(left)
        for row in left.select(".tbdata"):
            label_tag = row.find("b", recursive=False)
            if label_tag is None:
                continue
            label = norm(label_tag.get_text(" ", strip=True)).rstrip(":")
            entry = _COURSE_LABEL_MAP.get(label)
            if entry is None:
                continue
            key, _tag_name = entry
            container = label_tag.find_next_sibling() or row
            record("course", key, verdict(parsed.get(key, ""), container), parsed.get(key, ""),
                   container, html.name)
        if args.limit and n >= args.limit:
            break

    n = 0
    for html in iter_pages(root, "PRGNAME=ACTION"):
        n += 1
        soup = BeautifulSoup(html.read_text(encoding="utf-8", errors="replace"), "html.parser")
        dl = soup.find("dl")
        if not isinstance(dl, Tag):
            continue
        room_values = _extract_room_values(dl)
        building_values = _extract_section_values(dl, "Gebäude", _BUILDING_LABEL_MAP)
        for row in dl.find_all("div", recursive=False):
            dt, dd = row.find("dt", recursive=False), row.find("dd", recursive=False)
            if dt is None or dd is None:
                continue
            key = _ROOM_LABEL_MAP.get(norm(dt.get_text(" ", strip=True)))
            if key:
                record("room", key, verdict(room_values.get(key, ""), dd),
                       room_values.get(key, ""), dd, html.name)
        section = None
        for div in dl.find_all("div", class_="py-3", recursive=False):
            heading = div.find("div", class_="font-bold")
            if heading and "Gebäude" in heading.get_text(" ", strip=True):
                section = div
        if section is not None:
            for row in section.find_all("div", class_="sm:grid"):
                dt, dd = row.find("dt"), row.find("dd")
                if dt is None or dd is None:
                    continue
                key = _BUILDING_LABEL_MAP.get(norm(dt.get_text(" ", strip=True)))
                if key:
                    record("room_building", key, verdict(building_values.get(key, ""), dd),
                           building_values.get(key, ""), dd, html.name)
        if args.limit and n >= args.limit:
            break
    print(f"room pages scanned: {n}")

    n = 0
    event_glue = 0
    for html in iter_pages(root, "COURSEDETAILS"):
        n += 1
        soup = BeautifulSoup(html.read_text(encoding="utf-8", errors="replace"), "html.parser")
        for td in soup.select('td[name="appointmentInstructors"], td.rw-course-room'):
            if _cell_value(td) != _WS.sub(" ", td.get_text(" ", strip=True)).strip():
                event_glue += 1
        if args.limit and n >= args.limit:
            break
    print(f"event cells with separator mismatch: {event_glue} (of {n} pages)")

    print("\nNon-OK verdicts per field:")
    for key in sorted(results):
        counts = {k: v for k, v in results[key].items() if k != "OK"}
        if counts:
            print(f"  {key:<45} {counts}")
    print("\nNon-OK samples:")
    for key, sample in sorted(samples.items()):
        for line in sample:
            print(f"  {key}: {line}")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "verdicts": {k: dict(v) for k, v in results.items()},
            "samples": samples,
            "event_cell_separator_mismatch": event_glue,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

    print(f"course pages scanned: {n}")
