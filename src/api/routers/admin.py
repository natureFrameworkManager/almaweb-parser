import asyncio
import os
import queue
import signal
import subprocess
import sys
import threading
from collections.abc import AsyncIterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.sse import EventSourceResponse, ServerSentEvent
from sqlmodel import Session, col, select, func, text

from .shared import SessionDep, PROBLEM_RESPONSES
from schemas import StatsResponse, SyncRunRead
from database.database import engine
from database.model import Building, Course, Degree, Event, EventType, Faculty, Location, Module, ModuleExam, Semester, Staff, Status, CourseEventLink, CourseStaffLink, EventStaffLink, ModuleCourseLink, ModuleDegreeLink, ModuleSemesterLink, ModuleStaffLink, ModuleExamStaffLink, SyncRun

router = APIRouter(prefix="/admin", tags=["Admin"], responses=PROBLEM_RESPONSES)

# ---------------------------------------------------------------------------
# Background crawl runner
# ---------------------------------------------------------------------------

# Project root: routers/ -> api/ -> src/ -> project root (where scrapy.cfg lives)
_PROJECT_ROOT = Path(__file__).resolve().parents[3]

# SSE subscriber registry: run_id -> list of per-consumer queues.
# The background thread pushes lines (str) and a sentinel (None) into each queue.
_run_subscribers: dict[int, list["queue.Queue[str | None]"]] = {}
_run_subscribers_lock = threading.Lock()


def _run_crawl(run_id: int) -> None:
    """Launch ``scrapy crawl lecture_spider`` and persist the results to the DB."""
    process = subprocess.Popen(
        [sys.executable, "-m", "scrapy", "crawl", "lecture_spider"],
        cwd=_PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,  # line-buffered
    )

    # Persist the PID so the cancel endpoint can signal the process.
    with Session(engine) as session:
        run = session.get(SyncRun, run_id)
        if run:
            run.status = "running"
            run.pid = process.pid
            session.add(run)
            session.commit()

    # Stream output line-by-line, flushing to the DB every LOG_FLUSH_LINES lines.
    LOG_FLUSH_LINES = 20
    lines: list[str] = []
    pending: list[str] = []

    assert process.stdout is not None
    for line in process.stdout:
        lines.append(line)
        pending.append(line)
        # Push stripped line to any live SSE consumers.
        with _run_subscribers_lock:
            subs = list(_run_subscribers.get(run_id, []))
        for q in subs:
            q.put(line.rstrip("\n"))
        if len(pending) >= LOG_FLUSH_LINES:
            log_so_far = "".join(lines)
            with Session(engine) as session:
                run = session.get(SyncRun, run_id)
                if run:
                    run.log = log_so_far
                    session.add(run)
                    session.commit()
            pending.clear()

    process.wait()

    # Signal all SSE consumers that the stream is done.
    with _run_subscribers_lock:
        subs = list(_run_subscribers.pop(run_id, []))
    for q in subs:
        q.put(None)

    with Session(engine) as session:
        run = session.get(SyncRun, run_id)
        if run:
            run.finished_at = datetime.now(timezone.utc)
            run.log = "".join(lines)
            run.pid = None
            if run.status != "cancelled":
                if process.returncode == 0:
                    run.status = "completed"
                else:
                    run.status = "failed"
                    run.error = f"Process exited with code {process.returncode}"
            session.add(run)
            session.commit()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/health", summary="Check system health", status_code=200)
def get_health(session: SessionDep, response: Response):
    """Return 200 if the server and database are reachable, 503 otherwise."""
    try:
        session.exec(select(text("1")))
    except Exception:
        response.status_code = 503
        return Response(status_code=503)
    return Response(status_code=200)

@router.get("/stats", summary="Get system statistics", response_model=StatsResponse)
def get_stats(
    session: SessionDep,
):
    """Retrieve various statistics about the system."""
    counts = {
        "buildings": session.exec(select(func.count()).select_from(Building)).one(),
        "courses": session.exec(select(func.count()).select_from(Course)).one(),
        "degrees": session.exec(select(func.count()).select_from(Degree)).one(),
        "events": session.exec(select(func.count()).select_from(Event)).one(),
        "event_types": session.exec(select(func.count()).select_from(EventType)).one(),
        "exams": session.exec(select(func.count()).select_from(ModuleExam)).one(),
        "faculties": session.exec(select(func.count()).select_from(Faculty)).one(),
        "locations": session.exec(select(func.count()).select_from(Location)).one(),
        "modules": session.exec(select(func.count()).select_from(Module)).one(),
        "semesters": session.exec(select(func.count()).select_from(Semester)).one(),
        "staff": session.exec(select(func.count()).select_from(Staff)).one(),
        "statuses": session.exec(select(func.count()).select_from(Status)).one(),
        "links": {
            "course_event": session.exec(select(func.count()).select_from(CourseEventLink)).one(),
            "course_staff": session.exec(select(func.count()).select_from(CourseStaffLink)).one(),
            "event_staff": session.exec(select(func.count()).select_from(EventStaffLink)).one(),
            "module_course": session.exec(select(func.count()).select_from(ModuleCourseLink)).one(),
            "module_degree": session.exec(select(func.count()).select_from(ModuleDegreeLink)).one(),
            "module_semester": session.exec(select(func.count()).select_from(ModuleSemesterLink)).one(),
            "module_staff": session.exec(select(func.count()).select_from(ModuleStaffLink)).one(),
            "module_exam_staff": session.exec(select(func.count()).select_from(ModuleExamStaffLink)).one(),
        }
    }
    return counts


