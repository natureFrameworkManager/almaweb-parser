#!/usr/bin/env python3
"""Quantify prerequisite (Teilnahmevoraussetzungen) corruption.

The value of the ``Teilnahmevoraussetzungen`` field is a list of requirements,
one per ``<br>``-separated line, each shaped ``<context>: <requirement>``.
``extract_module_values`` collapses *all* whitespace (including newlines) to a
single space before calling ``parse_prerequisites``, so ``parse_prerequisites``
only ever sees ONE "line" and splits it at the first colon. Every following
requirement's key is swallowed into the previous requirement's value.

This script compares the raw line structure with the stored prerequisite dict
and reports pages where entries are merged/lost.

    python analysis/scan_prerequisites.py --limit 0
    python analysis/scan_prerequisites.py --limit 0 --json analysis/out/prerequisites.json
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

from src.parser.module_parser import parse_prerequisites, _split_prerequisite  # noqa: E402
from src.parser.utils import set_warning_print, text_with_structure  # noqa: E402

set_warning_print(False)

_WS = re.compile(r"\s+")


def iter_modules(root: Path):
    for sidecar in root.glob("*/*.json"):
        html = sidecar.with_suffix(".html")
        if not html.is_file():
            continue
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if "PRGNAME=MODULEDETAILS" in str(meta.get("url", "")):
            yield html


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(PAGEDATA))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--json", default=None)
    args = parser.parse_args()

    pages = 0
    pages_with_prereq = 0
    pages_multi_line = 0
    pages_with_colon_lines = 0
    keys_lost = 0
    merged_value = 0
    samples: list[dict] = []

    for html in iter_modules(Path(args.root)):
        pages += 1
        soup = BeautifulSoup(html.read_text(encoding="utf-8", errors="replace"), "html.parser")
        left = soup.select_one("#contentlayoutleft")
        if left is None:
            continue
        target = None
        for label_tag in left.select(".font-semibold.break-all"):
            label = _WS.sub(" ", label_tag.get_text(" ", strip=True)).rstrip(":")
            if label == "Teilnahmevoraussetzungen":
                target = label_tag.find_next_sibling("div")
                break
        if target is None:
            continue
        pages_with_prereq += 1
        # The raw lines as the page author wrote them ("<br>" -> newline).
        raw_lines = [norm for norm in (l.strip() for l in target.get_text("\n", strip=True).split("\n")) if norm]
        # What the parser now hands to parse_prerequisites (block-aware, newlines kept).
        structured = text_with_structure(target)
        prereq = parse_prerequisites(structured)

        colon_lines = [l for l in raw_lines if ":" in l]
        if len(raw_lines) > 1:
            pages_multi_line += 1
        if len(colon_lines) > 1:
            pages_with_colon_lines += 1
        expected_keys = []
        for line in raw_lines:
            split = _split_prerequisite(line)
            if split is not None:
                expected_keys.append(_WS.sub(" ", split[0]).strip())
        missing = [k for k in expected_keys if k not in prereq]
        if missing:
            keys_lost += len(missing)
            if len(samples) < 25:
                samples.append({
                    "page": html.name,
                    "raw_lines": raw_lines[:4],
                    "stored_keys": list(prereq.keys()),
                    "lost_keys": missing[:3],
                })
        # swallowed keys: a stored value still embeds the next "<key>:" segment
        for value in prereq.values():
            if any(key and f"{key}:" in value for key in expected_keys):
                merged_value += 1
                break

        if args.limit and pages >= args.limit:
            break

    print(f"Scanned {pages} module pages; with Teilnahmevoraussetzungen={pages_with_prereq}")
    print(f"Pages whose value spans multiple <br> lines: {pages_multi_line}")
    print(f"Pages with >1 'key: value' line: {pages_with_colon_lines}")
    print(f"Requirement keys lost to the collapse: {keys_lost}")
    print(f"Pages whose stored value swallowed a following key: {merged_value}")
    for sample in samples[:12]:
        print(f"\n  {sample['page']}")
        for line in sample["raw_lines"]:
            print(f"    line   : {line[:110]}")
        print(f"    stored : {sample['stored_keys']} (lost {sample['lost_keys']})")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "pages": pages,
            "pages_with_prereq": pages_with_prereq,
            "pages_multi_line": pages_multi_line,
            "pages_with_colon_lines": pages_with_colon_lines,
            "keys_lost": keys_lost,
            "merged_value": merged_value,
            "samples": samples,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
