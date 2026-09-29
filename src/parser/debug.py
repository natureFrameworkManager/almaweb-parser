"""Single-page debug harness for the parser.

Lets you fetch, store and parse one AlmaWeb page at a time, so a parser bug can
be reproduced and fixed in seconds instead of a full crawl.  Fetched pages are
written to the on-disk page store (see :mod:`src.parser.fetch`), so repeated
runs are offline and every page stays inspectable.

Examples::

    # Download and store a page (also prints the stored file path)
    python -m src.parser.debug fetch "https://almaweb.uni-leipzig.de/.../MODULEDETAILS..."

    # Parse a module straight from the network, a stored page or a local file
    python -m src.parser.debug parse-module "https://..." --path "Root" --path "SoSe 26"
    python -m src.parser.debug parse-module .pagedata/ab/abcdef....html

    # Parse a course / a room page
    python -m src.parser.debug parse-course "https://..."
    python -m src.parser.debug parse-room "https://..." --offline
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, time
from pathlib import Path

try:
    from .fetch import KEY_STRATEGIES, create_cached_client
    from .module_parser import parseModule
    from .course_parser import parseCourse
    from .room_parser import parseRoom, set_room_fetch_enabled, backfill_room_name_cache
except (ImportError, ModuleNotFoundError):
    from src.parser.fetch import KEY_STRATEGIES, create_cached_client  # type: ignore
    from src.parser.module_parser import parseModule  # type: ignore
    from src.parser.course_parser import parseCourse  # type: ignore
    from src.parser.room_parser import parseRoom, set_room_fetch_enabled, backfill_room_name_cache  # type: ignore


def _json_default(value):
    if isinstance(value, (date, time)):
        return value.isoformat()
    return str(value)


def _print_json(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=_json_default))


def _fetch_text(client, target: str) -> str:
    """Return HTML for a URL (via the cached client) or a local file path."""
    if target.startswith("http://") or target.startswith("https://"):
        response = client.get(target)
        response.raise_for_status()
        return response.text
    path = Path(target)
    if path.is_file():
        return path.read_text(encoding="utf-8", errors="replace")
    raise SystemExit(f"Not a URL and not an existing file: {target}")


def _add_common_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("target", help="URL, stored page path or local HTML file.")
    parser.add_argument("--offline", action="store_true", help="Never touch the network.")
    parser.add_argument("--refresh", action="store_true", help="Re-download instead of using the page store.")
    parser.add_argument("--no-rooms", action="store_true", help="Skip room detail fetches.")
    parser.add_argument(
        "--key-strategy",
        choices=KEY_STRATEGIES,
        default="exact",
        help="Page-store URL key strategy (default: exact).",
    )


def _cmd_fetch(args) -> int:
    with create_cached_client(offline=args.offline, refresh=args.refresh) as client:
        if args.target.startswith("http"):
            response = client.get(args.target)
            print(f"status={response.status_code}")
            if response.status_code == 200:
                print(f"stored at {client.store.path_for(args.target)}")
            return 0 if response.status_code == 200 else 1
        text = _fetch_text(client, args.target)
        print(f"local file {args.target}: {len(text)} chars")
        return 0


def _cmd_parse_module(args) -> int:
    if args.no_rooms:
        set_room_fetch_enabled(False)
    with create_cached_client(offline=args.offline, refresh=args.refresh) as client:
        html = _fetch_text(client, args.target)
        module = parseModule(html, path=list(args.path or []), client=client)
    if module is None:
        print("parseModule returned None", file=sys.stderr)
        return 1
    _print_json(module)
    return 0


def _cmd_parse_course(args) -> int:
    if args.no_rooms:
        set_room_fetch_enabled(False)
    with create_cached_client(offline=args.offline, refresh=args.refresh) as client:
        html = _fetch_text(client, args.target)
        course = parseCourse(html, client=client)
    if course is None:
        print("parseCourse returned None", file=sys.stderr)
        return 1
    _print_json(course)
    return 0


def _cmd_parse_room(args) -> int:
    with create_cached_client(offline=args.offline, refresh=args.refresh) as client:
        html = _fetch_text(client, args.target)
    room = parseRoom(html)
    if room is None:
        print("parseRoom returned None", file=sys.stderr)
        return 1
    _print_json(room)
    return 0


def _cmd_backfill_rooms(args) -> int:
    stats = backfill_room_name_cache(progress=print)
    print(f"Backfilled room-name index: scanned={stats['scanned']}, indexed={stats['indexed']}.")
    return 0


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch and parse single AlmaWeb pages for debugging.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch = subparsers.add_parser("fetch", help="Download and store a page.")
    _add_common_flags(fetch)
    fetch.set_defaults(func=_cmd_fetch)

    parse_module = subparsers.add_parser("parse-module", help="Parse a module page.")
    _add_common_flags(parse_module)
    parse_module.add_argument(
        "--path",
        action="append",
        default=[],
        help="A navigation path node (repeatable), e.g. --path 'Root' --path 'SoSe 26'.",
    )
    parse_module.set_defaults(func=_cmd_parse_module)

    parse_course = subparsers.add_parser("parse-course", help="Parse a course page.")
    _add_common_flags(parse_course)
    parse_course.set_defaults(func=_cmd_parse_course)

    parse_room = subparsers.add_parser("parse-room", help="Parse a room detail page.")
    _add_common_flags(parse_room)
    parse_room.set_defaults(func=_cmd_parse_room)

    backfill = subparsers.add_parser(
        "backfill-rooms",
        help="Index already-stored room pages by room name so re-parses work fully offline.",
    )
    backfill.add_argument(
        "--key-strategy",
        choices=KEY_STRATEGIES,
        default="exact",
        help="Page-store URL key strategy (default: exact).",
    )
    backfill.set_defaults(func=_cmd_backfill_rooms)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    if args.key_strategy != "exact":
        # The page-store singleton reads this lazily on first use.
        os.environ["ALMAWEB_PAGE_KEY_STRATEGY"] = args.key_strategy
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
