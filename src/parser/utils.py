import logging
import re
from threading import Event

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


# Silence noisy httpx logs as soon as this module is imported.
_silence_httpx_logs()
