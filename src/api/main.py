import os
import sys
from pathlib import Path
from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from contextlib import asynccontextmanager

# Make sibling top-level packages (e.g. database) importable when running this file directly.
SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from database.database import create_db_and_tables
from routers import modules, events, courses, admin, catalog, degrees, faculties, locations, schedule, semesters, staff, exams, achievements
from schemas import Problem

HTTP_STATUS_TITLES: dict[int, str] = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    409: "Conflict",
    422: "Unprocessable Content",
    500: "Internal Server Error",
}


def _problem_response(status: int, detail: str | None, instance: str | None = None) -> JSONResponse:
    title = HTTP_STATUS_TITLES.get(status, "Error")
    body = Problem(status=status, title=title, detail=detail, instance=instance)
    return JSONResponse(
        status_code=status,
        content=body.model_dump(exclude_none=True),
        headers={"Content-Type": "application/problem+json"},
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield

# --- Read proxy path from environment (Defaults to /almaweb/v1 for production) ---
PROXY_ROOT_PATH = os.getenv("PROXY_ROOT_PATH", "/almaweb/v1")

app = FastAPI(
    lifespan=lifespan,
    title="AlmaWeb API",
    summary="Parsed data from AlmaWeb in a structured format",
    description=(
        "API for accessing parsed data from AlmaWeb, which includes modules, courses, events, exams and achievements. "
        "Faster and more convenient than navigating the large website tree directly, with additional "
        "filtering and querying capabilities."
        "\n\n### Query parameter conventions\n"
        "- **Unknown parameters are ignored.** Only the parameters listed for an endpoint have an effect; "
        "any other query parameter is silently dropped and does not change the result. Always rely on the "
        "per-endpoint parameter list in this schema."
        "\n- **Unimplemented parameters** are documented as `NOT IMPLEMENTED` in their description: they are "
        "accepted for forward compatibility but currently match nothing because the underlying data is not "
        "populated by the parser."
        "\n- **Repeated parameters** (`?id=1&id=2`) are combined with `OR` inside one filter; different filters "
        "are combined with `AND`."
        "\n- **`sort` / `order`** accept a single column only; multi-level sorting has to be applied client-side."
        "\n- **Pagination** (`page` / `page_size`) is disabled unless both are supplied."
        "\n\n### Data notes\n"
        "- **Free-text fields keep the source line breaks.** Where AlmaWeb used a line break "
        "(`<br>`), the stored text contains `\\n`; every line is whitespace-normalised. This applies to "
        "module `goals`, `content`, `exam_prerequisites`, `literature`, `elective_prerequisites`, "
        "`elective_classification`, `grading_note` and to course `official_description`, `organisational` "
        "and `literature`.\n"
        "- **`Module.prerequisites`** is a map keyed by study-programme context (or the generic key "
        "`allgemein`); each value is the requirement text for that context."
    ),
    version="1.2.1",
    root_path=PROXY_ROOT_PATH
)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return _problem_response(exc.status_code, detail, str(request.url))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    detail = "; ".join(
        f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}" for e in errors
    )
    return _problem_response(422, detail, str(request.url))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

api_router = APIRouter(prefix="")
api_router.include_router(modules.router)
api_router.include_router(courses.router)
api_router.include_router(events.router)
api_router.include_router(exams.router)
api_router.include_router(achievements.router)
api_router.include_router(degrees.router)
api_router.include_router(staff.router)
api_router.include_router(locations.location_router)
api_router.include_router(locations.room_router)
api_router.include_router(faculties.router)
api_router.include_router(semesters.router)
api_router.include_router(schedule.router)
api_router.include_router(catalog.router)
api_router.include_router(admin.router)
app.include_router(api_router)