#!/usr/bin/env python3
"""Definitive offline coverage check: snapshot (found) -> DB (stored).

For every module the crawl found (``snapshots/modules_latest.json``), determine
the semester from its navigation path and verify in ``database.db`` that

* a module row with the same ``(number, name)`` exists, and
* it is linked to that semester.

This is what detects "a module was found in semester X but never linked to X".
Read-only: opens the DB read-only and never writes to ``.pagedata``.

    python analysis/check_coverage.py
    python analysis/check_coverage.py --sample 30 --json analysis/out_coverage.json
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SNAPSHOT = REPO / "snapshots" / "modules_latest.json"
DB = REPO / "database.db"

_SEM_RE = re.compile(r"^(SoSe|WiSe)\s*\d", re.I)


def split_snapshot_name(name: str) -> tuple[str, str]:
    """Snapshot names are the anchor text ``"<number> <name>"``."""
    parts = name.split(None, 1)
    if len(parts) == 2:
        return parts[0], parts[1].strip()
    return name, ""


def path_groups(path) -> list[list[str]]:
    if not path:
        return []
    if any(isinstance(node, list) for node in path):
        return [[str(n) for n in p] for p in path if p]
    return [[str(n) for n in path]]


def semesters_of(path) -> list[str]:
    found: list[str] = []
    for group in path_groups(path):
        for node in group:
            if _SEM_RE.match(node) and node not in found:
                found.append(node)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", default=str(SNAPSHOT))
    parser.add_argument("--db", default=str(DB))
    parser.add_argument("--sample", type=int, default=20)
    parser.add_argument("--json", default=None)
    args = parser.parse_args()

    payload = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    modules = payload.get("modules", [])
    print(f"Snapshot: {args.snapshot}  ({len(modules)} module entries)")

    uri = f"file:{args.db}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    cur = con.cursor()

    # (number, name) -> module id
    module_ids: dict[tuple[str, str], int] = {}
    for mid, number, name in cur.execute("SELECT id, number, name FROM module"):
        module_ids[(number or "", name or "")] = mid
    # module id -> set of semester names
    links: dict[int, set[str]] = defaultdict(set)
    for mid, sem in cur.execute(
        "SELECT l.module_id, s.name FROM modulesemesterlink l JOIN semester s ON s.id = l.semester_id"
    ):
        links[mid].add(sem)

    missing_module: list[tuple[str, str, str]] = []
    missing_link: list[tuple[str, str, str]] = []
    no_semester: list[str] = []
    checked = 0
    matched = 0

    for entry in modules:
        raw_name = str(entry.get("name", ""))
        number, name = split_snapshot_name(raw_name)
        sems = semesters_of(entry.get("path"))
        if not sems:
            no_semester.append(raw_name)
            continue
        checked += 1
        mid = module_ids.get((number, name))
        if mid is None:
            missing_module.append((number, name, ", ".join(sems)))
            continue
        matched += 1
        for sem in sems:
            if sem not in links.get(mid, set()):
                missing_link.append((number, name, sem))

    print(f"\nChecked entries with a semester: {checked}")
    print(f"Matched module in DB: {matched}")
    print(f"Entries WITHOUT any parsable semester: {len(no_semester)}")
    print(f"Missing module row in DB: {len(missing_module)}")
    print(f"Missing module<->semester link: {len(missing_link)}")

    print(f"\nSample missing module rows (first {args.sample}):")
    for number, name, sems in missing_module[: args.sample]:
        print(f"  {number}  {name}   [{sems}]")
    print(f"\nSample missing semester links (first {args.sample}):")
    for number, name, sem in missing_link[: args.sample]:
        print(f"  {number}  {name}   missing semester={sem}")
    if no_semester:
        print(f"\nSample entries without semester (first {args.sample}):")
        for name in no_semester[: args.sample]:
            print(f"  {name}")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "snapshot_entries": len(modules),
            "checked": checked,
            "matched": matched,
            "no_semester": no_semester,
            "missing_module": [
                {"number": n, "name": m, "semesters": s} for n, m, s in missing_module
            ],
            "missing_link": [
                {"number": n, "name": m, "semester": s} for n, m, s in missing_link
            ],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
