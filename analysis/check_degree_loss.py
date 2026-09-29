#!/usr/bin/env python3
"""Quantify how much path loss costs in degree links.

Since ``degree_parser`` derives degrees from ``module.path`` and only one path
group was persisted per module (see ``check_path_retention.py``), degrees that
exist only under the dropped paths are never created. This script runs the real
path extractor (``extract_for_paths``) on (a) all snapshot paths and (b) only the
paths actually stored, and reports the difference.

    python analysis/check_degree_loss.py --sample 15
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.parser.path_parser import extract_for_paths  # noqa: E402

SNAPSHOT = REPO / "snapshots" / "modules_latest.json"
DB = REPO / "database.db"


def split_name(name: str) -> tuple[str, str]:
    parts = name.split(None, 1)
    return (parts[0], parts[1].strip()) if len(parts) == 2 else (name, "")


def norm_paths(path) -> list[list[str]]:
    if not path:
        return []
    if any(isinstance(node, list) for node in path):
        return [[str(n) for n in p] for p in path if p]
    return [[str(n) for n in path]]


def degree_names(paths: list[list[str]]) -> set[str]:
    names = set()
    try:
        results = extract_for_paths(paths)
    except Exception:
        return names
    for result in results:
        if getattr(result, "kind", None) == "studiengang" and getattr(result, "name", None):
            names.add(result.name)
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", default=str(SNAPSHOT))
    parser.add_argument("--db", default=str(DB))
    parser.add_argument("--sample", type=int, default=15)
    parser.add_argument("--json", default=None)
    args = parser.parse_args()

    payload = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    snap_paths: dict[tuple[str, str], list[tuple]] = defaultdict(list)
    for entry in payload.get("modules", []):
        key = split_name(str(entry.get("name", "")))
        for group in norm_paths(entry.get("path")):
            if tuple(group) not in snap_paths[key]:
                snap_paths[key].append(tuple(group))

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    cur = con.cursor()
    db_paths: dict[tuple[str, str], list[list[str]]] = {}
    for number, name, path in cur.execute("SELECT number, name, path FROM module"):
        try:
            parsed = json.loads(path) if path else []
        except (TypeError, json.JSONDecodeError):
            parsed = []
        db_paths[(number or "", name or "")] = norm_paths(parsed)

    total_full = 0
    total_stored = 0
    affected = 0
    examples = []
    for key, groups in snap_paths.items():
        full = degree_names([list(g) for g in groups])
        stored_groups = db_paths.get(key, [])
        if not stored_groups:
            continue
        stored = degree_names(stored_groups)
        total_full += len(full)
        total_stored += len(stored)
        if len(full) > len(stored):
            affected += 1
            if len(examples) < args.sample:
                examples.append((key[0], key[1], sorted(full - stored)))

    print(f"Modules considered: {len(db_paths)}")
    print(f"Distinct degrees from ALL snapshot paths: {total_full}")
    print(f"Distinct degrees from STORED paths:       {total_stored}")
    print(f"Degrees lost to path loss:                {total_full - total_stored}")
    print(f"Modules whose stored paths yield fewer degrees: {affected}")
    print(f"\nSample modules with missing degrees (first {args.sample}):")
    for number, name, missing in examples:
        print(f"  {number} {name[:40]!r}: lost {missing}")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "degrees_from_all_paths": total_full,
            "degrees_from_stored_paths": total_stored,
            "degrees_lost": total_full - total_stored,
            "modules_affected": affected,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
