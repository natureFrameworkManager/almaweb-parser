"""Streaming second pass that derives degree programs from module navigation paths.

The normal module insertion (``insert_module_graph``) intentionally does **not** create
degrees. Instead, this module scans the modules already stored in the database, extracts
the Studiengang/Degree information from each module's ``path`` (using the
``path_parser`` package), harmonizes the spellings across the *entire* dataset, and then
creates ``Degree`` rows plus ``ModuleDegreeLink`` links.

Design goals (see the integration plan):

* **Two passes, bounded memory.** The full dataset is processed streaming in fixed-size
  batches; only small aggregation maps (keyed by distinct programs, not modules) are kept
  in memory. No list of all modules or all ``Studiengang`` objects is ever held.
* **Full-dataset harmonization.** The same rules as ``harmonize()`` are applied, but on
  occurrence counts instead of on the full object list (``merge_key``,
  ``most_specific_degree``, ``subject_canonicalizer``).
* **Idempotent.** Re-running only inserts missing degrees/links.

Can also be run standalone::

    python -m src.parser.degree_parser [--batch-size 500] [--prune]
"""

from __future__ import annotations

import argparse
import re
from collections import Counter, defaultdict
from typing import Callable

from sqlmodel import Session, func, select

try:
    from database.database import (
        _get_or_insert_degree,
        _link_module_degree,
        create_db_and_tables,
        engine,
    )
    from database.model import Degree, Faculty, Module, ModuleDegreeLink
except ModuleNotFoundError:
    from src.database.database import (  # type: ignore
        _get_or_insert_degree,
        _link_module_degree,
        create_db_and_tables,
        engine,
    )
    from src.database.model import Degree, Faculty, Module, ModuleDegreeLink  # type: ignore

# The path-parser package (renamed from "path-parser" so it is importable).
try:
    from .path_parser import (
        DEGREE_SPECIFICITY,
        build_name,
        degree_category,
        extract_for_paths,
        merge_key,
        subject_canonicalizer,
    )
except (ImportError, ModuleNotFoundError):
    from src.parser.path_parser import (  # type: ignore
        DEGREE_SPECIFICITY,
        build_name,
        degree_category,
        extract_for_paths,
        merge_key,
        subject_canonicalizer,
    )

_WHITESPACE_RE = re.compile(r"\s+")
# "06 - Fakultät ..." / "A10 - ..." -> numeric prefix + the rest (mirrors the extractor)
_FACULTY_PREFIX_RE = re.compile(r"^\s*A?(\d{2})\s*-\s*")
_FACULTY_NO_RE = re.compile(r"^\s*A?\d{2}\s*-\s*")
_MODULE_PREFIX_RE = re.compile(r"^A?(\d{2})")


def _strip_faculty(name: str) -> str:
    return _WHITESPACE_RE.sub(" ", _FACULTY_NO_RE.sub("", name or "")).strip()


def _normalize_paths(path) -> list[list[str]]:
    """Normalize a stored module path (flat or nested) to ``list[list[str]]``."""
    if not path:
        return []
    if any(isinstance(element, list) for element in path):
        return [[str(node) for node in p] for p in path if p]
    return [[str(node) for node in path]]


def _faculty_prefix_from_path(paths: list[list[str]]) -> int | None:
    """Return the numeric faculty prefix (e.g. ``6`` for "06 - ...") from a path, if present."""
    for path in paths:
        for node in path:
            match = _FACULTY_PREFIX_RE.match(node)
            if match:
                return int(match.group(1))
    return None


def _faculty_prefix_from_number(number: str) -> int | None:
    match = _MODULE_PREFIX_RE.match(number or "")
    return int(match.group(1)) if match else None


def _build_faculty_lookup(session: Session) -> tuple[dict[int, list[tuple[str, int]]], dict[str, int]]:
    """Build in-memory lookups (faculties are few) for resolving extractor faculty names."""
    by_prefix: dict[int, list[tuple[str, int]]] = defaultdict(list)
    by_stripped: dict[str, int] = {}
    for faculty in session.exec(select(Faculty)).all():
        if faculty.id is None:
            continue
        stripped = _strip_faculty(faculty.name)
        by_stripped.setdefault(stripped, faculty.id)
        if faculty.prefix is not None:
            by_prefix[faculty.prefix].append((stripped, faculty.id))
    return by_prefix, by_stripped


def _resolve_faculty_id(
    faculty_name: str | None,
    paths: list[list[str]],
    number: str,
    by_prefix: dict[int, list[tuple[str, int]]],
    by_stripped: dict[str, int],
) -> int | None:
    """Resolve the faculty_id for an extracted degree.

    Prefers the numeric prefix from the path (then module number) combined with the exact
    stripped name, falling back to name-only matching.
    """
    prefix = _faculty_prefix_from_path(paths)
    if prefix is None:
        prefix = _faculty_prefix_from_number(number)

    name = faculty_name or ""
    if prefix is not None and prefix in by_prefix:
        candidates = by_prefix[prefix]
        if name:
            run = _WHITESPACE_RE.sub(" ", name).strip().casefold()
            for stripped, faculty_id in candidates:
                if stripped.casefold() == run:
                    return faculty_id
        return candidates[0][1]

    if name:
        run = _WHITESPACE_RE.sub(" ", name).strip()
        if run in by_stripped:
            return by_stripped[run]
        run_cf = run.casefold()
        for stripped, faculty_id in by_stripped.items():
            if stripped.casefold() == run_cf:
                return faculty_id
    return None


