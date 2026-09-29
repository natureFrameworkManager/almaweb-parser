#!/usr/bin/env python3
"""Scan cached MODULEDETAILS / COURSEDETAILS pages for fields the parser may drop.

Read-only. Reports labels that appear on real pages but are not captured by the
current label maps (data the parser silently discards, e.g. a language field),
plus the exam/achievement table structure.

    python analysis/scan_fields.py --kind module --limit 400
    python analysis/scan_fields.py --kind course --limit 400
    python analysis/scan_fields.py --kind exam --limit 400
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

from src.parser.module_parser import _LABEL_MAP  # noqa: E402
from src.parser.course_parser import _COURSE_LABEL_MAP  # noqa: E402

_WS = re.compile(r"\s+")


def prgname_of(url: str) -> str:
    query = parse_qs(urlsplit(url).query)
    return (query.get("PRGNAME") or ["<none>"])[0]


def iter_pages(kind: str, root: Path):
    for sidecar in root.glob("*/*.json"):
        html = sidecar.with_suffix(".html")
        if not html.is_file():
            continue
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if prgname_of(str(meta.get("url", ""))) != kind:
            continue
        yield sidecar, html


def norm(text: str) -> str:
    return _WS.sub(" ", text.replace("\xa0", " ")).strip()


def scan_module(path: Path, label_counts: Counter, known: dict, unmapped: dict) -> None:
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    left = soup.select_one("#contentlayoutleft")
    if left is None:
        return
    for tag in left.select(".font-semibold.break-all"):
        label = norm(tag.get_text(" ", strip=True)).rstrip(":")
        label_counts[label] += 1
        if label not in known:
            sibling = tag.find_next_sibling("div")
            if label not in unmapped or unmapped[label] is None:
                unmapped[label] = norm(sibling.get_text(" ", strip=True))[:120] if sibling else None


def scan_course(path: Path, label_counts: Counter, known: dict, unmapped: dict) -> None:
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    left = soup.select_one("#contentlayoutleft")
    if left is None:
        return
    for row in left.select(".tbdata"):
        label_tag = row.find("b", recursive=False)
        if label_tag is None:
            continue
        label = norm(label_tag.get_text(" ", strip=True)).rstrip(":")
        label_counts[label] += 1
        if label not in known:
            if label not in unmapped or unmapped[label] is None:
                sibling = row.find("div")
                unmapped[label] = norm(sibling.get_text(" ", strip=True))[:120] if sibling else None


def scan_exam(path: Path, header_counts: Counter, class_counts: Counter, section_counts: Counter) -> None:
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    for table in soup.find_all("table"):
        summary = norm(str(table.get("summary", "")))
        header = norm(" ".join(th.get_text(" ", strip=True) for th in table.find_all("th")))
        if any(k in (summary + header) for k in ("Leistung", "Modulabschluss")):
            section_counts[(summary, header[:200])] += 1
            for td in table.find_all("td"):
                for cls in td.get("class") or []:
                    class_counts[cls] += 1
    for tag in soup.find_all(string=lambda s: s and ("Modulabschlussprüfungen" in s or "Leistungen" in s)):
        header_counts[norm(str(tag))] += 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=["module", "course", "exam"], required=True)
    parser.add_argument("--root", default=str(PAGEDATA))
    parser.add_argument("--limit", type=int, default=300)
    args = parser.parse_args()

    root = Path(args.root)
    label_counts: Counter = Counter()
    unmapped: dict[str, str | None] = {}
    header_counts: Counter = Counter()
    class_counts: Counter = Counter()
    section_counts: Counter = Counter()

    page_kind = "MODULEDETAILS" if args.kind in {"module", "exam"} else "COURSEDETAILS"
    n = 0
    for _sidecar, html in iter_pages(page_kind, root):
        n += 1
        if args.kind == "module":
            scan_module(html, label_counts, set(_LABEL_MAP), unmapped)
        elif args.kind == "course":
            scan_course(html, label_counts, {k for k, _ in _COURSE_LABEL_MAP.items()}, unmapped)
        else:
            scan_exam(html, header_counts, class_counts, section_counts)
        if args.limit and n >= args.limit:
            break

    print(f"Scanned {n} {args.kind} pages")
    if args.kind in {"module", "course"}:
        known = _LABEL_MAP if args.kind == "module" else {k for k, _ in _COURSE_LABEL_MAP.items()}
        print(f"\nLabels found ({len(label_counts)} distinct):")
        for label, count in label_counts.most_common():
            print(f"  {count:>6}  {'MAPPED  ' if label in known else 'UNMAPPED'}  {label!r}")
        print(f"\nUnmapped labels ({len(unmapped)}):")
        for label, sample in sorted(unmapped.items()):
            print(f"  {label!r}  example_value={sample!r}")
    else:
        print("\nSection headings:")
        for k, v in header_counts.most_common(20):
            print(f"  {v:>6}  {k!r}")
        print("\nTables (summary | header):")
        for (summary, header), v in section_counts.most_common(20):
            print(f"  {v:>6}  summary={summary!r}\n          th={header!r}")
        print("\nTD classes in exam/achievement tables:")
        for k, v in class_counts.most_common(40):
            print(f"  {v:>7}  {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
