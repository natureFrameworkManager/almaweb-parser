#!/usr/bin/env python3
"""Audit the current module parser against the cached MODULEDETAILS pages.

Read-only. For every module page in ``.pagedata`` this compares what the parser
*stores* with what the raw HTML *contains*, to surface silent data loss on the
scalar "break-all" fields, the exams table and the "Leistungen" achievements
table. It does not import the DB and never writes to ``.pagedata``.

Checks
------
* duplicate module labels on one page (only one value can be stored per key)
* label rows whose value the parser reads as empty although the page carries text
* value truncation (parser value not contained in the independently extracted text)
* exam rows where ``parse_exam_datetime`` fails (date/time silently lost)
* exam / achievement row-count differences between raw DOM and parser output

    python analysis/compare_module_capture.py --limit 0
    python analysis/compare_module_capture.py --limit 0 --json analysis/out/module_capture.json
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

from src.parser.module_parser import (  # noqa: E402
    _LABEL_MAP,
    extract_achievements,
    extract_exams,
    extract_module_values,
    find_achievements_table,
    find_exam_section,
    parse_exam_datetime,
)
from src.parser.utils import set_warning_print, text_with_structure  # noqa: E402

set_warning_print(False)

_WS = re.compile(r"\s+")


def norm(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


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




def independent_labels(left) -> tuple[dict[str, list[str]], list[str]]:
    """label -> list of independently extracted value texts (in page order)."""
    values: dict[str, list[str]] = {}
    order: list[str] = []
    for label_tag in left.select(".font-semibold.break-all"):
        label = norm(label_tag.get_text(" ", strip=True)).rstrip(":")
        if not label:
            continue
        sibling = label_tag.find_next_sibling("div")
        value = text_with_structure(sibling) if sibling is not None else ""
        values.setdefault(label, []).append(value)
        order.append(label)
    return values, order


def raw_exam_rows(left):
    section = find_exam_section(left)
    if section is None:
        return None
    return section.select("table tbody tr")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(PAGEDATA))
    parser.add_argument("--limit", type=int, default=0, help="0 = all pages")
    parser.add_argument("--json", default=None)
    args = parser.parse_args()

    root = Path(args.root)
    pages = 0
    dup_labels = 0
    dup_samples: list[str] = []
    mismatches = 0
    mismatch_by_label: Counter = Counter()
    mismatch_samples: list[dict] = []
    exam_pages = 0
    exam_raw_rows = 0
    exam_parsed_rows = 0
    exam_count_mismatch = 0
    unparseable_exam_dates: Counter = Counter()
    ach_raw_rows = 0
    ach_parsed_rows = 0
    ach_count_mismatch = 0

    for html in iter_pages(root, "MODULEDETAILS"):
        pages += 1
        soup = BeautifulSoup(html.read_text(encoding="utf-8", errors="replace"), "html.parser")
        left = soup.select_one("#contentlayoutleft")
        if left is None:
            continue
        header = soup.find("h1")
        page_name = norm(header.get_text(" ", strip=True)) if header else html.name

        independent, order = independent_labels(left)
        parsed = extract_module_values(left)

        for label, values in independent.items():
            if len(values) > 1:
                dup_labels += 1
                if len(dup_samples) < 15:
                    dup_samples.append(f"{page_name}: {label!r} x{len(values)} -> {values[:3]}")

        for label, key in _LABEL_MAP.items():
            if label not in independent:
                continue
            raw = independent[label][-1]
            got = (parsed.get(key, "") or "").replace("\xa0", " ").strip()
            if raw and not got:
                mismatches += 1
                mismatch_by_label[label] += 1
                if len(mismatch_samples) < 25:
                    mismatch_samples.append({
                        "page": page_name, "label": label, "raw": raw[:160], "parsed": got,
                    })
            elif got and got not in raw and raw not in got:
                mismatches += 1
                mismatch_by_label[label] += 1
                if len(mismatch_samples) < 25:
                    mismatch_samples.append({
                        "page": page_name, "label": label, "raw": raw[:160], "parsed": got,
                    })

        # --- exams ---
        rows = raw_exam_rows(left)
        if rows is not None:
            exam_pages += 1
            exam_raw_rows += len(rows)
            for row in rows:
                date_cell = None
                for cell in row.find_all("td", recursive=False):
                    if "rw-detail-date" in (cell.get("class") or []):
                        date_cell = cell
                if date_cell is None:
                    continue
                value = norm(date_cell.get_text(" ", strip=True))
                value = re.sub(r"^Datum\s+", "", value)
                if value and value != "k.Terminbuchung" and parse_exam_datetime(value) == ("", "", ""):
                    unparseable_exam_dates[value] += 1
            section = find_exam_section(left)
            parsed_exams = extract_exams(section, page_name)
            exam_parsed_rows += len(parsed_exams)
            if len(parsed_exams) != len(rows):
                exam_count_mismatch += 1

        # --- achievements ---
        table = find_achievements_table(left)
        if table is not None:
            raw_rows = len(table.select("tbody tr"))
            ach_raw_rows += raw_rows
            parsed_ach = extract_achievements(table, page_name)
            ach_parsed_rows += len(parsed_ach)
            if len(parsed_ach) != raw_rows:
                ach_count_mismatch += 1

        if args.limit and pages >= args.limit:
            break

    print(f"Scanned {pages} module pages")
    print(f"\nDuplicate labels (only one value storable): {dup_labels}")
    for sample in dup_samples:
        print(f"  {sample}")
    print(f"\nScalar field mismatches (raw text present but parsed differently): {mismatches}")
    for label, count in mismatch_by_label.most_common():
        print(f"  {count:>6}  {label!r}")
    for sample in mismatch_samples[:20]:
        print(f"    {sample['page'][:50]!r} {sample['label']!r}: "
              f"raw={sample['raw']!r} parsed={sample['parsed']!r}")

    print(f"\nExam pages: {exam_pages}; raw rows={exam_raw_rows}; parsed rows={exam_parsed_rows}; "
          f"count mismatches={exam_count_mismatch}")
    print(f"Unparseable exam dates: {len(unparseable_exam_dates)} distinct, "
          f"{sum(unparseable_exam_dates.values())} occurrences")
    for value, count in unparseable_exam_dates.most_common(15):
        print(f"  {count:>5}  {value!r}")

    print(f"\nAchievement rows: raw={ach_raw_rows}; parsed={ach_parsed_rows}; "
          f"count mismatches={ach_count_mismatch}")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "pages": pages,
            "duplicate_labels": dup_labels,
            "dup_samples": dup_samples,
            "scalar_mismatches": mismatches,
            "mismatch_by_label": dict(mismatch_by_label),
            "mismatch_samples": mismatch_samples,
            "exam_pages": exam_pages,
            "exam_raw_rows": exam_raw_rows,
            "exam_parsed_rows": exam_parsed_rows,
            "exam_count_mismatch": exam_count_mismatch,
            "unparseable_exam_dates": dict(unparseable_exam_dates),
            "ach_raw_rows": ach_raw_rows,
            "ach_parsed_rows": ach_parsed_rows,
            "ach_count_mismatch": ach_count_mismatch,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
