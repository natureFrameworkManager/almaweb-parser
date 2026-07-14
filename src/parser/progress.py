"""
Progress tracking with styled terminal output for the crawler and parser.

Provides a ProgressTracker class that manages multi-phase progress display
using rich for spinners, styled progress bars, and a live display pinned
to the bottom of the terminal.
"""

import logging
import sys
from logging import Handler, LogRecord
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
)

# ANSI color codes (kept for summary output)
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_BLUE = "\033[34m"
_MAGENTA = "\033[35m"
_RED = "\033[31m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RESET = "\033[0m"

# Phase color assignments (rich color names)
_PHASE_COLORS: dict[str, str] = {
    "semesters": "cyan",
    "faculties": "cyan",
    "nodes": "cyan",
    "modules_found": "cyan",
    "modules": "yellow",
    "courses": "blue",
    "events": "magenta",
    "exams": "green",
    "rooms": "cyan",
}

# Phase display labels
_PHASE_LABELS: dict[str, str] = {
    "semesters": "Semesters",
    "faculties": "Faculties",
    "nodes": "Nodes",
    "modules_found": "Modules",
    "modules": "Modules",
    "courses": "Courses",
    "events": "Events",
    "exams": "Exams",
    "rooms": "Rooms",
}

# Phase grouping
_CRAWLING_PHASES = ("semesters", "faculties", "nodes", "modules_found")
_PARSING_PHASES = ("modules", "courses", "events", "exams", "rooms")


class _RichLogHandler(Handler):
    """Logging handler that redirects log records to a rich Console.

    This ensures all logger output is managed by the rich Live display,
    preventing log messages from breaking the pinned progress bars.
    """

    def __init__(self, console: Console) -> None:
        super().__init__()
        self.console = console
        # Use a format that preserves the timestamp and level, so the
        # output is consistent with the original Scrapy logging.
        self.setFormatter(logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))

    def emit(self, record: LogRecord) -> None:
        try:
            # Respect the logger's level filtering.
            if not self.filter(record):
                return
            msg = self.format(record)
            # markup=False prevents accidental rich markup interpretation
            # in log messages that might contain e.g. square brackets.
            self.console.print(msg, markup=False)
        except Exception:
            self.handleError(record)


class Phase:
    """Tracks progress for a single phase."""

    def __init__(self, name: str, total: int, color: str = ""):
        self.name = name
        self.total = total
        self.completed = 0
        self.color = color or _PHASE_COLORS.get(name, "")
        self.label = _PHASE_LABELS.get(name, name)

    @property
    def percentage(self) -> float:
        if self.total == 0:
            return 100.0
        return min(100.0, (self.completed / self.total) * 100.0)

    @property
    def is_finished(self) -> bool:
        return self.completed >= self.total > 0


