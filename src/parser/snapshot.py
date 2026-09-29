"""JSON savepoints for the crawl results so parsing can be re-run without crawling.

The Scrapy crawl collects every module link (and its navigation path) in memory
and only hands it to the parser in the spider's ``closed`` callback.  If the
crawl crashes -- or when you simply want to iterate on the parser -- that data is
gone.  This module snapshots the crawl result to ``snapshots/`` as JSON and loads
it back, so crawling and parsing become independent, resumable steps.

Two files are written on every crawl:

* ``snapshots/crawl-<timestamp>.json`` -- immutable, keeps a history.
* ``snapshots/modules_latest.json`` -- overwritten, the default input for
  ``python -m src.parser.run_parse``.

A module is stored as ``{"name", "url", "path"}``; ``path`` may be a flat list of
nodes or a list of such lists when a module is reachable through several paths
(see ``LectureSpider.module_set``).
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_SNAPSHOT_DIR = "snapshots"
LATEST_MODULES_FILE = "modules_latest.json"
STREAM_MODULES_FILE = "modules_stream.jsonl"


@dataclass
class SnapshotModule:
    """A module link restored from a snapshot (``ModuleLink``-compatible)."""

    name: str
    url: str
    path: Any = field(default_factory=list)

    def tostring(self) -> str:
        first: Any = self.path
        if self.path and isinstance(self.path[0], list):
            first = self.path[0]
        return f"{self.name} (Path: {' > '.join(str(node) for node in first)})"


def _module_to_dict(module: Any) -> dict[str, Any]:
    return {"name": module.name, "url": module.url, "path": module.path}


def write_crawl_snapshot(
    found_faculties: list[dict[str, Any]],
    found_modules: list[Any],
    directory: str | Path = DEFAULT_SNAPSHOT_DIR,
    timestamp: str | None = None,
) -> dict[str, Path]:
    """Write the crawl result as a dated and a ``latest`` JSON snapshot."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    ts = timestamp or time.strftime("%Y%m%d-%H%M%S")
    payload = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "count": len(found_modules),
        "faculties": [dict(faculty) for faculty in found_faculties],
        "modules": [_module_to_dict(module) for module in found_modules],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    dated = directory / f"crawl-{ts}.json"
    latest = directory / LATEST_MODULES_FILE
    dated.write_text(text, encoding="utf-8")
    latest.write_text(text, encoding="utf-8")
    return {"dated": dated, "latest": latest}


def append_module_jsonl(
    module: Any,
    directory: str | Path = DEFAULT_SNAPSHOT_DIR,
    filename: str = STREAM_MODULES_FILE,
) -> Path:
    """Append a single discovered module to a JSONL stream (crash resilience)."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_module_to_dict(module), ensure_ascii=False) + "\n")
    return path


def load_snapshot(path: str | Path) -> dict[str, Any]:
    """Load a snapshot file and normalise it to a payload dict."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        # Tolerate a plain list of modules (older/ad-hoc dumps).
        return {"modules": payload, "faculties": []}
    return payload


def load_modules(path: str | Path) -> list[SnapshotModule]:
    """Load the module list from a snapshot file."""
    payload = load_snapshot(path)
    return [
        SnapshotModule(
            name=str(entry.get("name", "")),
            url=str(entry.get("url", "")),
            path=entry.get("path", []),
        )
        for entry in payload.get("modules", [])
    ]


def load_faculties(path: str | Path) -> list[dict[str, Any]]:
    """Load the faculty list from a snapshot file."""
    payload = load_snapshot(path)
    return list(payload.get("faculties", []))


def _path_strings(path: Any) -> list[str]:
    """Flatten a (possibly nested) module path to a list of node strings."""
    if not path:
        return []
    if any(isinstance(node, list) for node in path):
        return [str(node) for group in path for node in group]
    return [str(node) for node in path]


def filter_modules(
    modules: list[SnapshotModule],
    *,
    only: str | None = None,
    path_contains: str | None = None,
    semester: str | None = None,
    number: str | None = None,
    limit: int | None = None,
) -> list[SnapshotModule]:
    """Filter a module list for fast, targeted parser runs.

    ``only`` is a regex matched against the module name; ``path_contains`` and
    ``semester`` are case-insensitive substrings matched against any path node;
    ``number`` is a substring match against the module number.
    """
    result = modules
    if only:
        pattern = re.compile(only, re.IGNORECASE)
        result = [m for m in result if pattern.search(m.name)]
    if number:
        needle = number.lower()
        result = [m for m in result if needle in m.name.lower()]
    if path_contains:
        needle = path_contains.lower()
        result = [m for m in result if any(needle in node.lower() for node in _path_strings(m.path))]
    if semester:
        needle = semester.lower()
        result = [m for m in result if any(needle in node.lower() for node in _path_strings(m.path))]
    if limit is not None:
        result = result[:limit]
    return result
