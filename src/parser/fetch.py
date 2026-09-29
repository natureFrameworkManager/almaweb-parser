"""On-disk page store and cached HTTP client for the parser.

The Scrapy crawl phase already caches navigation pages in ``.scrapy/httpcache``,
but the module/course/room parsing phase uses raw ``httpx`` and therefore
re-downloads every page on each run.  A full crawl+parse takes hours, so that is
painful when iterating on the parser.

This module adds a transparent on-disk cache ("page store") for the parser:

* Every successful ``GET`` is written to ``.pagedata/`` as the raw HTML plus a
  small ``.json`` sidecar (url, status, timestamp, headers).
* Re-runs serve identical URLs from disk, so parsing becomes offline and fast
  and every raw page stays available for manual inspection.
* ``offline=True`` refuses to touch the network and raises
  :class:`PageNotCachedError` on a cache miss, turning a silent change in the
  source data into a loud error.

The store location can be overridden with the ``ALMAWEB_PAGE_STORE`` environment
variable; set it to ``off`` to disable caching entirely.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

DEFAULT_PAGE_STORE_DIR = ".pagedata"

# How a URL is turned into a page-store key. ``exact`` uses the URL verbatim;
# the others canonicalize it first so equivalent URLs share one cache entry.
KEY_STRATEGIES = ("exact", "query-sorted", "ignore-arguments")


def normalize_url(url: str, strategy: str | Callable[[str], str] | None = "exact") -> str:
    """Canonicalize ``url`` according to ``strategy`` for use as a page-store key.

    * ``exact`` (default): return the URL unchanged.
    * ``query-sorted``: sort the query parameters (safe; handles reordering).
    * ``ignore-arguments``: drop the ``ARGUMENTS`` query parameter. **Use with
      care**: on CampusNet ``MODULEDETAILS``/``COURSEDETAILS`` pages the module or
      course identity is carried *in* ``ARGUMENTS``, so this collapses distinct
      pages onto one cache entry. It is meant for navigation pages whose
      ``ARGUMENTS`` only holds a per-request session blob.

    A callable can be passed to apply custom normalization.
    """
    if strategy is None or strategy == "exact":
        return url
    if callable(strategy):
        return strategy(url)
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    if strategy == "query-sorted":
        query = sorted(query)
    elif strategy == "ignore-arguments":
        query = [(key, value) for key, value in query if key.upper() != "ARGUMENTS"]
    else:
        raise ValueError(f"Unknown page-store key strategy: {strategy!r} (choose from {KEY_STRATEGIES})")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


class PageNotCachedError(RuntimeError):
    """Raised when offline mode is active and a URL is not in the page store."""

    def __init__(self, url: str):
        super().__init__(f"Page not in the local store (offline mode): {url}")
        self.url = url


class PageStore:
    """Content-addressed store of raw HTML pages keyed by their URL.

    ``key_strategy`` controls how URLs map to cache entries (see
    :func:`normalize_url`). The original URL is always preserved in the sidecar
    metadata, even when the key is normalized.
    """

    def __init__(
        self,
        root: str | os.PathLike[str] = DEFAULT_PAGE_STORE_DIR,
        enabled: bool = True,
        key_strategy: str | Callable[[str], str] = "exact",
    ):
        self.root = Path(root)
        self.enabled = enabled
        self.key_strategy = key_strategy

    def normalize(self, url: str) -> str:
        """Return the canonical key input for ``url`` under this store's strategy."""
        return normalize_url(url, self.key_strategy)

    def key(self, url: str) -> str:
        """Return the stable cache key (SHA-1 of the normalized URL) for ``url``."""
        return hashlib.sha1(self.normalize(url).encode("utf-8")).hexdigest()


    def _html_path(self, url: str) -> Path:
        digest = self.key(url)
        return self.root / digest[:2] / f"{digest}.html"

    def _meta_path(self, url: str) -> Path:
        digest = self.key(url)
        return self.root / digest[:2] / f"{digest}.json"

    def has(self, url: str) -> bool:
        return self.enabled and self._html_path(url).is_file()

    def path_for(self, url: str) -> Path:
        """Return the on-disk path where ``url`` is (or would be) stored."""
        return self._html_path(url)

    def get(self, url: str) -> str | None:
        """Return the cached HTML for ``url`` or ``None`` if it is not stored."""
        if not self.enabled:
            return None
        path = self._html_path(url)
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")
        return None

    def get_meta(self, url: str) -> dict[str, Any] | None:
        """Return the sidecar metadata for ``url`` or ``None`` if it is not stored."""
        if not self.enabled:
            return None
        path = self._meta_path(url)
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
        return None

    def put(self, url: str, text: str, status: int = 200, headers: Any = None) -> Path:
        """Store ``text`` for ``url`` and return the path of the written HTML file."""
        html_path = self._html_path(url)
        html_path.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(html_path, text)
        meta = {
            "url": url,
            "status": status,
            "fetched_at": time.time(),
            "headers": _headers_to_dict(headers),
        }
        _write_atomic(
            self._meta_path(url),
            json.dumps(meta, ensure_ascii=False, indent=2),
        )
        return html_path

    def count(self) -> int:
        """Return the number of stored pages."""
        if not self.root.is_dir():
            return 0
        return sum(1 for _ in self.root.rglob("*.html"))

    def iter_entries(self):
        """Yield ``(url, html_path)`` for every stored page (reads sidecar metadata).

        The HTML is intentionally not read here so callers can filter by URL first
        (e.g. only scan room pages) without touching the whole store.
        """
        if not self.root.is_dir():
            return
        for meta_path in self.root.rglob("*.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            url = meta.get("url")
            if not url:
                continue
            html_path = self._html_path(url)
            if html_path.is_file():
                yield url, html_path


def _write_atomic(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically (temp file + rename).

    The parser writes from several threads; a plain ``write_text`` can interleave
    and leave a truncated/corrupt file (observed as JSON sidecars with extra data).
    """
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _headers_to_dict(headers: Any) -> dict[str, str]:
    if headers is None:
        return {}
    try:
        return {str(key): str(value) for key, value in headers.items()}
    except AttributeError:
        return {}


_default_store: PageStore | None = None


def get_page_store(
    root: str | os.PathLike[str] | None = None,
    key_strategy: str | Callable[[str], str] | None = None,
) -> PageStore:
    """Return the process-wide page store (lazily created).

    Pass ``root`` to build a store at a specific location without touching the
    shared singleton. ``key_strategy`` falls back to the ``ALMAWEB_PAGE_KEY_STRATEGY``
    environment variable (default ``exact``).
    """
    if key_strategy is None:
        key_strategy = os.environ.get("ALMAWEB_PAGE_KEY_STRATEGY", "exact")
    if root is not None:
        return PageStore(root, key_strategy=key_strategy)
    global _default_store
    if _default_store is None:
        configured = os.environ.get("ALMAWEB_PAGE_STORE", DEFAULT_PAGE_STORE_DIR)
        if configured.strip().lower() in {"", "off", "0", "false", "none", "disabled"}:
            _default_store = PageStore(DEFAULT_PAGE_STORE_DIR, enabled=False, key_strategy=key_strategy)
        else:
            _default_store = PageStore(configured, key_strategy=key_strategy)
    return _default_store


def reset_page_store() -> None:
    """Drop the cached singleton (used by tests/CLI between runs)."""
    global _default_store
    _default_store = None


class CachedClient:
    """``httpx.Client`` wrapper that caches successful responses in a :class:`PageStore`.

    Only the subset of the client API used by the parser is implemented.  A cache
    hit is returned as an ``httpx.Response`` so callers can keep using
    ``response.text``, ``response.status_code`` and ``response.raise_for_status()``.
    """

    def __init__(
        self,
        client: httpx.Client,
        store: PageStore | None = None,
        refresh: bool = False,
        offline: bool = False,
        on_event=None,
        key_strategy: str | Callable[[str], str] | None = None,
    ):
        self._client = client
        self.store = store if store is not None else get_page_store(key_strategy=key_strategy)
        self.refresh = refresh
        self.offline = offline
        self.on_event = on_event
        self.hits = 0
        self.misses = 0

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        if not self.refresh and self.store.has(url):
            cached = self.store.get(url)
            if cached is not None:
                self.hits += 1
                self._emit("hit", url)
                return httpx.Response(200, text=cached, request=httpx.Request("GET", url))

        if self.offline:
            self._emit("miss", url)
            raise PageNotCachedError(url)

        response = self._client.get(url, **kwargs)
        self.misses += 1
        if response.status_code == 200:
            self.store.put(url, response.text, status=response.status_code, headers=response.headers)
        self._emit("fetch", url)
        return response

    def _emit(self, kind: str, url: str) -> None:
        if self.on_event is not None:
            try:
                self.on_event(kind, url)
            except Exception:
                pass

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "CachedClient":
        return self

    def __exit__(self, *exc_info: Any) -> bool:
        self.close()
        return False

    def __getattr__(self, item: str) -> Any:
        # Fall through to the wrapped client (e.g. ``base_url``, ``headers``).
        return getattr(self._client, item)


# ``CachedClient`` is duck-type compatible with ``httpx.Client`` for the calls
# the parser makes.  This alias keeps the annotations in the parser readable.
ClientLike = httpx.Client | CachedClient


def create_cached_client(
    *,
    limits: httpx.Limits | None = None,
    timeout: float = 15.0,
    store: PageStore | None = None,
    refresh: bool = False,
    offline: bool = False,
    on_event=None,
    headers: dict[str, str] | None = None,
    follow_redirects: bool = True,
    key_strategy: str | Callable[[str], str] | None = None,
) -> CachedClient:
    """Create an ``httpx.Client`` wrapped in a :class:`CachedClient`."""
    kwargs: dict[str, Any] = {"timeout": timeout, "follow_redirects": follow_redirects}
    if limits is not None:
        kwargs["limits"] = limits
    if headers is not None:
        kwargs["headers"] = headers
    client = httpx.Client(**kwargs)
    return CachedClient(
        client,
        store=store,
        refresh=refresh,
        offline=offline,
        on_event=on_event,
        key_strategy=key_strategy,
    )