class ProgressTracker:
    """Manages multi-phase progress display.

    Uses rich SpinnerColumn + BarColumn for a polished look, and a Live
    display to keep all progress bars pinned to the bottom of the terminal.
    The public API is identical to the previous implementation so that hooks
    in crawler and parser code do not need to change.
    """

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.phases: dict[str, Phase] = {}
        self._task_ids: dict[str, TaskID] = {}
        self._progress: Progress | None = None
        self._live: Live | None = None
        self._crawling_finished = False
        self._parsing_started = False
        self._has_output = False
        self._crawling_tasks_added = False
        self._parsing_tasks_added = False
        self._console = Console(stderr=True)
        self._log_handler: _RichLogHandler | None = None
        self._original_log_handlers: list[Handler] = []

    # ------------------------------------------------------------------
    # Phase management
    # ------------------------------------------------------------------

    def add_phase(self, name: str, total: int, color: str = "") -> "ProgressTracker":
        """Register a phase to track."""
        self.phases[name] = Phase(name, total, color)
        return self

    def set_total(self, name: str, total: int) -> None:
        """Update the total for a phase (e.g. when discovered during crawling)."""
        if name in self.phases:
            self.phases[name].total = total
            if name in self._task_ids and self._progress is not None:
                self._progress.update(self._task_ids[name], total=total)

    def update_total(self, name: str, total: int) -> None:
        """Add to the total for a phase (e.g. when discovered during crawling)."""
        if name in self.phases:
            self.phases[name].total += total
            if name in self._task_ids and self._progress is not None:
                self._progress.update(
                    self._task_ids[name], total=self.phases[name].total
                )

    def increment(self, name: str, amount: int = 1) -> None:
        """Increment the completed count for a phase."""
        if name in self.phases:
            self.phases[name].completed += amount
            if name in self._task_ids and self._progress is not None:
                self._progress.update(self._task_ids[name], advance=amount)

    def set_completed(self, name: str, completed: int) -> None:
        """Set the completed count for a phase directly."""
        if name in self.phases:
            self.phases[name].completed = completed
            if name in self._task_ids and self._progress is not None:
                self._progress.update(self._task_ids[name], completed=completed)

    # ------------------------------------------------------------------
    # Module tracking (kept as no-op stubs for backward compatibility)
    # ------------------------------------------------------------------

    def set_current_module(self, name: str) -> None:
        """Set the currently-being-parsed module name."""
        pass

    # ------------------------------------------------------------------
    # Live display management
    # ------------------------------------------------------------------

    def _ensure_live(self) -> None:
        """Start the Live display if it isn't already running."""
        if self._live is not None:
            return

        columns = [
            SpinnerColumn(),
            TextColumn("{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.1f}%"),
            TextColumn("[dim]({task.completed}/{task.total})[/dim]"),
        ]
        self._progress = Progress(*columns, console=self._console)
        self._live = Live(
            self._progress,
            refresh_per_second=4,
            console=self._console,
            vertical_overflow="visible",
        )
        self._live.start()
        self._has_output = True

        # Redirect the root logger through the rich console so that all
        # logger output (e.g. Scrapy spider log messages) is managed by
        # the Live display and does not break the pinned progress bars.
        self._log_handler = _RichLogHandler(self._console)
        root_logger = logging.getLogger()
        # Determine the appropriate level filter from the original handlers.
        # The root logger's effective level may be permissive (NOTSET/DEBUG),
        # but the actual handlers were the ones doing the filtering.
        self._original_log_handlers = root_logger.handlers[:]
        handler_levels = [h.level for h in self._original_log_handlers if h.level > 0]
        if handler_levels:
            # Use the most restrictive (highest numeric) level from the
            # original handlers, e.g. INFO=20 if any handler was INFO.
            self._log_handler.setLevel(max(handler_levels))
        else:
            self._log_handler.setLevel(logging.INFO)
        # Also set the root logger's level to the same value so that
        # child loggers (e.g. scrapy.core.engine) cannot emit records
        # below this threshold.
        root_logger.setLevel(self._log_handler.level)
        for handler in self._original_log_handlers:
            root_logger.removeHandler(handler)
        root_logger.addHandler(self._log_handler)

    # ------------------------------------------------------------------
    # Rendering methods (called by crawler / parser hooks)
    # ------------------------------------------------------------------

    def render_crawling(self) -> None:
        """Print crawling progress block."""
        if not self.enabled:
            return
        self._ensure_live()
        if self._crawling_tasks_added:
            return
        self._crawling_tasks_added = True

        assert self._progress is not None  # _ensure_live() guarantees this
        for name in _CRAWLING_PHASES:
            if name not in self.phases:
                continue
            phase = self.phases[name]
            color = phase.color or "cyan"
            self._task_ids[name] = self._progress.add_task(
                f"[bold {color}]{phase.label}[/bold {color}]",
                total=phase.total if phase.total > 0 else None,
                completed=phase.completed,
            )

    def render_crawling_live(self) -> None:
        """Print crawling progress block, throttled to avoid excessive output.

        With the Live display, throttling is handled automatically by rich,
        so this is equivalent to render_crawling().
        """
        self.render_crawling()

    def render_parsing(self) -> None:
        """Print parsing progress block."""
        if not self.enabled:
            return
        self._ensure_live()
        if self._parsing_tasks_added:
            return
        self._parsing_tasks_added = True

        assert self._progress is not None  # _ensure_live() guarantees this
        for name in _PARSING_PHASES:
            if name not in self.phases:
                continue
            phase = self.phases[name]
            color = phase.color or "green"
            self._task_ids[name] = self._progress.add_task(
                f"[bold {color}]{phase.label}[/bold {color}]",
                total=phase.total if phase.total > 0 else None,
                completed=phase.completed,
            )

    def start_parsing(self) -> None:
        """Mark the transition from crawling to parsing."""
        if not self.enabled:
            return
        self._parsing_started = True

    def finish(self) -> None:
        """Stop the live display and print final summary."""
        if not self.enabled or self._live is None:
            return

        self._live.stop()
        self._live = None
        self._progress = None

        # Restore the original logging handlers now that the Live display
        # is no longer active.
        if self._log_handler is not None:
            root_logger = logging.getLogger()
            root_logger.removeHandler(self._log_handler)
            for handler in self._original_log_handlers:
                root_logger.addHandler(handler)
            self._log_handler = None
            self._original_log_handlers = []

        self._print_summary()

    def _print_summary(self) -> None:
        """Print a summary of all phases."""
        lines: list[str] = []
        lines.append(f"{_BOLD}═══ Summary ═══{_RESET}")
        for name, phase in self.phases.items():
            label = _PHASE_LABELS.get(name, name)
            color = phase.color
            # Map rich color name to ANSI color for the summary
            ansi_color = _color_to_ansi(color)
            if phase.total > 0:
                status = f"{_GREEN}✓{_RESET}" if phase.is_finished else f"{_RED}✗{_RESET}"
                lines.append(
                    f"  {status} {ansi_color}{label}{_RESET}: {phase.completed}/{phase.total}"
                )
            else:
                lines.append(f"  {ansi_color}{label}{_RESET}: {phase.completed}")

        sys.stdout.write("\n".join(lines) + "\n")
        sys.stdout.flush()


def _color_to_ansi(color: str) -> str:
    """Convert a rich color name to the nearest ANSI escape code."""
    mapping: dict[str, str] = {
        "cyan": _CYAN,
        "green": _GREEN,
        "yellow": _YELLOW,
        "blue": _BLUE,
        "magenta": _MAGENTA,
        "red": _RED,
        "": "",
    }
    return mapping.get(color, "")