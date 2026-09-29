import json
import logging
import os
import re
import time
from pathlib import Path
from threading import Event, Lock
from typing import Any

_WHITESPACE_RE = re.compile(r"\s+")


def _silence_httpx_logs() -> None:
    for name in ("httpx", "httpcore", "httpcore.http11", "httpcore.connection"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = False
        logger.setLevel(logging.CRITICAL + 1)
        logger.disabled = True


def _cancelled(cancel_event: Event | None) -> bool:
    return cancel_event is not None and cancel_event.is_set()

def _is_multidimensional(arr: list) -> bool:
    for element in arr:
        if isinstance(element, list):
            return True
    return False


# ---------------------------------------------------------------------------
# Structured parser warnings
#
# Parsers used to emit bare ``print`` statements for recoverable problems
# ("No events content found ...", "Failed to parse date: ...").  Those are now
# routed through :func:`log_warning`, which both echoes them (keeping the CLI
# behaviour) and appends one JSON object per warning to
# ``logs/parser-warnings.jsonl`` so the whole dataset can be summarised by the
# audit tool.
# ---------------------------------------------------------------------------
DEFAULT_LOG_DIR = "logs"
WARNINGS_FILENAME = "parser-warnings.jsonl"

_warn_lock = Lock()
_warn_print = True


def warning_log_path(path: str | os.PathLike[str] | None = None) -> Path:
    """Return the warnings log path (``ALMAWEB_LOG_DIR`` overrides the directory)."""
    if path is not None:
        return Path(path)
    directory = os.environ.get("ALMAWEB_LOG_DIR", DEFAULT_LOG_DIR)
    return Path(directory) / WARNINGS_FILENAME


def set_warning_print(enabled: bool) -> None:
    """Enable/disable echoing warnings to stdout (they are always logged to JSONL)."""
    global _warn_print
    _warn_print = enabled


def log_warning(kind: str, message: str, path: str | os.PathLike[str] | None = None, **context: Any) -> None:
    """Record a parser warning as one JSONL line and echo it to stdout.

    ``kind`` is a short machine-readable category (e.g. ``failed_date``) used by
    the audit to group warnings.  This never raises: logging failures are ignored
    so a read-only or full filesystem cannot break parsing.
    """
    if _warn_print:
        print(message)
    record = {"ts": time.time(), "kind": kind, "message": message, "context": context}
    try:
        target = warning_log_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, default=str)
        with _warn_lock:
            with target.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
    except OSError:
        pass


def read_warnings(
    path: str | os.PathLike[str] | None = None, kinds: set[str] | None = None
) -> list[dict[str, Any]]:
    """Read all recorded warnings, optionally filtered to specific ``kinds``."""
    target = warning_log_path(path)
    if not target.is_file():
        return []
    records: list[dict[str, Any]] = []
    try:
        for line in target.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if kinds and record.get("kind") not in kinds:
                continue
            records.append(record)
    except OSError:
        return []
    return records


def warning_summary(path: str | os.PathLike[str] | None = None, limit: int = 15) -> dict[str, Any]:
    """Return the total warning count and the most frequent warning ``kind``s."""
    records = read_warnings(path)
    counts: dict[str, int] = {}
    for record in records:
        kind = str(record.get("kind", "unknown"))
        counts[kind] = counts.get(kind, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]
    return {"total": len(records), "counts": dict(ordered), "path": str(warning_log_path(path))}


# Silence noisy httpx logs as soon as this module is imported.
_silence_httpx_logs()
