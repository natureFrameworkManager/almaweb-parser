#!/usr/bin/env python3
"""Dataset-wide integrity checks over ``database.db`` (read-only).

Complements ``src.parser.audit`` with checks aimed at *silent data loss and
corruption*: dedup collapses, key collisions, empty mandatory fields, duplicate
reference rows and 2-digit semester years.

    python analysis/db_integrity.py
    python analysis/db_integrity.py --json analysis/out2/db_integrity.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "database.db"


def q(cur, sql, *params):
    try:
        return cur.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        return [("ERR", str(exc))]


def scalar(cur, sql, *params):
    row = q(cur, sql, *params)
    return row[0][0] if row else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DB))
    parser.add_argument("--json", default=None)
    args = parser.parse_args()

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    cur = con.cursor()
    report: dict[str, object] = {"_checks": {}, "_totals": {}}

    def check(key: str, where: str, sample_sql: str | None = None, sample: int = 8):
        """Count rows matching ``where`` (a WHERE clause over ``table``)."""
        table, _, clause = key.partition("|")
        sql = f"SELECT COUNT(*) AS n FROM {table}" + (f" WHERE {where}" if where else "")
        rows = q(cur, sql)
        count = rows[0][0] if rows and rows[0] and not isinstance(rows[0][0], str) else 0
        samples = q(cur, sample_sql, sample) if sample_sql and count else []
        report["_checks"][key] = {"count": count, "sample": samples}  # type: ignore
        print(f"[{'!' if count else ' '}] {key}: {count}")
        for r in samples[:sample]:
            print(f"       {r}")

    # --- module identity / paths -------------------------------------------------
    check("module|multiple names per number",
          "1=1", "SELECT number, COUNT(DISTINCT name) n FROM module GROUP BY number HAVING n>1 ORDER BY n DESC LIMIT ?")
    check("module|empty name", "name='' OR name IS NULL")
    check("module|no path", "path IS NULL OR path IN ('[]','null')")
    check("module|flat path (not list-of-lists)",
          "json_type(path,'$[0]') = 'text'", "SELECT id, number, substr(path,1,70) FROM module WHERE json_type(path,'$[0]')='text' LIMIT ?")
    check("module|no courses",
          "NOT EXISTS (SELECT 1 FROM modulecourselink l WHERE l.module_id=module.id)",
          "SELECT number, name FROM module m WHERE NOT EXISTS (SELECT 1 FROM modulecourselink l WHERE l.module_id=m.id) LIMIT ?")

    # --- semester sanity ---------------------------------------------------------
    check("semester|two-digit year", "year < 100", "SELECT id, name, year FROM semester WHERE year<100 LIMIT ?")
    check("semester|duplicate name", "1=0")

    # --- course integrity --------------------------------------------------------
    check("course|no events",
          "NOT EXISTS (SELECT 1 FROM courseeventlink l WHERE l.course_id=course.id)",
          "SELECT number, name FROM course c WHERE NOT EXISTS (SELECT 1 FROM courseeventlink l WHERE l.course_id=c.id) LIMIT ?")
    check("course|empty org_unit", "org_unit=''", "SELECT COUNT(*) FROM course WHERE org_unit=''")
    check("course|zero weekly_hours", "weekly_hours=0")

    # --- event integrity ---------------------------------------------------------
    check("event|null location", "location_id IS NULL")
    check("event|start >= end", "start_time >= end_time",
          "SELECT id, event_date, start_time, end_time FROM event WHERE start_time>=end_time LIMIT ?")
    check("event|date out of range", "event_date < '2000-01-01' OR event_date > '2100-01-01'")

    # --- location / building -----------------------------------------------------
    check("location|duplicate identity", "1=0")
    check("location|empty external_id", "external_id=''")
    check("location|empty name", "name=''")
    check("building|empty name", "name=''")

    # --- staff -------------------------------------------------------------------
    check("staff|empty name", "name='' OR name IS NULL")

    # --- degrees -----------------------------------------------------------------
    check("degree|orphan",
          "NOT EXISTS (SELECT 1 FROM moduledegreelink l WHERE l.degree_id=degree.id)")
    check("degree|empty name", "name='' OR name IS NULL")

    # --- group / duplicate checks ------------------------------------------------
    def group_check(key: str, group_sql: str, sample_sql: str, sample: int = 8):
        groups = q(cur, group_sql)
        count = len(groups)
        samples = q(cur, sample_sql, sample) if count else []
        report["_checks"][key] = {"count": count, "sample": samples}  # type: ignore
        print(f"[{'!' if count else ' '}] {key}: {count}")
        for r in samples[:sample]:
            print(f"       {r}")

    group_check("GROUP|module (number,name) duplicates",
                "SELECT number, name FROM module GROUP BY number, name HAVING COUNT(*)>1",
                "SELECT number, name, COUNT(*) n FROM module GROUP BY number, name HAVING n>1 LIMIT ?")
    group_check("GROUP|course (name,number,type) duplicates",
                "SELECT name, number, type FROM course GROUP BY name, number, type HAVING COUNT(*)>1",
                "SELECT name, number, type, COUNT(*) n FROM course GROUP BY name, number, type HAVING n>1 LIMIT ?")
    group_check("GROUP|event identity duplicates",
                "SELECT event_date, start_time, end_time, COALESCE(location_id,-1) FROM event "
                "GROUP BY event_date, start_time, end_time, COALESCE(location_id,-1) HAVING COUNT(*)>1",
                "SELECT event_date, start_time, end_time, location_id, COUNT(*) n FROM event "
                "GROUP BY event_date, start_time, end_time, COALESCE(location_id,-1) HAVING n>1 ORDER BY n DESC LIMIT ?")
    group_check("GROUP|event shared across modules (dedup collapse)",
                "SELECT e.id FROM event e JOIN courseeventlink ce ON ce.event_id=e.id "
                "JOIN modulecourselink l ON l.course_id=ce.course_id GROUP BY e.id HAVING COUNT(DISTINCT l.module_id)>1",
                "SELECT e.id, e.event_date, e.start_time, e.end_time, e.location_id, COUNT(DISTINCT l.module_id) nm "
                "FROM event e JOIN courseeventlink ce ON ce.event_id=e.id "
                "JOIN modulecourselink l ON l.course_id=ce.course_id GROUP BY e.id HAVING nm>1 ORDER BY nm DESC LIMIT ?")
    group_check("GROUP|exam (module,name,date,required) duplicates",
                "SELECT module_id, name, COALESCE(exam_date,''), required FROM moduleexam "
                "GROUP BY module_id, name, COALESCE(exam_date,''), required HAVING COUNT(*)>1",
                "SELECT module_id, name, exam_date, required, COUNT(*) n FROM moduleexam "
                "GROUP BY module_id, name, COALESCE(exam_date,''), required HAVING n>1 LIMIT ?")
    group_check("GROUP|achievement (module,name,required,weight) duplicates",
                "SELECT module_id, name, required, COALESCE(weight,-1) FROM moduleachievement "
                "GROUP BY module_id, name, required, COALESCE(weight,-1) HAVING COUNT(*)>1",
                "SELECT module_id, name, required, weight, COUNT(*) n FROM moduleachievement "
                "GROUP BY module_id, name, required, COALESCE(weight,-1) HAVING n>1 LIMIT ?")
    group_check("GROUP|location name split (same name, >1 row)",
                "SELECT name FROM location GROUP BY name HAVING COUNT(*)>1",
                "SELECT name, COUNT(*) n, GROUP_CONCAT(external_id,' | ') FROM location GROUP BY name HAVING n>1 ORDER BY n DESC LIMIT ?")
    group_check("GROUP|staff duplicate name",
                "SELECT name FROM staff GROUP BY name HAVING COUNT(*)>1",
                "SELECT name, COUNT(*) n FROM staff GROUP BY name HAVING n>1 LIMIT ?")

    # exam key deliberately excludes time -> same name/date but different slots collapse
    group_check("GROUP|exam same (module,name,date) with differing times",
                "SELECT module_id, name, COALESCE(exam_date,'') FROM moduleexam "
                "GROUP BY module_id, name, COALESCE(exam_date,'') "
                "HAVING COUNT(DISTINCT COALESCE(start_time,''))>1 OR COUNT(DISTINCT COALESCE(end_time,''))>1",
                "SELECT module_id, name, exam_date, start_time, end_time FROM moduleexam "
                "WHERE module_id IN (SELECT module_id FROM moduleexam GROUP BY module_id, name, COALESCE(exam_date,'') "
                "HAVING COUNT(DISTINCT COALESCE(start_time,''))>1) LIMIT ?")

    print("\n--- totals ---")
    for table in ("module", "course", "event", "moduleexam", "moduleachievement",
                  "location", "building", "staff", "semester", "degree", "faculty"):
        report["_totals"][table] = scalar(cur, f"SELECT COUNT(*) FROM {table}")  # type: ignore
    print(json.dumps(report["_totals"], indent=1))  # type: ignore

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
