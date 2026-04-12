import sys
from pathlib import Path
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# Make sibling top-level packages (e.g. database) importable when running this file directly.
SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from database.database import create_db_and_tables
from routers import modules, events, courses, admin, catalog, degrees, faculties, locations, schedule, semesters, staff

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield


app = FastAPI(
    lifespan=lifespan,
    title="AlmaWeb API",
    summary="Parsed data from AlmaWeb in a structured format",
    description="API for accessing parsed data from AlmaWeb, which includes modules, courses, and events. Faster and more convenient than navigating the large website tree directly, with additional filtering and querying capabilities.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

api_router = APIRouter(prefix="/api")
api_router.include_router(modules.router)
api_router.include_router(courses.router)
api_router.include_router(events.router)
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