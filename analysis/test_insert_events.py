#!/usr/bin/env python3
"""Reproduce the "one bad event aborts the whole module insert" failure mode.

``Event.start_time`` / ``end_time`` / ``event_date`` are ``NOT NULL`` in the
model. ``extract_events`` yields ``None`` for a date/time it cannot parse, so a
single such Termine row makes ``insert_module_graph`` raise an ``IntegrityError``.
``handleModuleList`` catches that, logs ``module_insert_failed`` and **re-raises**,
which aborts the entire parse run (all remaining modules are lost).

This test uses an isolated temporary SQLite database; it never reads or writes
``database.db`` or ``.pagedata``.

    python analysis/test_insert_events.py
"""

from __future__ import annotations

import sys
import tempfile
from datetime import date, time
from pathlib import Path

from sqlmodel import create_engine

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import src.database.database as db  # noqa: E402


def _module_data(event: dict) -> dict:
    return {
        "name": "Audit Probe Module",
        "number": "99-AUDIT-001",
        "path": [["Root", "SoSe 2025", "10 - Fakultät für Mathematik und Informatik"]],
        "responsible_person": "",
        "duration_semesters": 1,
        "credits": 5.0,
        "start_semester": "",
        "frequency": "",
        "goals": "",
        "content": "",
        "exam_prerequisites": "",
        "prerequisites": {},
        "literature": "",
        "elective_course_count": 0,
        "elective_prerequisites": "",
        "elective_classification": "",
        "grading_note": "",
        "courses": [{
            "name": "Audit Probe Course",
            "number": "99-AUDIT-001-C1",
            "staff": [],
            "type": "Vorlesung",
            "weekly_hours": 2,
            "language": "Deutsch",
            "events": [event],
            "status": "almaweb",
            "org_unit": "",
            "official_description": "",
            "organisational": "",
            "literature": "",
        }],
        "exams": [],
        "achievements": [],
    }


def _fresh_engine():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_engine(f"sqlite:///{tmp.name}")
    db.engine = engine  # rebind the module-global used by insert_module_graph
    db.create_db_and_tables()
    return engine


def main() -> int:
    good_event = {
        "number": "1",
        "event_date": date(2025, 4, 8),
        "start_time": time(13, 15),
        "end_time": time(14, 45),
        "location": None,
        "staff": [],
    }

    _fresh_engine()
    ok, counts = db.insert_module_graph(_module_data(good_event))
    print(f"valid module inserted ok={ok} events={counts['events']} (expected ok=True events=1)")
    assert ok and counts["events"] == 1

    bad_event = dict(good_event, number="2", event_date=None)
    _fresh_engine()
    try:
        db.insert_module_graph(_module_data(bad_event))
    except Exception as exc:  # noqa: BLE001
        print(f"event_date=None -> {type(exc).__name__}: {str(exc)[:100]}")
        print("=> a single unparseable Termine row makes the whole module insert fail")
        return 0
    print("UNEXPECTED: insert with event_date=None succeeded")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
