"""Standalone parser runner: re-parse modules from a crawl snapshot.

Crawling and parsing are decoupled: the spider writes a snapshot of every module
link it found (see :mod:`src.parser.snapshot`), and this CLI re-parses from that
snapshot.  Combined with the on-disk page store (:mod:`src.parser.fetch`) a
re-parse is offline and fast, so parser changes can be iterated on quickly.

Examples::

    # Re-parse everything from the latest crawl snapshot (uses cached pages)
    python -m src.parser.run_parse

    # Only modules matching a regex, refreshing pages from the network first
    python -m src.parser.run_parse --only "Rechnernetze" --refresh

    # Offline replay, resuming where the previous run stopped, dumping each module
    python -m src.parser.run_parse --offline --resume --dump-dir debug/modules

    # Skip room detail fetches
    python -m src.parser.run_parse --no-rooms --progress
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from datetime import date, time
from pathlib import Path
from threading import Event

try:
    from .snapshot import DEFAULT_SNAPSHOT_DIR, LATEST_MODULES_FILE, filter_modules, load_modules
    from .module_parser import handleModuleList
    from .progress import ProgressTracker
    from .room_parser import set_room_fetch_enabled
    from .fetch import KEY_STRATEGIES, PageStore
except (ImportError, ModuleNotFoundError):
    from src.parser.snapshot import DEFAULT_SNAPSHOT_DIR, LATEST_MODULES_FILE, filter_modules, load_modules  # type: ignore
    from src.parser.module_parser import handleModuleList  # type: ignore
    from src.parser.progress import ProgressTracker  # type: ignore
    from src.parser.room_parser import set_room_fetch_enabled  # type: ignore
    from src.parser.fetch import KEY_STRATEGIES, PageStore  # type: ignore


def _json_default(value):
    if isinstance(value, (date, time)):
        return value.isoformat()
    return str(value)


def _slug(value: str, max_length: int = 60) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")
    return slug[:max_length] or "module"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Parse modules from a crawl snapshot without crawling again."
    )
    parser.add_argument(
        "--snapshot",
        default=str(Path(DEFAULT_SNAPSHOT_DIR) / LATEST_MODULES_FILE),
        help="Crawl snapshot to read modules from.",
    )
    parser.add_argument("--only", default=None, help="Regex matched against the module name.")
    parser.add_argument("--number", default=None, help="Substring matched against the module name/number.")
    parser.add_argument("--path-contains", default=None, help="Substring matched against any path node.")
    parser.add_argument("--semester", default=None, help="Substring matched against any path node (e.g. SoSe26).")
    parser.add_argument("--limit", type=int, default=None, help="Parse at most N modules.")
    parser.add_argument("--refresh", action="store_true", help="Re-download pages instead of using the page store.")
    parser.add_argument("--offline", action="store_true", help="Never touch the network; fail on cache misses.")
    parser.add_argument("--resume", action="store_true", help="Skip modules listed in the processed file.")
    parser.add_argument(
        "--processed-file",
        default=str(Path(DEFAULT_SNAPSHOT_DIR) / "processed_modules.txt"),
        help="File tracking successfully parsed module URLs (for --resume).",
    )
    parser.add_argument("--dump-dir", default=None, help="Write each parsed module as a JSON file here.")
    parser.add_argument("--no-rooms", action="store_true", help="Skip room detail fetches entirely.")
    parser.add_argument("--progress", action="store_true", help="Show rich progress bars.")
    parser.add_argument(
        "--key-strategy",
        choices=KEY_STRATEGIES,
        default="exact",
        help="Page-store URL key strategy (default: exact). See src/parser/fetch.py.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    snapshot_path = Path(args.snapshot)
    if not snapshot_path.is_file():
        print(f"Snapshot not found: {snapshot_path}", file=sys.stderr)
        print("Run the spider once (optionally with -a crawl_only=1) to create it.", file=sys.stderr)
        return 2

    modules = load_modules(snapshot_path)
    total_available = len(modules)
    modules = filter_modules(
        modules,
        only=args.only,
        number=args.number,
        path_contains=args.path_contains,
        semester=args.semester,
        limit=args.limit,
    )

    processed_path = Path(args.processed_file)
    if args.resume and processed_path.is_file():
        processed = {
            line.strip() for line in processed_path.read_text(encoding="utf-8").splitlines() if line.strip()
        }
        before = len(modules)
        modules = [module for module in modules if module.url not in processed]
        print(f"Resume: skipped {before - len(modules)} already-processed modules.")

    if not modules:
        print(f"No modules to parse (snapshot has {total_available}).")
        return 0

    if args.no_rooms:
        set_room_fetch_enabled(False)

    store = None
    if args.key_strategy != "exact":
        store = PageStore(key_strategy=args.key_strategy)

    try:
        from database.database import create_db_and_tables
    except ModuleNotFoundError:
        from src.database.database import create_db_and_tables

    create_db_and_tables()

    progress_tracker = ProgressTracker(enabled=args.progress)
    if progress_tracker.enabled:
        for phase in ("modules", "courses", "events", "exams", "rooms"):
            progress_tracker.add_phase(phase, 0)
        progress_tracker.set_total("modules", len(modules))
        progress_tracker.start_parsing()

    stats = {"ok": 0, "failed": 0}
    failed_path = processed_path.parent / "failed_modules.jsonl"
    dump_dir = Path(args.dump_dir) if args.dump_dir else None
    if dump_dir is not None:
        dump_dir.mkdir(parents=True, exist_ok=True)

    def on_module_done(index, module, parsed):
        if parsed is None:
            stats["failed"] += 1
            failed_path.parent.mkdir(parents=True, exist_ok=True)
            with failed_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"name": module.name, "url": module.url}, ensure_ascii=False) + "\n")
            return
        stats["ok"] += 1
        if args.resume:
            processed_path.parent.mkdir(parents=True, exist_ok=True)
            with processed_path.open("a", encoding="utf-8") as handle:
                handle.write(module.url + "\n")
        if dump_dir is not None:
            number = parsed.get("number", "")
            name = parsed.get("name", module.name)
            target = dump_dir / f"{_slug(f'{number}-{name}')}.json"
            target.write_text(
                json.dumps(parsed, ensure_ascii=False, indent=2, default=_json_default),
                encoding="utf-8",
            )

    print(
        f"Parsing {len(modules)} of {total_available} modules from {snapshot_path} "
        f"(offline={args.offline}, refresh={args.refresh})."
    )

    cancel_event = Event()
    try:
        handleModuleList(
            modules,
            cancel_event=cancel_event,
            progress_tracker=progress_tracker if progress_tracker.enabled else None,
            store=store,
            refresh=args.refresh,
            offline=args.offline,
            on_module_done=on_module_done,
        )
    except KeyboardInterrupt:
        cancel_event.set()
        print("Interrupted. Modules inserted so far are saved.")
    except Exception:
        traceback.print_exc()
        print(f"Parsing crashed after {stats['ok']} modules.", file=sys.stderr)
        return 1
    finally:
        if progress_tracker.enabled:
            progress_tracker.finish()

    print(f"Done. Parsed {stats['ok']} modules, failed {stats['failed']}.")
    if stats["failed"]:
        print(f"Failed modules logged to {failed_path}.")
    return 1 if stats["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
