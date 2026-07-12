"""
Progress tracking with styled terminal output for the crawler and parser.

Provides a ProgressTracker class that manages multi-phase progress display.
Writes to stdout (separate from scrapy's stderr logs) using simple block output
without cursor control, so it doesn't interfere with scrapy's logging.
"""

import sys
import time
from typing import Any

# ANSI color codes
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_BLUE = "\033[34m"
_MAGENTA = "\033[35m"
_RED = "\033[31m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RESET = "\033[0m"

# Minimum interval between progress renders (seconds)
_RENDER_INTERVAL = 2.0

# Phase color assignments
_PHASE_COLORS: dict[str, str] = {
    "semesters": _CYAN,
    "faculties": _CYAN,
    "nodes": _CYAN,
    "modules_found": _CYAN,
    "modules": _YELLOW,
    "courses": _BLUE,
    "events": _MAGENTA,
    "rooms": _CYAN,
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
    "rooms": "Rooms",
}

# Phase grouping
_CRAWLING_PHASES = ("semesters", "faculties", "nodes", "modules_found")
_PARSING_PHASES = ("modules", "courses", "events", "rooms")


class Phase:
    """Tracks progress for a single phase."""

    def __init__(self, name: str, total: int, color: str = ""):
        self.name = name
        self.total = total
        self.completed = 0
        self.color = color or _PHASE_COLORS.get(name, _RESET)
        self.label = _PHASE_LABELS.get(name, name)

    @property
    def percentage(self) -> float:
        if self.total == 0:
            return 100.0
        return min(100.0, (self.completed / self.total) * 100.0)

    @property
    def is_finished(self) -> bool:
        return self.completed >= self.total > 0

    def bar(self, width: int = 150) -> str:
        """Render a progress bar string like ████████░░░░ 67%."""
        if self.total == 0:
            # Unknown total: show completed count
            return f"{self.color}◉{_RESET} {self.completed}"
        filled = int(self.percentage / 100.0 * width)
        empty = width - filled
        bar = f"{self.color}█{_RESET}" * filled + f"{_DIM}░{_RESET}" * empty
        pct = f"{self.percentage:5.1f}%"
        return f"{bar} {pct}"


class ProgressTracker:
    """Manages multi-phase progress display.

    Renders progress blocks to stdout. Does NOT use cursor control, so it
    works cleanly alongside scrapy's stderr logging.
    """

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.phases: dict[str, Phase] = {}
        self._current_module: str = ""
        self._last_module: str = ""
        self._crawling_finished = False
        self._parsing_started = False
        self._has_output = False
        self._last_render_time: float = 0.0

    def add_phase(self, name: str, total: int, color: str = "") -> "ProgressTracker":
        """Register a phase to track."""
        self.phases[name] = Phase(name, total, color)
        return self

    def set_total(self, name: str, total: int) -> None:
        """Update the total for a phase (e.g. when discovered during crawling)."""
        if name in self.phases:
            self.phases[name].total = total
    
    def update_total(self, name: str, total: int) -> None:
        """Update the total for a phase (e.g. when discovered during crawling)."""
        if name in self.phases:
            self.phases[name].total += total

    def increment(self, name: str, amount: int = 1) -> None:
        """Increment the completed count for a phase."""
        if name in self.phases:
            self.phases[name].completed += amount

    def set_completed(self, name: str, completed: int) -> None:
        """Set the completed count for a phase directly."""
        if name in self.phases:
            self.phases[name].completed = completed

    def set_current_module(self, name: str) -> None:
        """Set the currently-being-parsed module name."""
        self._current_module = name

    def render_crawling(self) -> None:
        """Print crawling progress block."""
        if not self.enabled:
            return

        crawling_phases = [p for p in _CRAWLING_PHASES if p in self.phases]
        if not crawling_phases:
            return

        lines: list[str] = []
        lines.append(f"{_BOLD}{_CYAN}── Crawling Progress ──{_RESET}")
        for name in crawling_phases:
            phase = self.phases[name]
            if phase.total > 0:
                count_str = f"{_DIM}({phase.completed}/{phase.total}){_RESET}"
            else:
                count_str = ""
            lines.append(f"  {_BOLD}{phase.color}{phase.label:>12}{_RESET}  {phase.bar()}  {count_str}")

        output = "\n".join(lines) + "\n"
        sys.stdout.write(output)
        sys.stdout.flush()
        self._has_output = True
        self._last_render_time = time.time()

    def render_crawling_live(self) -> None:
        """Print crawling progress block, throttled to avoid excessive output."""
        if not self.enabled:
            return
        now = time.time()
        if now - self._last_render_time < _RENDER_INTERVAL:
            return
        self.render_crawling()

    def render_parsing(self) -> None:
        """Print parsing progress block."""
        if not self.enabled:
            return

        parsing_phases = [p for p in _PARSING_PHASES if p in self.phases]
        if not parsing_phases:
            return

        lines: list[str] = []
        lines.append(f"{_BOLD}{_GREEN}── Parsing Progress ──{_RESET}")
        for name in parsing_phases:
            phase = self.phases[name]
            if phase.total > 0:
                count_str = f"{_DIM}({phase.completed}/{phase.total}){_RESET}"
            else:
                count_str = ""
            lines.append(f"  {_BOLD}{phase.color}{phase.label:>12}{_RESET}  {phase.bar()}  {count_str}")

        if self._current_module:
            lines.append(f"  {_DIM}Current: {self._current_module}{_RESET}")
        elif self._last_module:
            lines.append(f"  {_DIM}Last: {self._last_module}{_RESET}")

        output = "\n".join(lines) + "\n"
        sys.stdout.write(output)
        sys.stdout.flush()
        self._has_output = True

    def start_parsing(self) -> None:
        """Mark the transition from crawling to parsing."""
        if not self.enabled:
            return
        self._parsing_started = True
        self._last_module = ""

    def finish(self) -> None:
        """Print final summary."""
        if not self.enabled or not self._has_output:
            return

        # Print final summary
        lines: list[str] = []
        lines.append(f"{_BOLD}═══ Summary ═══{_RESET}")
        for name, phase in self.phases.items():
            label = _PHASE_LABELS.get(name, name)
            color = phase.color
            if phase.total > 0:
                status = f"{_GREEN}✓{_RESET}" if phase.is_finished else f"{_RED}✗{_RESET}"
                lines.append(f"  {status} {color}{label}{_RESET}: {phase.completed}/{phase.total}")
            else:
                lines.append(f"  {color}{label}{_RESET}: {phase.completed}")

        sys.stdout.write("\n".join(lines) + "\n")
        sys.stdout.flush()