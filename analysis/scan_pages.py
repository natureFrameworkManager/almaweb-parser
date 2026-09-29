#!/usr/bin/env python3
"""Offline reconnaissance of the on-disk page store (``.pagedata``).

Read-only. Classifies every cached page by its CampusNet ``PRGNAME`` (from the
``.json`` sidecar) so we know exactly which page kinds the parser had to work
with, and prints the counts. Use this to reason about coverage: how many module
pages, course pages, room pages, navigation pages, etc. exist locally.

    python analysis/scan_pages.py
    python analysis/scan_pages.py --prgname MODULEDETAILS --list 5
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

REPO = Path(__file__).resolve().parent.parent
PAGEDATA = REPO / ".pagedata"


def iter_sidecars(root: Path):
    for sidecar in root.glob("*/*.json"):
        html = sidecar.with_suffix(".html")
        if not html.is_file():
            continue
        yield sidecar, html


def prgname_of(url: str) -> str:
    query = parse_qs(urlsplit(url).query)
    return (query.get("PRGNAME") or ["<none>"])[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(PAGEDATA), help="Page-store root.")
    parser.add_argument("--prgname", default=None, help="Only report this PRGNAME.")
    parser.add_argument("--list", type=int, default=0, help="List N sample URLs.")
    args = parser.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        print(f"page store not found: {root}", file=sys.stderr)
        return 1

    counts: Counter[str] = Counter()
    samples: dict[str, list[str]] = {}
    total = 0
    for sidecar, _html in iter_sidecars(root):
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        total += 1
        name = prgname_of(str(meta.get("url", "")))
        counts[name] += 1
        if args.list:
            samples.setdefault(name, [])
            if len(samples[name]) < args.list:
                samples[name].append(str(meta.get("url", "")))

    print(f"Page store: {root}  ({total} cached pages)")
    for name, count in counts.most_common():
        if args.prgname and name != args.prgname:
            continue
        print(f"  {count:>6}  {name}")
        for url in samples.get(name, []):
            print(f"          {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
