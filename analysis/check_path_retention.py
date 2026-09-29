#!/usr/bin/env python3
"""Quantify navigation-path loss for modules offered in several semesters.

The spider emits one snapshot entry per ``(name, url)``; the same module in
different semesters is therefore several entries with several distinct paths.
In the DB all of them collapse onto ONE ``module`` row. ``_get_or_insert_module``
tries to accumulate the additional paths by mutating ``module.path`` **in place**
on a plain ``Column(JSON)`` -- SQLAlchemy does not track in-place JSON mutations,
so the extra paths are silently dropped.

Because ``degree_parser`` derives degrees from ``module.path``, this also loses
degree links. This script compares, per ``(number, name)``, the number of
distinct snapshot paths against the number of path groups actually stored.

    python analysis/check_path_retention.py
    python analysis/check_path_retention.py --json analysis/out_path_retention.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", default=str(SNAPSHOT))
    parser.add_argument("--db", default=str(DB))
    parser.add_argument("--sample", type=int, default=15)
    parser.add_argument("--json", default=None)
    args = parser.parse_args()

    payload = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    snap_paths: dict[tuple[str, str], set[tuple[str, ...]]] = defaultdict(set)
    snap_semesters: dict[tuple[str, str], set[str]] = defaultdict(set)
    for entry in payload.get("modules", []):
        number, name = split_name(str(entry.get("name", "")))
        for group in norm_paths(entry.get("path")):
            snap_paths[(number, name)].add(tuple(group))
        for group in norm_paths(entry.get("path")):
            for node in group:
                if node.startswith(("SoSe", "WiSe")):
                    snap_semesters[(number, name)].add(node)
    print(f"Snapshot distinct (number,name): {len(snap_paths)}")

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    cur = con.cursor()
    db_paths: dict[tuple[str, str], int] = {}
    db_module_id: dict[tuple[str, str], int] = {}
    for mid, number, name, path in cur.execute("SELECT id, number, name, path FROM module"):
        key = (number or "", name or "")
        db_module_id[key] = mid
        try:
            parsed = json.loads(path) if path else []
        except (TypeError, json.JSONDecodeError):
            parsed = []
        db_paths[key] = len(norm_paths(parsed))

    under: list[tuple[str, str, int, int, list[str]]] = []
    for key, paths in snap_paths.items():
        stored = db_paths.get(key, 0)
        if len(paths) > stored:
            under.append((key[0], key[1], len(paths), stored, sorted(snap_semesters[key])))
    under.sort(key=lambda x: -(x[2] - x[3]))

    total_snapshot_paths = sum(len(v) for v in snap_paths.values())
    total_stored_paths = sum(db_paths.get(k, 0) for k in snap_paths)
    print(f"Snapshot path groups for matched modules: {total_snapshot_paths}")
    print(f"Path groups stored in DB:                {total_stored_paths}")
    print(f"Path groups LOST: {total_snapshot_paths - total_stored_paths}")
    print(f"Modules storing fewer paths than found: {len(under)}")

    print(f"\nSample (first {args.sample}):")
    for number, name, found, stored, sems in under[: args.sample]:
        print(f"  {number} {name[:45]!r}  found={found} stored={stored}  semesters={sems}")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "snapshot_path_groups": total_snapshot_paths,
            "stored_path_groups": total_stored_paths,
            "lost_path_groups": total_snapshot_paths - total_stored_paths,
            "modules_understored": len(under),
            "sample": [
                {"number": n, "name": m, "found": f, "stored": s, "semesters": sem}
                for n, m, f, s, sem in under[:200]
            ],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
