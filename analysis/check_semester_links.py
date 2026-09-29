#!/usr/bin/env python3
"""Check module<->semester linking against the crawl snapshot (read-only).

The spider deduplicates modules by ``(name, url)``; a module offered in several
semesters appears as several entries (one per semester URL) which the DB collapses
onto one ``module`` row. ``insert_module_graph`` links that row to every semester
found in the entry's path, so the question this script answers is: **does each
stored module carry a link for every semester its snapshot entries mention?**

Matching is by ``(number, name)`` -- the snapshot anchor text is "<number> <name>",
while the DB stores only ``name``. (Earlier versions matched on the full anchor
text and therefore reported every multi-semester module as under-linked.)

    python analysis/check_semester_links.py
    python analysis/check_semester_links.py --json analysis/out2/semester_links.json
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


def split_name(name: str) -> tuple[str, str]:
    """Snapshot anchor text is ``"<number> <name>"``; the DB stores only ``name``."""
    parts = name.split(None, 1)
    return (parts[0], parts[1].strip()) if len(parts) == 2 else (name, "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", default=str(SNAPSHOT))
    parser.add_argument("--db", default=str(DB))
    parser.add_argument("--sample", type=int, default=15)
    parser.add_argument("--json", default=None)
    args = parser.parse_args()

    payload = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    modules = payload.get("modules", [])
    print(f"Snapshot: {args.snapshot}  ({len(modules)} module entries)")

    multi_path = 0
    multi_semester: list[tuple[str, list[str]]] = []
    unparsable = 0
    sem_counter: Counter[str] = Counter()
    by_name: dict[tuple[str, str], set[str]] = defaultdict(set)
    for entry in modules:
        groups = path_groups(entry.get("path"))
        sems = semesters_of(entry.get("path"))
        if len(groups) > 1:
            multi_path += 1
        if len(sems) > 1:
            multi_semester.append((str(entry.get("name", "")), sems))
        for s in sems:
            sem_counter[s] += 1
        if not sems:
            unparsable += 1
        by_name[split_name(str(entry.get("name", "")))].update(sems)

    print(f"\nEntries with >1 path group: {multi_path}")
    print(f"Entries with >1 distinct semester across paths: {len(multi_semester)}")
    print(f"Entries with no parsable semester node: {unparsable}")
    print("\nSnapshot semester histogram (entries per sem):")
    for s, c in sem_counter.most_common():
        print(f"  {c:>6}  {s}")
    print(f"\nSample multi-semester entries (first {args.sample}):")
    for name, sems in multi_semester[: args.sample]:
        print(f"  {name!r}  ->  {sems}")

    con = sqlite3.connect(args.db)
    cur = con.cursor()
    rows = cur.execute(
        "SELECT m.number, m.name, s.name FROM module m "
        "JOIN modulesemesterlink l ON l.module_id = m.id "
        "JOIN semester s ON s.id = l.semester_id"
    ).fetchall()
    db_by_name: dict[tuple[str, str], set[str]] = defaultdict(set)
    db_sem_counter: Counter[str] = Counter()
    for number, name, sem in rows:
        db_by_name[(number or "", name or "")].add(sem)
        db_sem_counter[sem] += 1

    print(f"\nDB semester histogram ({len(db_sem_counter)} distinct):")
    for s, c in db_sem_counter.most_common():
        print(f"  {c:>6}  {s}")

    only_snap = sorted(set(sem_counter) - set(db_sem_counter))
    only_db = sorted(set(db_sem_counter) - set(sem_counter))
    print(f"\nDB distinct semesters={len(db_sem_counter)}  snapshot distinct={len(sem_counter)}")
    if only_snap:
        print(f"  Semesters in snapshot but NOT in DB: {only_snap}")
    if only_db:
        print(f"  Semesters in DB but not snapshot: {only_db}")

    underlinked = []
    for name, sems in by_name.items():
        db_sems = db_by_name.get(name, set())
        if len(sems) > 1 and len(db_sems) < len(sems):
            underlinked.append((name, sorted(sems), sorted(db_sems)))
    print(f"\nEntries with >1 snapshot semester but fewer DB semester links: {len(underlinked)}")
    for (number, name), snap_sems, db_sems in underlinked[: args.sample]:
        print(f"  {number} {name!r}\n      snapshot={snap_sems}\n      db      ={db_sems}")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "snapshot_entries": len(modules),
            "multi_path_entries": multi_path,
            "multi_semester_entries": len(multi_semester),
            "no_semester_entries": unparsable,
            "snapshot_semesters": dict(sem_counter),
            "db_semesters": dict(db_sem_counter),
            "only_in_snapshot": only_snap,
            "only_in_db": only_db,
            "underlinked": [{"number": n[0], "name": n[1], "snapshot": s, "db": d} for n, s, d in underlinked],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