@router.get("/sync", summary="List ingestion runs", response_model=list[SyncRunRead])
def list_ingestion_runs(session: SessionDep) -> list[SyncRun]:
    """Return all ingestion runs ordered by start time, newest first."""
    return list(session.exec(select(SyncRun).order_by(col(SyncRun.id).desc())).all())


@router.post("/sync", summary="Trigger data ingestion", response_model=SyncRunRead, status_code=201)
def trigger_data_ingestion(session: SessionDep) -> SyncRun:
    """Start a new scrapy crawl in the background. Returns 409 if one is already running."""
    active = session.exec(
        select(SyncRun).where(SyncRun.status.in_(["pending", "running"]))  # type: ignore[attr-defined]
    ).first()
    if active:
        raise HTTPException(status_code=409, detail=f"A crawl is already in progress (run id={active.id})")

    run = SyncRun(status="pending", started_at=datetime.now(timezone.utc))
    session.add(run)
    session.commit()
    session.refresh(run)

    thread = threading.Thread(target=_run_crawl, args=(run.id,), daemon=True)
    thread.start()

    return run


@router.get("/sync/{run_id}", summary="Get ingestion run details", response_model=SyncRunRead)
def get_ingestion_run(run_id: int, session: SessionDep) -> SyncRun:
    """Return details for a single ingestion run."""
    run = session.get(SyncRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Sync run {run_id} not found")
    return run


def _get_run_or_404(run_id: int) -> SyncRun:
    """Dependency: fetch SyncRun by id and raise 404 if missing.

    Opens and closes its own session immediately so the DB connection is not
    held open for the entire lifetime of a long-running SSE stream.
    """
    with Session(engine) as s:
        run = s.get(SyncRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Sync run {run_id} not found")
    return run


@router.get(
    "/sync/{run_id}/log",
    summary="Stream live log output via SSE",
    response_class=EventSourceResponse,
)
async def stream_run_log(
    run_id: int,
    run: Annotated[SyncRun, Depends(_get_run_or_404)],
) -> AsyncIterable[ServerSentEvent]:
    """
    Open a Server-Sent Events stream for the given ingestion run.

    - **Running run**: streams new log lines as they are produced; sends a final
      ``event: done`` when the crawl finishes.
    - **Finished run**: replays the stored log line-by-line then closes.
    - Each unnamed event carries one log line as ``data``.
    - Keepalive pings, ``Cache-Control``, and ``X-Accel-Buffering`` are managed
      automatically by ``EventSourceResponse``.
    """
    if run.status not in ("pending", "running"):
        for line in run.log.splitlines():
            yield ServerSentEvent(raw_data=line)
        yield ServerSentEvent(raw_data="", event="done")
        return

    q: queue.Queue[str | None] = queue.Queue()
    with _run_subscribers_lock:
        _run_subscribers.setdefault(run_id, []).append(q)
    loop = asyncio.get_event_loop()
    try:
        while True:
            try:
                item: str | None = await loop.run_in_executor(
                    None, lambda: q.get(timeout=30.0)
                )
            except queue.Empty:
                continue  # EventSourceResponse sends keepalive pings automatically
            if item is None:
                yield ServerSentEvent(raw_data="", event="done")
                return
            yield ServerSentEvent(raw_data=item)
    finally:
        with _run_subscribers_lock:
            subs = _run_subscribers.get(run_id, [])
            if q in subs:
                subs.remove(q)


@router.post("/sync/{run_id}/cancel", summary="Cancel an ingestion run", response_model=SyncRunRead)
def cancel_ingestion_run(run_id: int, session: SessionDep) -> SyncRun:
    """Send SIGTERM to a running crawl process and mark the run as cancelled."""
    run = session.get(SyncRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Sync run {run_id} not found")
    if run.status not in ("pending", "running"):
        raise HTTPException(status_code=409, detail=f"Cannot cancel a run with status '{run.status}'")

    if run.pid is not None:
        try:
            os.kill(run.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass  # Process already exited; still mark as cancelled

    run.status = "cancelled"
    run.finished_at = datetime.now(timezone.utc)
    session.add(run)
    session.commit()
    session.refresh(run)
    return run