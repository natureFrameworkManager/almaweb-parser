"""Dataset-wide consistency audit for the parsed AlmaWeb database.

Many parser bugs ("module missing from semester", "wrong link", "missing data")
only show up in aggregate and are impractical to spot by browsing the API.  This
module runs fast, read-only SQL checks over the whole SQLite database and prints
a report, and optionally diffs the stored modules against a crawl snapshot to
catch modules that were found but never landed in the database.

Run it after every parse::

    python -m src.parser.audit
    python -m src.parser.audit --snapshot snapshots/modules_latest.json --sample 20
    python -m src.parser.audit --json audit.json

Checks are classified as ``error`` (structural link/data integrity) or ``warn``
(quality issues that may be legitimate).  The process exits non-zero when errors
are found, or when ``--strict`` is given and any warning is found.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from .snapshot import DEFAULT_SNAPSHOT_DIR, LATEST_MODULES_FILE, load_modules
except (ImportError, ModuleNotFoundError):
    from src.parser.snapshot import DEFAULT_SNAPSHOT_DIR, LATEST_MODULES_FILE, load_modules  # type: ignore

try:
    from .utils import warning_summary
except (ImportError, ModuleNotFoundError):
    from src.parser.utils import warning_summary  # type: ignore

try:
    from database.database import engine
except ModuleNotFoundError:
    from src.database.database import engine  # type: ignore


@dataclass
class Check:
    key: str
    label: str
    sql: str
    severity: str = "error"
    sample_sql: str | None = None
    hint: str = ""


TOTALS_SQL: dict[str, str] = {
    "modules": "SELECT COUNT(*) FROM module",
    "courses": "SELECT COUNT(*) FROM course",
    "events": "SELECT COUNT(*) FROM event",
    "locations": "SELECT COUNT(*) FROM location",
    "buildings": "SELECT COUNT(*) FROM building",
    "degrees": "SELECT COUNT(*) FROM degree",
    "semesters": "SELECT COUNT(*) FROM semester",
    "faculties": "SELECT COUNT(*) FROM faculty",
    "staff": "SELECT COUNT(*) FROM staff",
}


CHECKS: list[Check] = [
    Check(
        "modules_without_semester",
        "Modules not linked to any semester",
        "SELECT COUNT(*) FROM module m WHERE NOT EXISTS "
        "(SELECT 1 FROM modulesemesterlink l WHERE l.module_id = m.id)",
        sample_sql="SELECT m.number, m.name FROM module m WHERE NOT EXISTS "
        "(SELECT 1 FROM modulesemesterlink l WHERE l.module_id = m.id) LIMIT :n",
        hint="The module's path has no parsable semester, or the link was never created.",
    ),
    Check(
        "modules_without_start_semester",
        "Modules without a start-semester link",
        "SELECT COUNT(*) FROM module m WHERE NOT EXISTS "
        "(SELECT 1 FROM modulestartsemesterlink l WHERE l.module_id = m.id)",
        hint="`Startsemester` was missing/empty on the module page.",
    ),
    Check(
        "modules_without_courses",
        "Modules not linked to any course",
        "SELECT COUNT(*) FROM module m WHERE NOT EXISTS "
        "(SELECT 1 FROM modulecourselink l WHERE l.module_id = m.id)",
        sample_sql="SELECT m.number, m.name FROM module m WHERE NOT EXISTS "
        "(SELECT 1 FROM modulecourselink l WHERE l.module_id = m.id) LIMIT :n",
        hint="No COURSEDETAILS links were found on the module page.",
    ),
    Check(
        "modules_without_degrees",
        "Modules not linked to any degree",
        "SELECT COUNT(*) FROM module m WHERE NOT EXISTS "
        "(SELECT 1 FROM moduledegreelink l WHERE l.module_id = m.id)",
        severity="warn",
        hint="Run `-a sync_degrees=1` or `python -m src.parser.degree_parser`.",
    ),
    Check(
        "modules_without_faculty",
        "Modules without a faculty",
        "SELECT COUNT(*) FROM module WHERE faculty_id IS NULL",
        severity="warn",
        hint="Faculty prefix in path did not match the module number prefix.",
    ),
    Check(
        "modules_with_empty_path",
        "Modules with an empty navigation path",
        "SELECT COUNT(*) FROM module WHERE path IS NULL OR path = '[]' OR path = 'null'",
        sample_sql="SELECT number, name FROM module WHERE path IS NULL OR path = '[]' OR path = 'null' LIMIT :n",
        severity="warn",
    ),
    Check(
        "modules_zero_credits",
        "Modules with 0 credits",
        "SELECT COUNT(*) FROM module WHERE credits = 0",
        sample_sql="SELECT number, name FROM module WHERE credits = 0 LIMIT :n",
        severity="warn",
    ),
    Check(
        "modules_zero_duration",
        "Modules with 0 duration semesters",
        "SELECT COUNT(*) FROM module WHERE duration_semesters = 0",
        sample_sql="SELECT number, name FROM module WHERE duration_semesters = 0 LIMIT :n",
        severity="warn",
    ),
    Check(
        "courses_without_events",
        "Courses not linked to any event",
        "SELECT COUNT(*) FROM course c WHERE NOT EXISTS "
        "(SELECT 1 FROM courseeventlink l WHERE l.course_id = c.id)",
        sample_sql="SELECT c.number, c.name FROM course c WHERE NOT EXISTS "
        "(SELECT 1 FROM courseeventlink l WHERE l.course_id = c.id) LIMIT :n",
        severity="warn",
        hint="Often legitimate: many courses (Praktikum, Schulpraktische Studien, self-study) "
        "have an empty Termine table in AlmaWeb. Investigate a sample only if its source page shows dates.",
    ),
    Check(
        "courses_without_modules",
        "Orphan courses (no module link)",
        "SELECT COUNT(*) FROM course c WHERE NOT EXISTS "
        "(SELECT 1 FROM modulecourselink l WHERE l.course_id = c.id)",
        sample_sql="SELECT c.number, c.name FROM course c WHERE NOT EXISTS "
        "(SELECT 1 FROM modulecourselink l WHERE l.course_id = c.id) LIMIT :n",
    ),
    Check(
        "events_without_location",
        "Events without a location",
        "SELECT COUNT(*) FROM event WHERE location_id IS NULL",
        severity="warn",
        hint="The term row's room cell was empty in AlmaWeb (legitimate) or the room page failed to parse.",
    ),
    Check(
        "events_without_location_mixed",
        "Events missing a location in an otherwise located course",
        "SELECT COUNT(*) FROM event e WHERE e.location_id IS NULL AND EXISTS ("
        "SELECT 1 FROM courseeventlink l1 JOIN courseeventlink l2 ON l2.course_id = l1.course_id "
        "JOIN event e2 ON e2.id = l2.event_id "
        "WHERE l1.event_id = e.id AND e2.location_id IS NOT NULL)",
        sample_sql="SELECT c.number, c.name, COUNT(*) AS unlocated FROM event e "
        "JOIN courseeventlink l ON l.event_id = e.id JOIN course c ON c.id = l.course_id "
        "WHERE e.location_id IS NULL AND EXISTS ("
        "SELECT 1 FROM courseeventlink l2 JOIN event e2 ON e2.id = l2.event_id "
        "WHERE l2.course_id = l.course_id AND e2.location_id IS NOT NULL) "
        "GROUP BY c.id LIMIT :n",
        severity="warn",
        hint="Sibling terms have rooms, so these are the most likely room-page fetch failures -- but they can "
        "also be terms without a room (e.g. online sessions). Re-parse with --refresh and inspect one course "
        "with `python -m src.parser.debug parse-course <url>`.",
    ),
    Check(
        "events_without_courses",
        "Orphan events (no course link)",
        "SELECT COUNT(*) FROM event e WHERE NOT EXISTS "
        "(SELECT 1 FROM courseeventlink l WHERE l.event_id = e.id)",
    ),
    Check(
        "events_without_semester",
        "Events not linked to any semester",
        "SELECT COUNT(*) FROM event e WHERE NOT EXISTS "
        "(SELECT 1 FROM eventsemesterlink l WHERE l.event_id = e.id)",
    ),
    Check(
        "locations_without_events",
        "Locations never used by an event",
        "SELECT COUNT(*) FROM location l WHERE NOT EXISTS "
        "(SELECT 1 FROM event e WHERE e.location_id = l.id)",
        severity="warn",
    ),
    Check(
        "locations_without_building",
        "Locations without a building",
        "SELECT COUNT(*) FROM location WHERE building_id IS NULL",
        severity="warn",
    ),
    Check(
        "orphan_degrees",
        "Degrees not linked to any module",
        "SELECT COUNT(*) FROM degree d WHERE NOT EXISTS "
        "(SELECT 1 FROM moduledegreelink l WHERE l.degree_id = d.id)",
        severity="warn",
        hint="Prune with `python -m src.parser.degree_parser --prune`.",
    ),
    Check(
        "orphan_staff",
        "Staff not linked to any data row",
        "SELECT COUNT(*) FROM staff s WHERE NOT EXISTS "
        "(SELECT 1 FROM modulestafflink l WHERE l.staff_id = s.id) AND NOT EXISTS "
        "(SELECT 1 FROM coursestafflink l WHERE l.staff_id = s.id) AND NOT EXISTS "
        "(SELECT 1 FROM eventstafflink l WHERE l.staff_id = s.id) AND NOT EXISTS "
        "(SELECT 1 FROM moduleexamstafflink l WHERE l.staff_id = s.id)",
        severity="warn",
    ),
    Check(
        "duplicate_module_numbers",
        "Module numbers with several distinct names",
        "SELECT COUNT(*) FROM (SELECT number FROM module GROUP BY number "
        "HAVING COUNT(DISTINCT name) > 1)",
        sample_sql="SELECT number, COUNT(DISTINCT name) AS variants FROM module "
        "GROUP BY number HAVING COUNT(DISTINCT name) > 1 LIMIT :n",
        severity="warn",
        hint="Same number parsed into different names across pages/semesters.",
    ),
]


def _rows(session, sql: str, params: dict[str, Any] | None = None) -> list[tuple]:
    return list(session.connection().exec_driver_sql(sql, params or {}).fetchall())


def _count(session, sql: str, params: dict[str, Any] | None = None) -> int:
    rows = _rows(session, sql, params)
    return int(rows[0][0]) if rows else 0


# A module-number token contains both a digit and a hyphen, e.g. ``12-111-0001``,
# ``A04-004-1001``, ``01-DKE-1000.PS01``, ``07-ERA-SoSe11``. Deliberately does NOT match
# labels like ``P1``/``P11`` that merely contain a digit, since those are part of the name.
def _is_number_token(token: str) -> bool:
    return "-" in token and any(char.isdigit() for char in token)


def _normalize_name(value: str) -> str:
    """Lower-case a module label and drop a leading module-number token (``NN-NNN-NNNN``)."""
    value = (value or "").strip().lower()
    parts = value.split(None, 1)
    if len(parts) == 2 and _is_number_token(parts[0]):
        value = parts[1]
    return re.sub(r"\s+", " ", value).strip()


def _leading_number_token(value: str) -> str | None:
    """Return the leading token of a module label if it looks like a module number."""
    stripped = (value or "").strip()
    if not stripped:
        return None
    token = stripped.split(None, 1)[0]
    return token if _is_number_token(token) else None


def snapshot_diff(session, snapshot_path: str | Path, sample: int = 10) -> dict[str, Any]:
    """Compare modules found by the crawl (snapshot) with the modules stored in the DB.

    A snapshot module is ``matched`` when its normalized name is stored, ``renamed``
    when a module with the same number but a different name is stored (so renames /
    title changes are not misreported as missing), and ``not_in_db`` otherwise.
    """
    snapshot_modules = load_modules(snapshot_path)
    db_rows = _rows(session, "SELECT number, name FROM module")
    by_name: dict[str, list[tuple[str, str]]] = defaultdict(list)
    by_number: dict[str, set[str]] = defaultdict(set)
    for number, name in db_rows:
        normalized = _normalize_name(name)
        if normalized:
            by_name[normalized].append((number, name))
        if number:
            by_number[number].add(normalized)

    matched = 0
    renamed = 0
    renamed_sample: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    for module in snapshot_modules:
        normalized = _normalize_name(module.name)
        if normalized in by_name:
            matched += 1
            continue
        number = _leading_number_token(module.name)
        if number and number in by_number:
            renamed += 1
            if len(renamed_sample) < sample:
                renamed_sample.append({
                    "name": module.name,
                    "number": number,
                    "db_names": sorted(name for name in by_number[number] if name)[:3],
                })
            continue
        missing.append({"name": module.name, "url": module.url})

    stored_without_semester = _count(
        session,
        "SELECT COUNT(*) FROM module m WHERE NOT EXISTS "
        "(SELECT 1 FROM modulesemesterlink l WHERE l.module_id = m.id)",
    )
    return {
        "snapshot_path": str(snapshot_path),
        "snapshot_modules": len(snapshot_modules),
        "db_modules": len(by_name),
        "matched": matched,
        "renamed": renamed,
        "renamed_sample": renamed_sample,
        "not_in_db": len(missing),
        "not_in_db_sample": missing[:sample],
        "db_modules_without_semester": stored_without_semester,
    }


def run_audit(session, snapshot: str | None = None, sample: int = 10, warnings_path: str | None = None) -> dict[str, Any]:
    """Run all checks and return a structured result dict."""
    totals = {key: _count(session, sql) for key, sql in TOTALS_SQL.items()}
    results: list[dict[str, Any]] = []
    for check in CHECKS:
        count = _count(session, check.sql)
        entry: dict[str, Any] = {
            "key": check.key,
            "label": check.label,
            "severity": check.severity,
            "count": count,
            "hint": check.hint,
        }
        if count and check.sample_sql:
            entry["sample"] = [list(row) for row in _rows(session, check.sample_sql, {"n": sample})]
        results.append(entry)

    diff = None
    if snapshot:
        snapshot_path = Path(snapshot)
        if snapshot_path.is_file():
            diff = snapshot_diff(session, snapshot_path, sample=sample)
        else:
            diff = {"snapshot_path": str(snapshot_path), "error": "snapshot not found"}

    errors = sum(1 for entry in results if entry["severity"] == "error" and entry["count"])
    warnings = sum(1 for entry in results if entry["severity"] == "warn" and entry["count"])
    return {
        "totals": totals,
        "checks": results,
        "snapshot_diff": diff,
        "warnings_log": warning_summary(warnings_path),
        "errors": errors,
        "warnings": warnings,
    }


def _print_report(result: dict[str, Any], sample: int) -> None:
    """Render the audit result to the terminal (rich if available, plain otherwise)."""
    try:
        from rich.console import Console
        from rich.table import Table
    except ImportError:
        _print_report_plain(result)
        return

    console = Console()
    console.rule("[bold]AlmaWeb dataset audit")
    console.print("Totals: " + ", ".join(f"{key}={value}" for key, value in result["totals"].items()))

    table = Table()
    table.add_column("Status")
    table.add_column("Severity")
    table.add_column("Check")
    table.add_column("Count", justify="right")
    for entry in result["checks"]:
        count = entry["count"]
        if count == 0:
            status = "[green]OK[/green]"
        elif entry["severity"] == "error":
            status = "[red]FAIL[/red]"
        else:
            status = "[yellow]WARN[/yellow]"
        table.add_row(status, entry["severity"], entry["label"], str(count))
    console.print(table)

    for entry in result["checks"]:
        if not entry["count"]:
            continue
        console.print(f"\n[bold]{entry['label']}[/bold] ({entry['count']})")
        for row in entry.get("sample", []):
            console.print("  " + " — ".join(str(cell).replace("\n", " ") for cell in row))
        if entry["hint"]:
            console.print(f"  [dim]hint: {entry['hint']}[/dim]")

    diff = result.get("snapshot_diff")
    if diff is not None:
        console.rule("Snapshot diff")
        if diff.get("error"):
            console.print(f"[red]{diff['error']}: {diff['snapshot_path']}[/red]")
        else:
            console.print(
                f"snapshot modules={diff['snapshot_modules']}, stored modules={diff['db_modules']}, "
                f"matched={diff['matched']}, renamed={diff['renamed']}, not in DB={diff['not_in_db']}, "
                f"DB modules without semester={diff['db_modules_without_semester']}"
            )
            for entry in diff.get("renamed_sample", []):
                console.print(
                    f"  [yellow]renamed[/yellow] {entry['name']} → {', '.join(entry['db_names']) or '(empty)'}"
                )
            for entry in diff.get("not_in_db_sample", []):
                console.print(f"  [red]missing[/red] {entry['name']}")

    warnings_log = result.get("warnings_log")
    if warnings_log and warnings_log.get("total"):
        console.rule("Parser warnings log")
        console.print(f"{warnings_log['total']} warning(s) in {warnings_log['path']}")
        for kind, count in warnings_log["counts"].items():
            console.print(f"  {count:>6}  {kind}")

    console.rule("Result")
    if result["errors"]:
        console.print(f"[red]{result['errors']} error check(s), {result['warnings']} warning check(s).[/red]")
    elif result["warnings"]:
        console.print(f"[yellow]No errors, {result['warnings']} warning check(s).[/yellow]")
    else:
        console.print("[green]All checks passed.[/green]")


def _print_report_plain(result: dict[str, Any]) -> None:
    print("=== AlmaWeb dataset audit ===")
    print("Totals: " + ", ".join(f"{key}={value}" for key, value in result["totals"].items()))
    for entry in result["checks"]:
        if entry["count"] == 0:
            status = "OK"
        elif entry["severity"] == "error":
            status = "FAIL"
        else:
            status = "WARN"
        print(f"[{status}] ({entry['severity']}) {entry['label']}: {entry['count']}")
        if entry["hint"] and entry["count"]:
            print(f"        hint: {entry['hint']}")
    diff = result.get("snapshot_diff")
    if diff is not None and not diff.get("error"):
        print(
            f"Snapshot diff: modules={diff['snapshot_modules']}, stored={diff['db_modules']}, "
            f"matched={diff['matched']}, renamed={diff['renamed']}, not in DB={diff['not_in_db']}"
        )
        for entry in diff.get("renamed_sample", []):
            print(f"  renamed {entry['name']} -> {', '.join(entry['db_names']) or '(empty)'}")
        for entry in diff.get("not_in_db_sample", []):
            print(f"  missing {entry['name']}")
    warnings_log = result.get("warnings_log")
    if warnings_log and warnings_log.get("total"):
        print(f"Parser warnings: {warnings_log['total']} in {warnings_log['path']}")
        for kind, count in warnings_log["counts"].items():
            print(f"  {count:>6}  {kind}")
    print(
        f"Result: {result['errors']} error check(s), {result['warnings']} warning check(s)."
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit the parsed AlmaWeb database for missing data and links.")
    parser.add_argument(
        "--snapshot",
        default=str(Path(DEFAULT_SNAPSHOT_DIR) / LATEST_MODULES_FILE),
        help="Crawl snapshot used for the found-vs-stored diff.",
    )
    parser.add_argument("--sample", type=int, default=10, help="Number of sample rows per failing check.")
    parser.add_argument("--json", default=None, help="Write the full result as JSON to this path.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero on warnings too.")
    parser.add_argument("--warnings-log", default=None, help="Path to parser-warnings.jsonl (default: logs/).")
    parser.add_argument("--no-warnings", action="store_true", help="Skip the parser warnings summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    try:
        from database.database import create_db_and_tables
    except ModuleNotFoundError:
        from src.database.database import create_db_and_tables

    create_db_and_tables()

    from sqlmodel import Session

    snapshot = args.snapshot
    if snapshot and not Path(snapshot).is_file():
        snapshot = None

    with Session(engine) as session:
        result = run_audit(
            session,
            snapshot=snapshot,
            sample=args.sample,
            warnings_path=None if args.no_warnings else args.warnings_log,
        )

    _print_report(result, args.sample)

    if args.json:
        Path(args.json).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Wrote audit report to {args.json}.")

    if result["errors"]:
        return 1
    if args.strict and result["warnings"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