def _iter_module_batches(session: Session, batch_size: int):
    """Stream ``(id, path, number)`` tuples in id-ordered batches (keyset pagination)."""
    last_id = 0
    while True:
        rows = session.exec(
            select(Module.id, Module.path, Module.number)
            .where(Module.id > last_id)
            .order_by(Module.id)
            .limit(batch_size)
        ).all()
        if not rows:
            return
        yield rows
        if len(rows) < batch_size:
            return
        last_id = rows[-1][0]  # type: ignore[index]


def _iter_studiengaenge(paths: list[list[str]]):
    """Yield only the real degree programs (kind == "studiengang") for a module."""
    if not paths:
        return
    for result in extract_for_paths(paths):
        if result.kind == "studiengang":
            yield result


def sync_module_degrees(
    session: Session,
    batch_size: int = 500,
    prune: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """Derive degrees from stored module paths and link them to modules.

    Runs bounded-memory (streaming) over the full dataset. Returns a stats dict.
    """
    def report(message: str) -> None:
        if progress is not None:
            progress(message)

    by_prefix, by_stripped = _build_faculty_lookup(session)

    # --- Pass A: build bounded harmonization maps over the full dataset -------------
    best_degrees: dict[tuple, str | None] = {}
    subject_counts: dict[tuple, Counter] = defaultdict(Counter)

    scanned = 0
    for rows in _iter_module_batches(session, batch_size):
        for _module_id, path, number in rows:
            for result in _iter_studiengaenge(_normalize_paths(path)):
                key = merge_key(result)
                current = best_degrees.get(key)
                if current is None or DEGREE_SPECIFICITY.get(result.degree, 1) > DEGREE_SPECIFICITY.get(current, 1):
                    best_degrees[key] = result.degree
                if result.subject:
                    subject_counts[(result.faculty, degree_category(result.degree))][result.subject] += 1
            scanned += 1
        report(f"[degrees] pass A: analyzed {scanned} modules")
    report(f"[degrees] pass A done: {scanned} modules, {len(best_degrees)} degree variants")

    canonical = subject_canonicalizer(subject_counts)

    # --- Pass B: apply the canonical maps and persist degrees + links ---------------
    before_degrees = session.exec(select(func.count()).select_from(Degree)).one()
    before_links = session.exec(select(func.count()).select_from(ModuleDegreeLink)).one()

    processed = 0
    for rows in _iter_module_batches(session, batch_size):
        for module_id, path, number in rows:
            paths = _normalize_paths(path)
            for result in _iter_studiengaenge(paths):
                best_degree = best_degrees.get(merge_key(result), result.degree)
                category = degree_category(best_degree)
                canon = canonical.get((result.faculty, category), {})
                subject = canon.get(result.subject, result.subject) if result.subject else result.subject
                name = build_name(subject, best_degree, result.school_type, result.ects, result.version)
                faculty_id = _resolve_faculty_id(result.faculty, paths, number, by_prefix, by_stripped)
                degree_id = _get_or_insert_degree(session, {
                    "name": name,
                    "subject": subject or "",
                    "degree": best_degree or "",
                    "school_type": result.school_type or "",
                    "ects": result.ects,
                    "version": result.version or "",
                    "confidence": result.confidence or "",
                    "faculty_id": faculty_id,
                })
                _link_module_degree(session, module_id, degree_id)
            processed += 1
        session.commit()
        report(f"[degrees] pass B: linked {processed} modules")

    stats = {
        "modules": processed,
        "degrees_created": session.exec(select(func.count()).select_from(Degree)).one() - before_degrees,
        "links_created": session.exec(select(func.count()).select_from(ModuleDegreeLink)).one() - before_links,
    }

    if prune:
        stats["degrees_pruned"] = _prune_orphan_degrees(session)

    report(f"[degrees] done: {stats}")
    return stats


def _prune_orphan_degrees(session: Session) -> int:
    """Delete degree rows that are no longer linked to any module."""
    linked_degree_ids = set(session.exec(select(ModuleDegreeLink.degree_id)).all())
    removed = 0
    for degree in session.exec(select(Degree)).all():
        if degree.id not in linked_degree_ids:
            session.delete(degree)
            removed += 1
    session.commit()
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description="Derive degrees from module paths (streaming, second pass).")
    parser.add_argument("--batch-size", type=int, default=500, help="Modules per batch (memory bound).")
    parser.add_argument("--prune", action="store_true", help="Delete degrees no longer linked to any module.")
    args = parser.parse_args()

    create_db_and_tables()
    with Session(engine) as session:
        stats = sync_module_degrees(session, batch_size=args.batch_size, prune=args.prune, progress=print)
    print(f"Degree sync finished: {stats}")


if __name__ == "__main__":
    main()