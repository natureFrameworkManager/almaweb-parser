#!/usr/bin/env python3
"""Prove the ``module.path`` in-place JSON mutation is not persisted.

Works on a *copy* of ``database.db`` (never the original). Loads a module through
the real SQLModel model, appends a path group the same way
``_get_or_insert_module`` does, commits, then re-opens a fresh session and checks
whether the new path was stored.

    python analysis/check_json_mutation.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from sqlmodel import Session, create_engine, select

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.database.model import Module  # noqa: E402

SRC_DB = REPO / "database.db"
COPY_DB = Path(__file__).resolve().parent / "test_json_mutation.db"


def main() -> int:
    if not SRC_DB.is_file():
        print(f"source DB missing: {SRC_DB}")
        return 1
    shutil.copyfile(SRC_DB, COPY_DB)
    engine = create_engine(f"sqlite:///{COPY_DB}")

    with Session(engine) as session:
        module = session.exec(select(Module).where(Module.id == 4)).first()
        if module is None:
            print("module id=4 not found")
            return 1
        before = list(module.path)
        marker = ["Root", "TEST_SEMESTER", "TEST_FACULTY", "TEST_DEGREE"]
        # Exactly what _get_or_insert_module does for an existing module:
        if not any(isinstance(node, list) for node in module.path):
            module.path.append(marker[0])   # mimic flat append path
        else:
            module.path.append(marker)
        session.commit()

    with Session(engine) as session:
        module = session.exec(select(Module).where(Module.id == 4)).first()
        after = list(module.path)

    print(f"before append: {len(before)} path entries")
    print(f"after  append (fresh session): {len(after)} path entries")
    if len(after) > len(before):
        print("RESULT: append WAS persisted (mutation tracked).")
    else:
        print("RESULT: append was NOT persisted -> in-place JSON mutation bug confirmed.")
    COPY_DB.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
